import argparse
import asyncio
import atexit
import ctypes
import dataclasses
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

import psutil
from winotify import Notification

import autostart
import reschanger
import update_check
from reschanger import DISP_RESULTS
from tray import TrayController

# constants
TIME_STEP = 5  # seconds
CONFIG_RELOAD_EVERY = 6  # iterations -> ~30 s
RECONCILE_EVERY = 12  # iterations -> ~60 s, rarer than TIME_STEP (D-4, D-7)

PROJECT_NAME = "SRR"
PROJECT_DISPLAY_NAME = "Smart Refresh Rate"
PROJECT_EXECUTABLE = PROJECT_NAME + ".exe"
UNINSTALL_REG_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{PROJECT_NAME}"

PATH_APPDATA_LOCAL = Path(os.environ["LOCALAPPDATA"]).resolve()
PATH_TO_PROGRAM = PATH_APPDATA_LOCAL / PROJECT_NAME
PATH_CURRENT_FILE = Path(sys.argv[0]).resolve()
PATH_BASE_DIR = PATH_CURRENT_FILE.parent
PATH_CONFIG = PATH_TO_PROGRAM / "config.json"
PATH_LOG = PATH_TO_PROGRAM / "logs.txt"

# single-instance mutex handle kept alive for process lifetime
_mutex_handle = None


def _resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", PATH_BASE_DIR))
    return base / rel


PATH_ICON = _resource_path("assets/icon.png")

# runtime state
_shutdown_event: Optional[asyncio.Event] = None
_reload_event: Optional[asyncio.Event] = None
_tray: Optional[TrayController] = None
_last_notified_update_version: Optional[str] = None

config_last_state: Optional[Dict[str, Tuple["ScreenSettings", "ScreenSettings"]]] = None
config_last_update = None
config_last_target: Optional[str] = None


@dataclasses.dataclass
class ScreenSettings:
    width: int
    height: int
    refresh_rate: int

    def __iter__(self) -> Iterator[int]:
        return iter([self.width, self.height, self.refresh_rate])


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    replaced = False
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp, path)
        replaced = True
    finally:
        if not replaced:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def _tray_notify(message: str, title: str = "SRR") -> None:
    if _tray is not None:
        _tray.notify(message, title)


def _show_winotify(title: str, msg: str) -> None:
    try:
        Notification(app_id=PROJECT_NAME, title=title, msg=msg).show()
    except Exception as e:
        logging.warning(f"winotify failed: {e}")


async def _run_update_check() -> None:
    """One update check (startup / 24h / on-demand): set tray status + notify
    on a new version (dedup via _last_notified_update_version), or clear stale
    status to "No updates yet" when there is none (D-2)."""
    global _last_notified_update_version
    if _tray is None:
        return
    try:
        ver = await update_check.check_for_updates()
    except Exception as e:
        logging.warning(f"update check failed: {e}")
        ver = None
    if ver:
        _tray.set_update_available(ver)
        if ver != _last_notified_update_version:
            _tray_notify(f"Update available: v{ver}", "SRR")
            _last_notified_update_version = ver
    else:
        _tray.set_update_available(None)


def _release_mutex() -> None:
    global _mutex_handle
    if _mutex_handle:
        try:
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            k.CloseHandle.restype = ctypes.c_int
            k.CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None


def _acquire_single_instance_mutex() -> None:
    global _mutex_handle
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        _mutex_handle = kernel32.CreateMutexW(None, 0, "Local\\SRR.SingleInstance")
        if _mutex_handle and ctypes.get_last_error() == 183:
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "SRR is already running. Please close the existing instance in the system tray before starting a new one.",
                    "SRR",
                    0x40,
                )
            except Exception:
                pass
            sys.exit(0)
        atexit.register(_release_mutex)
    except SystemExit:
        raise
    except Exception as e:
        logging.warning(f"mutex check failed: {e}")


def write_logs(e: BaseException, show_dialog: bool = True):
    logging.error(f"Error occurred: {e}", exc_info=e)
    if show_dialog:
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                f"The SRR program terminated with the following error:\n{e}",
                "Error",
                0x00000010,
            )
        except Exception:
            pass


def cur_power_state() -> Optional[bool]:
    """Returns True if AC, False if on battery, None if no battery info."""
    try:
        bat = psutil.sensors_battery()
    except Exception as e:
        logging.warning(f"sensors_battery failed: {e}")
        return None
    if bat is None:
        return None
    return bool(bat.power_plugged)


def build_display_map() -> Dict[str, bytes]:
    """Returns {monitor_id: adapter_name} for all currently active displays."""
    return {
        d["monitor_id"]: d["adapter_name"] for d in reschanger.get_active_displays()
    }


_CONFIG_RESERVED_KEYS = {"target_display", "notifications"}


async def load_config(
    force: bool = False,
) -> Optional[Dict[str, Tuple[ScreenSettings, ScreenSettings]]]:
    global config_last_state, config_last_update, config_last_target
    try:
        update_time = os.path.getmtime(PATH_CONFIG)
    except OSError as e:
        logging.error(f"config not accessible: {e}")
        return config_last_state

    if not force and config_last_update == update_time:
        return config_last_state

    try:
        with open(PATH_CONFIG, "r") as f:
            raw = json.load(f)

        result: Dict[str, Tuple[ScreenSettings, ScreenSettings]] = {}
        for monitor_id, entry in raw.items():
            if monitor_id in _CONFIG_RESERVED_KEYS:
                continue
            perf = ScreenSettings(**entry["performance-state"])
            psav = ScreenSettings(**entry["powersave-state"])
            result[monitor_id] = (perf, psav)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logging.error(f"config parse failed, keeping previous: {e}")
        try:
            bak = PATH_CONFIG.with_name("config.json.bak")
            shutil.copy2(PATH_CONFIG, bak)
        except Exception:
            pass
        _tray_notify("config.json is invalid — keeping previous settings.")
        return config_last_state

    # silently ignore legacy `notifications` key if present (compat, no error, no persistence)
    # (legacy field is filtered on next write via save_target_display)
    config_last_update = update_time
    config_last_state = result
    config_last_target = raw.get("target_display", None)
    return config_last_state


def save_target_display(mid: Optional[str]) -> None:
    global config_last_target
    config_last_target = mid
    try:
        existing: dict = {}
        if PATH_CONFIG.exists():
            with open(PATH_CONFIG, "r") as f:
                existing = json.load(f)
            if not isinstance(existing, dict):
                existing = {}
        existing["target_display"] = mid
        # drop legacy notifications field if present
        existing.pop("notifications", None)
        PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(PATH_CONFIG, existing)
    except Exception as e:
        logging.warning(f"failed to save target_display: {e}")


async def change_screen_settings(ss: ScreenSettings, adapter_name: bytes) -> None:
    logging.info(f"Changing {adapter_name!r} to {ss}")

    def _set_resolution() -> Optional[int]:
        try:
            return reschanger.set_resolution(*ss, adapter_name=adapter_name)
        except RuntimeError as e:
            msg = f"Skipping {adapter_name!r}: {e}"
            logging.warning(msg)
            _tray_notify(msg)
            return None

    res = _set_resolution()
    if res is None:
        return

    if res == DISP_RESULTS.DISP_CHANGE_BADPARAM:
        msg = f"Unsupported display mode in config.json for {adapter_name!r}."
        logging.error(msg)
        _tray_notify(msg)
        return

    if res != DISP_RESULTS.DISP_CHANGE_SUCCESSFUL:
        logging.warning(
            f"set_resolution returned {res} for {adapter_name!r}; retrying after 10s"
        )
        await asyncio.sleep(10)
        retry_res = _set_resolution()
        if retry_res not in (None, DISP_RESULTS.DISP_CHANGE_SUCCESSFUL):
            logging.warning(
                f"retry set_resolution returned {retry_res} for {adapter_name!r}"
            )


async def switch_rate(
    current_state: Optional[bool],
    config: Dict[str, Tuple[ScreenSettings, ScreenSettings]],
    display_map: Dict[str, bytes],
) -> None:
    if current_state is None:
        return
    for monitor_id, (perf, powersave) in config.items():
        adapter_name = display_map.get(monitor_id)
        if adapter_name is None:
            logging.debug(f"monitor {monitor_id!r} not active, skipping")
            continue
        await change_screen_settings(perf if current_state else powersave, adapter_name)


def _state_label(state: Optional[bool]) -> str:
    if state is None:
        return "no battery info"
    return "AC (performance)" if state else "Battery (powersave)"


_MANUFACTURER_CODES: Dict[str, str] = {
    "AUO": "AU Optronics", "BOE": "BOE", "CMN": "Chimei Innolux",
    "INN": "Innolux", "LGD": "LG Display", "SDC": "Samsung Display",
    "SHP": "Sharp", "HSD": "HannStar", "LEN": "Lenovo", "APP": "Apple",
    "DEL": "Dell", "HWP": "HP", "ACR": "Acer", "VSC": "ViewSonic",
    "BNQ": "BenQ", "NEC": "NEC", "SAM": "Samsung", "PHL": "Philips",
}


def _format_model_code(model_code: str) -> str:
    prefix, suffix = model_code[:3].upper(), model_code[3:]
    manufacturer = _MANUFACTURER_CODES.get(prefix, prefix)
    return f"{manufacturer} {suffix}" if suffix else manufacturer


def _format_display_name(
    adapter_name: bytes, monitor_id: str, monitor_string: str
) -> str:
    adapter_str = adapter_name.decode("ascii", errors="replace").strip("\x00")
    idx = adapter_str.upper().rfind("DISPLAY")
    num = adapter_str[idx + 7:].strip() if idx >= 0 else "?"
    parts = [p for p in monitor_id.split("\\") if p]
    model_code = parts[1] if len(parts) >= 2 else ""
    name = (
        reschanger.get_monitor_friendly_name(monitor_id)
        or (_format_model_code(model_code) if model_code else None)
        or monitor_string.strip()
        or "Unknown display"
    )
    return f"Display {num} — {name}"


async def srr_loop() -> None:
    assert _shutdown_event is not None
    assert _reload_event is not None

    last_state = cur_power_state()
    current_config = await load_config()
    display_map = build_display_map()

    if _tray is not None:
        _tray.set_state_text(_state_label(last_state))
    counter = 0
    reconcile_counter = 0
    last_update_check = time.monotonic()

    loop = asyncio.get_running_loop()
    managed_display_id: Optional[str] = config_last_target

    def _set_managed_display(mid: Optional[str]) -> None:
        nonlocal managed_display_id
        managed_display_id = mid
        logging.info(f"tray: managed display set to {mid!r}")
        save_target_display(mid)

    def _refresh_tray_displays() -> None:
        if _tray is None:
            return
        displays = [
            {
                "id": d["monitor_id"],
                "name": _format_display_name(
                    d["adapter_name"], d["monitor_id"], d["monitor_string"]
                ),
            }
            for d in reschanger.get_active_displays()
        ]
        _tray.set_displays(
            displays,
            managed_display_id,
            lambda mid: loop.call_soon_threadsafe(_set_managed_display, mid),
        )

    def _target_modes(state: bool) -> Dict[str, ScreenSettings]:
        if current_config is None:
            return {}
        return {
            mid: (perf if state else psav)
            for mid, (perf, psav) in current_config.items()
            if display_map.get(mid) is not None
            and (managed_display_id is None or mid == managed_display_id)
        }

    async def _do_switch(state: bool) -> None:
        nonlocal display_map
        assert current_config is not None

        # A monitor can disappear between the power event and this switch.
        # Refresh the snapshot so a disconnected adapter is not used.
        display_map = build_display_map()
        _refresh_tray_displays()
        targets = _target_modes(state)
        filtered_map = {mid: display_map[mid] for mid in targets if mid in display_map}
        await switch_rate(state, current_config, filtered_map)

    _refresh_tray_displays()

    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=TIME_STEP)
            break
        except asyncio.TimeoutError:
            pass

        if _reload_event.is_set():
            _reload_event.clear()
            if _tray is not None:
                try:
                    _tray.refresh_icon()
                except Exception:
                    pass
            current_config = await load_config(force=True)
            display_map = build_display_map()
            _refresh_tray_displays()
            if current_config is not None:
                state = cur_power_state()
                if state is not None:
                    await _do_switch(state)

        if _tray is not None and _tray.paused:
            continue

        current_state = cur_power_state()

        if counter >= CONFIG_RELOAD_EVERY:
            counter = 0
            new_config = await load_config()
            display_map = build_display_map()
            _refresh_tray_displays()
            if new_config is not None and new_config != current_config:
                current_config = new_config
                _tray_notify("Config reloaded.")
                if current_state is not None:
                    await _do_switch(current_state)
        counter += 1

        # Periodic update check every 24h (86400s) — dedup notify (FIX 4)
        if time.monotonic() - last_update_check >= 86400:
            last_update_check = time.monotonic()
            await _run_update_check()

        # Sleep-wake reconciliation: at a rarer interval than TIME_STEP
        # (RECONCILE_EVERY ticks ~60s) compare live current display settings
        # (ENUM_CURRENT_SETTINGS, not registry) against desired for the
        # current power state; if mismatched (e.g. after resume without
        # power toggle) re-apply via _do_switch. No registry write.
        if reconcile_counter >= RECONCILE_EVERY:
            reconcile_counter = 0
            if (
                current_config is not None
                and current_state is not None
                and (_tray is None or not _tray.paused)
            ):
                try:
                    targets = _target_modes(current_state)
                    needs_reconcile = False
                    for mid, desired in targets.items():
                        adapter = display_map.get(mid)
                        if adapter is None:
                            continue
                        try:
                            w, h, freq = reschanger.get_display_settings(
                                adapter, reschanger.ENUM_CURRENT_SETTINGS
                            )
                        except RuntimeError:
                            continue
                        if (w, h, freq) != tuple(desired):
                            needs_reconcile = True
                            break
                    if needs_reconcile:
                        logging.info(
                            "reconcile: live settings diverged from desired, re-applying"
                        )
                        await _do_switch(current_state)
                except Exception as e:
                    logging.warning(f"reconcile check failed: {e}")
        reconcile_counter += 1

        if current_state != last_state and current_config is not None:
            if current_state is not None:
                await _do_switch(current_state)
            if _tray is not None:
                _tray.set_state_text(_state_label(current_state))

        last_state = current_state


async def get_processes(app_name: str):
    out = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if p.info["name"] != app_name:
                continue
            if p.info["exe"] == str(PATH_CURRENT_FILE) or p.pid == os.getpid():
                continue
            out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def _register_uninstall(target_exe: Path) -> bool:
    try:
        import winreg
        uninstall_cmd = f'"{target_exe}" --uninstall'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY) as key:
            winreg.SetValueEx(key, "DisplayName",     0, winreg.REG_SZ,    PROJECT_DISPLAY_NAME)
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ,    uninstall_cmd)
            winreg.SetValueEx(key, "DisplayIcon",     0, winreg.REG_SZ,    f'"{target_exe}",0')
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ,    str(target_exe.parent))
            winreg.SetValueEx(key, "NoModify",        0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair",        0, winreg.REG_DWORD, 1)
        logging.info("uninstall registry entry registered")
        return True
    except Exception as e:
        logging.warning(f"_register_uninstall failed: {e}")
        return False


def _uninstall() -> None:
    target_exe = PATH_TO_PROGRAM / PROJECT_EXECUTABLE

    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if p.info["name"] == PROJECT_EXECUTABLE and p.pid != os.getpid():
                p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    autostart.disable(PROJECT_NAME)

    start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    shortcut = start_menu / f"{PROJECT_NAME}.lnk"
    try:
        shortcut.unlink(missing_ok=True)
    except Exception as e:
        logging.warning(f"shortcut removal failed: {e}")

    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY)
    except Exception as e:
        logging.warning(f"uninstall key removal failed: {e}")

    # Delete install dir after process exits — PowerShell runs detached
    ps_cmd = f'Start-Sleep -Seconds 2; Remove-Item -Recurse -Force "{PATH_TO_PROGRAM}"'
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_cmd],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    ctypes.windll.user32.MessageBoxW(
        None, f"{PROJECT_DISPLAY_NAME} has been uninstalled.", PROJECT_DISPLAY_NAME, 0x40
    )
    sys.exit(0)


def _create_start_menu_shortcut(target_exe: Path) -> bool:
    start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    shortcut = start_menu / f"{PROJECT_NAME}.lnk"
    script = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{shortcut}");'
        f'$s.TargetPath="{target_exe}";'
        f'$s.WorkingDirectory="{target_exe.parent}";'
        f'$s.Description="Smart Refresh Rate";'
        f'$s.Save()'
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            logging.warning(f"start menu shortcut failed: rc={result.returncode} {result.stderr!r}")
            return False
        if not shortcut.exists():
            logging.warning(f"start menu shortcut not found after creation: {shortcut}")
            return False
        logging.info(f"start menu shortcut created: {shortcut}")
        return True
    except Exception as e:
        logging.warning(f"start menu shortcut failed: {e}")
        return False


async def install():
    """Copy exe into %LOCALAPPDATA%\\SRR, register autostart, restart from there."""
    if PATH_BASE_DIR == PATH_TO_PROGRAM:
        return
    if PATH_CURRENT_FILE.suffix.lower() != ".exe":
        return

    logging.info("Installer: relocating to %s", PATH_TO_PROGRAM)

    for inst in await get_processes(PROJECT_EXECUTABLE):
        try:
            inst.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    await asyncio.sleep(2)

    PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
    target_exe = PATH_TO_PROGRAM / PROJECT_EXECUTABLE
    start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    shortcut = start_menu / f"{PROJECT_NAME}.lnk"
    _autostart_was_enabled = autostart.is_enabled(PROJECT_NAME)
    _we_enabled_autostart = False
    try:
        try:
            shutil.copy2(PATH_CURRENT_FILE, target_exe)
        except OSError as e:
            raise RuntimeError(f"Failed to copy executable to {target_exe}: {e}") from e

        if not autostart.enable(PROJECT_NAME, target_exe):
            raise RuntimeError("Failed to register autostart")
        _we_enabled_autostart = True

        if not _register_uninstall(target_exe):
            raise RuntimeError("Failed to register uninstall entry")

        if not _create_start_menu_shortcut(target_exe):
            raise RuntimeError("Failed to create Start Menu shortcut")

        try:
            os.startfile(str(target_exe))
        except OSError as e:
            raise RuntimeError(f"Failed to launch installed copy: {e}") from e

        _show_winotify("SRR installed", "SRR now runs in background. A tray icon will appear.")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        logging.error(f"install failed: {e}")
        # rollback best-effort in reverse order (shortcut → autostart → exe → uninstall key)
        try:
            if shortcut.exists():
                shortcut.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if _we_enabled_autostart and not _autostart_was_enabled:
                autostart.disable(PROJECT_NAME)
        except Exception:
            pass
        try:
            if target_exe.exists():
                target_exe.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            import winreg
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY)
            except FileNotFoundError:
                pass
        except Exception:
            pass
        msg = f"Installation failed:\n{e}\n\nChanges have been rolled back."
        try:
            ctypes.windll.user32.MessageBoxW(None, msg, "SRR Installation Error", 0x10)
        except Exception:
            pass
        print(f"Installation failed: {e}", file=sys.stderr)
        sys.exit(1)


def _ensure_config() -> None:
    """
    Create or update config.json.
    Each active display gets an entry keyed by its stable monitor DeviceID.
    Existing entries are never overwritten — only new displays are appended.
    Legacy flat configs are migrated to per-monitor entries, preserving values;
    invalid entries are regenerated from registry.
    """
    existing: dict = {}
    if PATH_CONFIG.exists():
        try:
            with open(PATH_CONFIG, "r") as f:
                existing = json.load(f)
            if not isinstance(existing, dict):
                logging.warning("config is not a dict — rebuilding")
                existing = {}
        except Exception as e:
            logging.warning(f"could not read existing config: {e}")
            existing = {}

    def _valid_screen(d) -> bool:
        if not isinstance(d, dict):
            return False
        for k in ("width", "height", "refresh_rate"):
            if k not in d:
                return False
            v = d[k]
            if isinstance(v, bool):
                return False
            try:
                iv = int(v)
                if iv <= 0:
                    return False
            except Exception:
                return False
        return True

    def _valid_entry(entry) -> bool:
        if not isinstance(entry, dict):
            return False
        return _valid_screen(entry.get("performance-state")) and _valid_screen(
            entry.get("powersave-state")
        )

    changed = False

    # --- legacy flat migration (deferred until active displays known — FIX 1) ---
    has_flat = "performance-state" in existing or "powersave-state" in existing
    has_monitor_keys = any(
        k not in _CONFIG_RESERVED_KEYS
        and k not in ("performance-state", "powersave-state")
        for k in existing
    )
    # store raw candidates without mutating yet
    legacy_raw_perf = existing.get("performance-state") if has_flat else None
    legacy_raw_psav = existing.get("powersave-state") if has_flat else None

    try:
        active_displays = reschanger.get_active_displays()
    except Exception as e:
        logging.warning(f"get_active_displays failed: {e}")
        active_displays = []

    legacy_perf = None
    legacy_psav = None
    legacy_valid = False
    if has_flat:
        if not active_displays:
            logging.info(
                "legacy flat config detected but no active displays — keeping legacy config intact"
            )
            # do not pop / do not mark changed to avoid data loss (FIX 1)
        elif not has_monitor_keys:
            # pure flat format — preserve values
            legacy_perf = existing.pop("performance-state", None)
            legacy_psav = existing.pop("powersave-state", None)
            changed = True
            if _valid_screen(legacy_perf) and _valid_screen(legacy_psav):
                legacy_valid = True
                logging.info("legacy flat config detected — migrating to per-monitor format")
            else:
                logging.info(
                    "legacy flat config detected with invalid values — will regenerate from registry"
                )
                legacy_perf = None
                legacy_psav = None
        else:
            # mixed: flat keys alongside monitor entries — strip flat keys but preserve for invalid fallback (FIX 2)
            legacy_perf = existing.pop("performance-state", None)
            legacy_psav = existing.pop("powersave-state", None)
            changed = True
            if _valid_screen(legacy_perf) and _valid_screen(legacy_psav):
                legacy_valid = True
                logging.info(
                    "legacy flat keys found alongside monitor entries — removing flat keys, will use for invalid entries"
                )
            else:
                logging.info(
                    "legacy flat keys with invalid values alongside monitor entries — removing flat keys"
                )
                legacy_perf = None
                legacy_psav = None
        # keep raw vars for potential debugging (unused)
        _ = (legacy_raw_perf, legacy_raw_psav)

    for disp in active_displays:
        mid = disp["monitor_id"]
        adapter = disp["adapter_name"]
        entry = existing.get(mid)

        needs_regen = False
        if entry is None:
            needs_regen = True
        elif not _valid_entry(entry):
            logging.info(f"display {mid!r} entry invalid — regenerating")
            needs_regen = True
        else:
            coerced = False
            for state_key in ("performance-state", "powersave-state"):
                sd = entry[state_key]
                for field in ("width", "height", "refresh_rate"):
                    orig = sd[field]
                    if isinstance(orig, bool):
                        needs_regen = True
                        break
                    try:
                        iv = int(orig)
                    except Exception:
                        needs_regen = True
                        break
                    if not isinstance(orig, int) or orig != iv:
                        sd[field] = iv
                        coerced = True
                if needs_regen:
                    break
            if coerced:
                changed = True
            if not needs_regen:
                continue

        if needs_regen:
            # FIX 2: legacy should be fallback for invalid entries as well (preserve flat values)
            use_legacy = False
            if legacy_valid and legacy_perf is not None and legacy_psav is not None:
                if entry is None:
                    # missing: only use legacy for pure flat (FIX 1 keeps legacy intact only when pure)
                    if not has_monitor_keys:
                        use_legacy = True
                else:
                    # invalid entry: use legacy where present (FIX 2)
                    use_legacy = True
            if use_legacy:
                assert legacy_perf is not None and legacy_psav is not None
                existing[mid] = {
                    "performance-state": {
                        k: int(legacy_perf[k]) for k in ("width", "height", "refresh_rate")
                    },
                    "powersave-state": {
                        k: int(legacy_psav[k]) for k in ("width", "height", "refresh_rate")
                    },
                }
                logging.info(f"migrated legacy config to display {mid!r}")
                changed = True
                continue
            try:
                w, h, freq = reschanger.get_display_settings(
                    adapter, reschanger.ENUM_REGISTRY_SETTINGS
                )
            except RuntimeError as e:
                logging.warning(f"could not read registry settings for {mid!r}: {e}")
                continue
            bat_freq = reschanger.best_powersave_freq(adapter, w, h)
            existing[mid] = {
                "performance-state": {"width": w, "height": h, "refresh_rate": freq},
                "powersave-state": {"width": w, "height": h, "refresh_rate": bat_freq},
            }
            logging.info(f"added display {mid!r} ({disp['monitor_string']!r}) to config")
            changed = True

    # drop legacy notifications field if present (D-5: do not persist it back;
    # best-effort pop, no error; FIX 1 no-active-displays path still skips write)
    existing.pop("notifications", None)

    if changed or not PATH_CONFIG.exists():
        PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(PATH_CONFIG, existing)


async def srr():
    PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
    await install()
    _ensure_config()

    global _shutdown_event, _reload_event, _tray
    loop = asyncio.get_running_loop()
    _shutdown_event = asyncio.Event()
    _reload_event = asyncio.Event()
    _shutdown_ev = _shutdown_event
    _reload_ev = _reload_event

    def _request_exit():
        logging.info("shutdown requested")
        try:
            adapter_names = list(build_display_map().values())
            reschanger.set_display_defaults(adapter_names)
        except Exception as e:
            logging.warning(f"set_display_defaults failed: {e}")
        try:
            _release_mutex()
        except Exception:
            pass
        loop.call_soon_threadsafe(_shutdown_ev.set)

    def _request_reload():
        loop.call_soon_threadsafe(_reload_ev.set)

    _tray = TrayController(
        project_name=PROJECT_NAME,
        exe_path=PATH_TO_PROGRAM / PROJECT_EXECUTABLE,
        config_path=PATH_CONFIG,
        log_path=PATH_LOG,
        on_exit=_request_exit,
        on_reload=_request_reload,
        icon_path=PATH_ICON if PATH_ICON.exists() else None,
    )
    _tray.start()

    def _on_tray_check_updates():
        try:
            loop.call_soon_threadsafe(lambda: asyncio.create_task(_run_update_check()))
        except Exception as e:
            logging.warning(f"failed to schedule update check: {e}")

    _tray.set_on_check_updates(_on_tray_check_updates)
    asyncio.create_task(_run_update_check())

    cfg = await load_config()
    if cfg is not None:
        await switch_rate(cur_power_state(), cfg, build_display_map())

    await srr_loop()


async def main():
    try:
        await srr()
    except Exception as e:
        write_logs(e)
        sys.exit(1)


def _setup_logging():
    PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        PATH_LOG, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    _cli_parser = argparse.ArgumentParser(description="Smart Refresh Rate — per-monitor refresh switcher")
    _cli_parser.add_argument("--uninstall", action="store_true", help="uninstall SRR")
    _cli_parser.add_argument("--version", action="store_true", help="print version and exit")
    _cli_parser.add_argument("--config", action="store_true", help="print config path and exit")
    _args, _ = _cli_parser.parse_known_args()
    if _args.uninstall:
        _uninstall()
    if _args.version:
        try:
            from version import __version__
            print(__version__)
        except Exception:
            print("unknown")
        sys.exit(0)
    if _args.config:
        print(str(PATH_CONFIG.resolve()))
        sys.exit(0)
    _acquire_single_instance_mutex()
    _setup_logging()
    asyncio.run(main())
