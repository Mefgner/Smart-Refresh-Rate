"""System tray icon for SRR. Runs pystray in a separate thread."""
import logging
import os
import threading
from pathlib import Path
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

import autostart


def _make_default_icon() -> Image.Image:
    img = Image.new("RGB", (64, 64), (30, 30, 30))
    d = ImageDraw.Draw(img)
    d.rectangle((8, 18, 56, 46), outline=(120, 200, 255), width=3)
    d.line((20, 32, 44, 32), fill=(120, 200, 255), width=2)
    d.rectangle((24, 48, 40, 52), fill=(120, 200, 255))
    return img


def _load_icon(icon_path: Optional[Path]) -> Image.Image:
    if icon_path and icon_path.exists():
        try:
            return Image.open(str(icon_path))
        except Exception as e:
            logging.warning(f"failed to load tray icon {icon_path}: {e}")
    return _make_default_icon()


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
    ):
        self.project_name = project_name
        self.exe_path = exe_path
        self.config_path = config_path
        self.log_path = log_path
        self._on_exit = on_exit
        self._on_reload = on_reload

        self.paused = False
        self.state_text = "starting…"

        self._icon_image = _load_icon(icon_path)
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    # --- menu actions -------------------------------------------------

    def _toggle_pause(self, icon, item):
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
        if autostart.is_enabled(self.project_name):
            autostart.disable(self.project_name)
        else:
            autostart.enable(self.project_name, self.exe_path)
        icon.update_menu()

    def _exit(self, icon, item):
        logging.info("tray: exit requested")
        self._on_exit()
        icon.stop()

    # --- public api ---------------------------------------------------

    def set_state_text(self, text: str):
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
        return pystray.Menu(
            pystray.MenuItem(lambda item: f"Status: {self.state_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "Resume" if self.paused else "Pause",
                self._toggle_pause,
            ),
            pystray.MenuItem("Reload config", self._reload),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open config folder", self._open_config_dir),
            pystray.MenuItem("Open logs", self._open_logs),
            pystray.MenuItem(
                "Run at startup",
                self._toggle_autostart,
                checked=lambda item: autostart.is_enabled(self.project_name),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )

    def start(self):
        self._icon = pystray.Icon(
            self.project_name,
            self._icon_image,
            f"SRR — {self.state_text}",
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="srr-tray")
        self._thread.start()
        logging.info("tray icon started")
