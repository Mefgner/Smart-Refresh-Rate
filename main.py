import asyncio
import ctypes
import dataclasses
import json
import logging
import logging.handlers
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

import psutil

import autostart
import reschanger
from reschanger import DISP_RESULTS
from tray import TrayController

# constants
TIME_STEP = 5  # seconds; raised from 1 to reduce idle CPU usage
CONFIG_RELOAD_EVERY = 6  # iterations -> ~30 s

PROJECT_NAME = "SRR"
PROJECT_EXECUTABLE = PROJECT_NAME + ".exe"

PATH_APPDATA_LOCAL = Path(os.environ["LOCALAPPDATA"]).resolve()
PATH_TO_PROGRAM = PATH_APPDATA_LOCAL / PROJECT_NAME
PATH_CURRENT_FILE = Path(sys.argv[0]).resolve()
PATH_BASE_DIR = PATH_CURRENT_FILE.parent
PATH_CONFIG = PATH_TO_PROGRAM / "config.json"
PATH_LOG = PATH_TO_PROGRAM / "logs.txt"
PATH_ICON = PATH_BASE_DIR / "assets" / "icon.png"

# runtime state
_shutdown_event: Optional[asyncio.Event] = None
_reload_event: Optional[asyncio.Event] = None
_tray: Optional[TrayController] = None

config_last_state = None
config_last_update = None


@dataclasses.dataclass
class ScreenSettings:
    width: int
    height: int
    refresh_rate: int

    def __iter__(self) -> Iterator[int]:
        return iter([self.width, self.height, self.refresh_rate])


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


def cur_monitor_specs() -> Dict[str, Dict[str, int]]:
    logging.info("Getting current monitor specs")
    width, height, rr_max, rr_min = reschanger.get_resolution()
    return {
        "powersave-state": {"width": width, "height": height, "refresh_rate": rr_min},
        "performance-state": {"width": width, "height": height, "refresh_rate": rr_max},
    }


async def load_config(force: bool = False) -> Optional[Tuple[ScreenSettings, ScreenSettings]]:
    global config_last_state, config_last_update
    try:
        update_time = os.path.getmtime(PATH_CONFIG)
    except OSError as e:
        logging.error(f"config not accessible: {e}")
        return config_last_state

    if not force and config_last_update == update_time:
        return config_last_state

    try:
        with open(PATH_CONFIG, "r") as f:
            params = json.load(f)
        performance_state = ScreenSettings(**params["performance-state"])
        powersave_state = ScreenSettings(**params["powersave-state"])
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logging.error(f"config parse failed, keeping previous: {e}")
        if _tray is not None:
            _tray.notify("config.json is invalid — keeping previous settings.")
        return config_last_state

    config_last_update = update_time
    config_last_state = (performance_state, powersave_state)
    return config_last_state


async def change_screen_settings(ss: ScreenSettings) -> None:
    logging.info(f"Changing screen settings to {ss}")
    res = reschanger.set_resolution(*ss)

    if res == DISP_RESULTS.DISP_CHANGE_BADPARAM:
        msg = "Parameters in config.json are not a supported display mode."
        logging.error(msg)
        if _tray is not None:
            _tray.notify(msg)
        return

    if res != DISP_RESULTS.DISP_CHANGE_SUCCESSFUL:
        logging.warning(f"set_resolution returned {res}; retrying after 10s")
        await asyncio.sleep(10)
        reschanger.set_resolution(*ss)


async def switch_rate(current_state: Optional[bool], prss: ScreenSettings, psss: ScreenSettings):
    if current_state is None:
        return
    await change_screen_settings(prss if current_state else psss)


def _state_label(state: Optional[bool]) -> str:
    if state is None:
        return "no battery info"
    return "AC (performance)" if state else "Battery (powersave)"


async def srr_loop() -> None:
    assert _shutdown_event is not None
    assert _reload_event is not None
    last_state = cur_power_state()
    current_config = await load_config()
    if _tray is not None:
        _tray.set_state_text(_state_label(last_state))
    counter = 0

    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=TIME_STEP)
            break
        except asyncio.TimeoutError:
            pass

        if _reload_event.is_set():
            _reload_event.clear()
            current_config = await load_config(force=True)
            if current_config is not None:
                await switch_rate(cur_power_state(), *current_config)

        if _tray is not None and _tray.paused:
            continue

        current_state = cur_power_state()

        if counter >= CONFIG_RELOAD_EVERY:
            counter = 0
            new_config = await load_config()
            if new_config is not None and new_config != current_config:
                current_config = new_config
                if _tray is not None:
                    _tray.notify("Config reloaded.")
                await switch_rate(current_state, *current_config)
        counter += 1

        if current_state != last_state and current_config is not None:
            await switch_rate(current_state, *current_config)
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
    try:
        shutil.copy2(PATH_CURRENT_FILE, target_exe)
    except OSError as e:
        logging.error(f"copy to {target_exe} failed: {e}")
        raise

    autostart.enable(PROJECT_NAME, target_exe)

    try:
        os.startfile(str(target_exe))
    except OSError as e:
        logging.error(f"failed to launch installed copy: {e}")
        raise

    ctypes.windll.user32.MessageBoxW(
        None,
        "SRR was installed and now runs in background. A tray icon will appear.",
        "Info",
        0x00000040,
    )
    sys.exit(0)


def _ensure_config():
    if not PATH_CONFIG.exists():
        logging.info("creating default config.json")
        with open(PATH_CONFIG, "w") as f:
            json.dump(cur_monitor_specs(), f, indent=4)


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
            reschanger.set_display_defaults()
        except Exception as e:
            logging.warning(f"set_display_defaults failed: {e}")
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

    cfg = await load_config()
    if cfg is not None:
        await switch_rate(cur_power_state(), *cfg)

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
    _setup_logging()
    asyncio.run(main())
