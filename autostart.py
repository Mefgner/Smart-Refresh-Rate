"""Windows autostart management via HKCU Run registry key."""
import logging
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _open(access):
    assert winreg is not None
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def is_enabled(name: str) -> bool:
    if winreg is None:
        return False
    try:
        with _open(winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, name)
            return True
    except FileNotFoundError:
        return False
    except OSError as e:
        logging.warning(f"autostart.is_enabled failed: {e}")
        return False


def enable(name: str, exe_path: Path) -> bool:
    if winreg is None:
        return False
    quoted = f'"{Path(exe_path).resolve()}"'
    try:
        with _open(winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, quoted)
        logging.info(f"autostart enabled: {name} -> {quoted}")
        return True
    except OSError as e:
        logging.error(f"autostart.enable failed: {e}")
        return False


def disable(name: str) -> bool:
    if winreg is None:
        return False
    try:
        with _open(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
        logging.info(f"autostart disabled: {name}")
        return True
    except FileNotFoundError:
        return True
    except OSError as e:
        logging.error(f"autostart.disable failed: {e}")
        return False
