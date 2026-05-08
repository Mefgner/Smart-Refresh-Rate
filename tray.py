"""System tray icon for SRR. Runs pystray in a separate thread."""

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import pystray

if TYPE_CHECKING:
    from pystray._base import Icon as _Icon
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
            return Image.open(str(icon_path)).convert("RGBA")
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
        self._displays: list = []
        self._selected_display_id: Optional[str] = None
        self._on_display_select: Optional[Callable] = None

        self._icon_image = _load_icon(icon_path)
        self._icon: Optional[_Icon] = None
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

    def set_displays(
        self,
        displays: list,
        selected_id: Optional[str],
        on_select: Callable,
    ):
        self._displays = [{"id": None, "name": "All displays"}] + displays
        self._selected_display_id = selected_id
        self._on_display_select = on_select
        self._rebuild_menu()

    def _make_display_selector(self, display_id: Optional[str]) -> Callable:
        def handler(icon, item):
            self._selected_display_id = display_id
            if self._on_display_select is not None:
                self._on_display_select(display_id)
            try:
                icon.update_menu()
            except Exception:
                pass
        return handler

    def _rebuild_menu(self):
        if self._icon is not None:
            try:
                self._icon.menu = self._build_menu()
                self._icon.update_menu()
            except Exception as e:
                logging.warning(f"tray menu rebuild failed: {e}")

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
        ]
        return pystray.Menu(*items)

    def start(self):
        icon = pystray.Icon(
            self.project_name,
            self._icon_image,
            f"SRR — {self.state_text}",
            menu=self._build_menu(),
        )
        self._icon = icon
        self._thread = threading.Thread(target=icon.run, daemon=True, name="srr-tray")
        self._thread.start()
        logging.info("tray icon started")
