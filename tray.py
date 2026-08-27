"""System tray icon for SRR. Runs pystray in a separate thread."""

import logging
import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import pystray

if TYPE_CHECKING:
    from pystray._base import Icon as _Icon
from PIL import Image, ImageDraw

import autostart
from update_check import LATEST_RELEASE_URL


def _is_light_theme() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(val)
    except Exception:
        return False


def _make_default_icon(is_light: bool = False) -> Image.Image:
    if is_light:
        bg = (245, 245, 245)
        fg = (30, 30, 30)
        accent = (30, 90, 180)
    else:
        bg = (30, 30, 30)
        fg = (120, 200, 255)
        accent = (120, 200, 255)
    # keep 64x64 crisp
    img = Image.new("RGB", (64, 64), bg)
    d = ImageDraw.Draw(img)
    # use fg/accent accordingly; light theme uses dark outline for contrast
    outline = fg if is_light else fg
    fill_accent = accent
    d.rectangle((8, 18, 56, 46), outline=outline, width=3)
    d.line((20, 32, 44, 32), fill=fill_accent, width=2)
    d.rectangle((24, 48, 40, 52), fill=fill_accent)
    return img


def _load_icon(icon_path: Optional[Path]) -> Image.Image:
    is_light = _is_light_theme()
    if icon_path and icon_path.exists():
        try:
            return Image.open(str(icon_path)).convert("RGBA")
        except Exception as e:
            logging.warning(f"failed to load tray icon {icon_path}: {e}")
    return _make_default_icon(is_light=is_light)


class TrayController:
    """
    Owns the pystray icon. The async loop reads `paused` and `state_text`,
    and triggers `reload_event` / `shutdown_event`.
    """

    def __init__(
        self,
        project_name: str,
        exe_path: Path,
        config_path: Path,
        log_path: Path,
        on_exit: Callable[[], None],
        on_reload: Callable[[], None],
        icon_path: Optional[Path] = None,
        on_check_updates: Optional[Callable[[], None]] = None,
    ):
        self.project_name = project_name
        self.exe_path = exe_path
        self.config_path = config_path
        self.log_path = log_path
        self._on_exit = on_exit
        self._on_reload = on_reload
        self._on_check_updates = on_check_updates
        self._update_version: Optional[str] = None

        self.paused = False
        self.state_text = "starting…"
        self._displays: list = []
        self._selected_display_id: Optional[str] = None
        self._on_display_select: Optional[Callable] = None
        self._icon_path = icon_path

        self._icon_image = _load_icon(icon_path)
        self._icon: Optional[_Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._menu_lock = threading.RLock()

        # Thread-safety note: verified pystray Win32 _update_menu (see
        # .venv/Lib/site-packages/pystray/_win32.py) manipulates HMenu handles
        # directly without queuing; existing code calls set_state_text/
        # set_displays from the asyncio thread, so we serialize all menu
        # mutations via _menu_lock. set_update_available is called from the
        # asyncio thread (update-check coroutine) and therefore acquires the
        # same lock to avoid racing Icon.__call__ on the tray thread.

        # Double-click detection: pystray Win32 backend has no native
        # double-click (window class style 0 lacks CS_DBLCLKS, _on_notify
        # only handles WM_LBUTTONUP / WM_RBUTTONUP). Use timing-based
        # detection by wrapping Icon.__call__ (invoked on WM_LBUTTONUP)
        # and measuring interval between activations.
        self._last_click_ts: float = 0.0
        self._DOUBLE_CLICK_INTERVAL: float = 0.4  # seconds (<400 ms)

    # --- menu actions -------------------------------------------------

    def _toggle_pause(self, icon, item):
        with self._menu_lock:
            self.paused = not self.paused
            logging.info(f"tray: paused={self.paused}")
            icon.update_menu()

    def _reload(self, icon, item):
        logging.info("tray: reload config requested")
        self._on_reload()

    def _open_config_dir(self, icon, item):
        try:
            os.startfile(str(self.config_path.parent))
        except OSError as e:
            logging.error(f"open config dir failed: {e}")

    def _open_logs(self, icon, item):
        try:
            os.startfile(str(self.log_path))
        except OSError as e:
            logging.error(f"open logs failed: {e}")

    def _toggle_autostart(self, icon, item):
        with self._menu_lock:
            if autostart.is_enabled(self.project_name):
                autostart.disable(self.project_name)
            else:
                autostart.enable(self.project_name, self.exe_path)
            icon.update_menu()

    def _exit(self, icon, item):
        logging.info("tray: exit requested")
        self._on_exit()
        icon.stop()

    def _trigger_update_check(self, icon, item):
        """Runs on the tray thread; marshals to the asyncio loop via on_check_updates."""
        if self._on_check_updates is not None:
            try:
                self._on_check_updates()
            except Exception as e:
                logging.warning(f"on_check_updates failed: {e}")
        else:
            logging.debug("update check requested but no handler")

    def _open_releases(self, icon, item):
        try:
            os.startfile(LATEST_RELEASE_URL)
        except Exception:
            try:
                webbrowser.open(LATEST_RELEASE_URL)
            except Exception as e:
                logging.warning(f"failed to open browser for update: {e}")

    # --- public api ---------------------------------------------------

    def set_update_available(self, version: Optional[str]) -> None:
        with self._menu_lock:
            self._update_version = version
        self._rebuild_menu()

    def set_on_check_updates(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_check_updates = callback

    def refresh_icon(self) -> None:
        new_img = _load_icon(self._icon_path)
        with self._menu_lock:
            self._icon_image = new_img
            if self._icon is not None:
                try:
                    self._icon.icon = new_img
                except Exception as e:
                    logging.warning(f"tray refresh_icon failed: {e}")

    def set_displays(
        self,
        displays: list,
        selected_id: Optional[str],
        on_select: Callable,
    ):
        with self._menu_lock:
            self._displays = [{"id": None, "name": "All displays"}] + displays
            self._selected_display_id = selected_id
            self._on_display_select = on_select
        self._rebuild_menu()

    def _make_display_selector(self, display_id: Optional[str]) -> Callable:
        def handler(icon, item):
            with self._menu_lock:
                self._selected_display_id = display_id
                if self._on_display_select is not None:
                    self._on_display_select(display_id)
                try:
                    icon.update_menu()
                except Exception:
                    pass
        return handler

    def _rebuild_menu(self):
        with self._menu_lock:
            if self._icon is not None:
                try:
                    self._icon.menu = self._build_menu()
                    self._icon.update_menu()
                except Exception as e:
                    logging.warning(f"tray menu rebuild failed: {e}")

    def set_state_text(self, text: str):
        with self._menu_lock:
            self.state_text = text
            if self._icon is not None:
                try:
                    self._icon.update_menu()
                    self._icon.title = f"SRR — {text}"
                except Exception:
                    pass

    def notify(self, message: str, title: str = "SRR"):
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception as e:
                logging.warning(f"tray notify failed: {e}")

    def _build_menu(self) -> pystray.Menu:
        items = [
            pystray.MenuItem(
                lambda item: f"Status: {self.state_text}", None, enabled=False
            ),
            pystray.Menu.SEPARATOR,
        ]
        if self._displays:
            items += [
                pystray.MenuItem(
                    "Target display",
                    pystray.Menu(
                        *[
                            pystray.MenuItem(
                                d["name"],
                                self._make_display_selector(d["id"]),
                                checked=lambda item, did=d["id"]: (
                                    self._selected_display_id == did
                                ),
                                radio=True,
                            )
                            for d in self._displays
                        ]
                    ),
                ),
                pystray.Menu.SEPARATOR,
            ]
        items += [
            pystray.MenuItem(
                lambda item: "Resume" if self.paused else "Pause",
                self._toggle_pause,
            ),
            pystray.MenuItem("Reload", self._reload),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open config folder", self._open_config_dir),
            pystray.MenuItem("Open logs", self._open_logs),
            pystray.MenuItem(
                "Run at startup",
                self._toggle_autostart,
                checked=lambda item: autostart.is_enabled(self.project_name),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Check for updates", self._trigger_update_check),
            pystray.MenuItem(
                lambda item: (
                    f"Update available: v{self._update_version}"
                    if self._update_version
                    else "No updates yet"
                ),
                self._open_releases,
                enabled=lambda item: bool(self._update_version),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        ]
        return pystray.Menu(*items)

    def start(self):
        # Double-click handling: pystray Win32 backend has no native
        # double-click support (window class style=0 lacks CS_DBLCLKS and
        # _on_notify only dispatches WM_LBUTTONUP/WM_RBUTTONUP). Implement
        # timing-based detection by intercepting Icon.__call__ (invoked on
        # WM_LBUTTONUP) — two activations within <400 ms are treated as a
        # double-click that reloads config; single click delegates to the
        # original Icon.__call__ to preserve default menu behavior.
        controller = self

        class _SRRIcon(pystray.Icon):  # type: ignore[misc]
            def __call__(self):  # type: ignore[override]
                now = time.monotonic()
                if now - controller._last_click_ts < controller._DOUBLE_CLICK_INTERVAL:
                    logging.info("tray: double-click detected — reloading config")
                    controller._last_click_ts = 0.0
                    try:
                        controller._on_reload()
                    except Exception as e:
                        logging.warning(f"tray double-click reload failed: {e}")
                    return
                controller._last_click_ts = now
                return super().__call__()

        icon = _SRRIcon(
            self.project_name,
            self._icon_image,
            f"SRR — {self.state_text}",
            menu=self._build_menu(),
        )
        self._icon = icon
        self._thread = threading.Thread(target=icon.run, daemon=True, name="srr-tray")
        self._thread.start()
        logging.info("tray icon started")
