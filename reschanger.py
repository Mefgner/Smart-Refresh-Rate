import ctypes
import ctypes.wintypes
import enum

user32 = ctypes.windll.user32

CCHFORMNAME = 32
CCHDEVICENAME = 32

DM_BITSPERPEL = 0x00040000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFLAGS = 0x00200000
DM_DISPLAYFREQUENCY = 0x00400000
DM_POSITION = 0x00000020

DISPLAY_DEVICE_ACTIVE = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

ENUM_CURRENT_SETTINGS = -1
ENUM_REGISTRY_SETTINGS = -2

CDS_UPDATEREGISTRY = 1
CDS_TEST = 2
CDS_FULLSCREEN = 4
CDS_GLOBAL = 8
CDS_SET_PRIMARY = 16
CDS_RESET = 0x40000000
CDS_SETRECT = 0x20000000
CDS_NORESET = 0x10000000


class DISP_RESULTS(enum.IntEnum):
    DISP_CHANGE_SUCCESSFUL = 0
    DISP_CHANGE_RESTART = 1
    DISP_CHANGE_FAILED = -1
    DISP_CHANGE_BADMODE = -2
    DISP_CHANGE_NOTUPDATED = -3
    DISP_CHANGE_BADFLAGS = -4
    DISP_CHANGE_BADPARAM = -5
    DISP_CHANGE_BADDUALVIEW = -6


class DUMMYSTRUCT(ctypes.Structure):
    _fields_ = [
        ("dmOrientation", ctypes.c_short),
        ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short),
        ("dmPaperWidth", ctypes.c_short),
        ("dmScale;", ctypes.c_short),
        ("dmCopies;", ctypes.c_short),
        ("dmDefaultSource;", ctypes.c_short),
        ("dmPrintQuality;", ctypes.c_short),
    ]


class DUMMYSTRUCT2(ctypes.Structure):
    _fields_ = [
        ("dmPosition", ctypes.wintypes.POINTL),
        ("dmDisplayOrientation", ctypes.wintypes.DWORD),
        ("dmDisplayFixedOutput", ctypes.wintypes.DWORD),
    ]


class DUMMYUNION(ctypes.Union):
    _anonymous_ = ["s1", "s2"]
    _fields_ = [("s1", DUMMYSTRUCT), ("s2", DUMMYSTRUCT2)]


class DUMMYUNION2(ctypes.Union):
    _fields_ = [
        ("dmDisplayFlags", ctypes.wintypes.DWORD),
        ("dmNup", ctypes.wintypes.DWORD),
    ]


class DEVMODE(ctypes.Structure):
    _anonymous_ = ["dummyunion", "dummyunion2"]
    _fields_ = [
        ("dmDeviceName", ctypes.wintypes.BYTE * CCHDEVICENAME),
        ("dmSpecVersion", ctypes.wintypes.WORD),
        ("dmDriverVersion", ctypes.wintypes.WORD),
        ("dmSize", ctypes.wintypes.WORD),
        ("dmDriverExtra", ctypes.wintypes.WORD),
        ("dmFields", ctypes.wintypes.DWORD),
        ("dummyunion", DUMMYUNION),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.wintypes.BYTE * CCHFORMNAME),
        ("dmLogPixels", ctypes.wintypes.WORD),
        ("dmBitsPerPel", ctypes.wintypes.DWORD),
        ("dmPelsWidth", ctypes.wintypes.DWORD),
        ("dmPelsHeight", ctypes.wintypes.DWORD),
        ("dummyunion2", DUMMYUNION2),
        ("dmDisplayFrequency", ctypes.wintypes.DWORD),
        ("dmICMMethod", ctypes.wintypes.DWORD),
        ("dmICMIntent", ctypes.wintypes.DWORD),
        ("dmMediaType", ctypes.wintypes.DWORD),
        ("dmDitherType", ctypes.wintypes.DWORD),
        ("dmReserved1", ctypes.wintypes.DWORD),
        ("dmReserved2", ctypes.wintypes.DWORD),
        ("dmPanningWidth", ctypes.wintypes.DWORD),
        ("dmPanningHeight", ctypes.wintypes.DWORD),
    ]


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("DeviceName", ctypes.wintypes.CHAR * 32),
        ("DeviceString", ctypes.wintypes.CHAR * 128),
        ("StateFlags", ctypes.wintypes.DWORD),
        ("DeviceID", ctypes.wintypes.CHAR * 128),
        ("DeviceKey", ctypes.wintypes.CHAR * 128),
    ]


def get_active_displays() -> list:
    """
    Returns list of dicts for every active display:
        adapter_name  : bytes  e.g. b'\\\\.\\DISPLAY1'
        monitor_id    : str    stable hardware ID e.g. 'MONITOR\\LGD0521\\...'
        monitor_string: str    human-readable name
    """
    result = []
    dd_adapter = DISPLAY_DEVICE()
    dd_adapter.cb = ctypes.sizeof(dd_adapter)
    adapter_idx = 0

    while user32.EnumDisplayDevicesA(None, adapter_idx, ctypes.pointer(dd_adapter), 0):
        adapter_idx += 1
        if not (dd_adapter.StateFlags & DISPLAY_DEVICE_ACTIVE):
            continue

        adapter_name = dd_adapter.DeviceName  # bytes

        dd_monitor = DISPLAY_DEVICE()
        dd_monitor.cb = ctypes.sizeof(dd_monitor)
        monitor_idx = 0

        while user32.EnumDisplayDevicesA(
            adapter_name, monitor_idx, ctypes.pointer(dd_monitor), 0
        ):
            monitor_idx += 1
            if dd_monitor.StateFlags & DISPLAY_DEVICE_ACTIVE:
                monitor_id = (
                    dd_monitor.DeviceID.decode("ascii", errors="replace")
                    .strip("\x00")
                    .strip()
                )
                monitor_string = (
                    dd_monitor.DeviceString.decode("ascii", errors="replace")
                    .strip("\x00")
                    .strip()
                )
                result.append(
                    {
                        "adapter_name": adapter_name,
                        "monitor_id": monitor_id,
                        "monitor_string": monitor_string,
                    }
                )
                break  # one active monitor per adapter is the common case

    return result


def get_display_settings(adapter_name, mode: int) -> tuple:
    """Return (width, height, freq) for adapter_name at the given mode constant."""
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(dm)
    if not user32.EnumDisplaySettingsA(
        adapter_name, ctypes.c_uint32(mode).value, ctypes.pointer(dm)
    ):
        raise RuntimeError(
            f"EnumDisplaySettingsA failed for {adapter_name!r} mode {mode}"
        )
    return dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency


def enum_display_modes(adapter_name) -> tuple:
    """Return all supported (width, height, freq) modes for the given adapter."""
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(dm)
    modes = []
    i = 0
    while user32.EnumDisplaySettingsA(adapter_name, i, ctypes.pointer(dm)) != 0:
        modes.append((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
        i += 1
    return tuple(modes)


def best_powersave_freq(adapter_name, width: int, height: int) -> int:
    """
    Highest refresh rate <= 60 Hz available at (width, height) on adapter_name.
    Falls back to the lowest available freq if nothing <= 60 exists.
    """
    modes = enum_display_modes(adapter_name)
    freqs = sorted(
        {freq for w, h, freq in modes if w == width and h == height}, reverse=True
    )
    candidates = [f for f in freqs if f <= 60]
    if candidates:
        return candidates[0]
    return freqs[-1] if freqs else 60


def set_display_defaults(adapter_names: list | None = None) -> None:
    """Reset display(s) to their default settings."""
    if not adapter_names:
        user32.ChangeDisplaySettingsA(None, 0)
        return
    for name in adapter_names:
        user32.ChangeDisplaySettingsExA(name, None, None, 0, None)


def set_resolution(width: int, height: int, freq: int, adapter_name) -> int:
    """
    Set the resolution of a specific display.
    adapter_name: bytes, e.g. b'\\\\.\\DISPLAY1'
    """
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(dm)

    if not user32.EnumDisplaySettingsA(
        adapter_name, ENUM_CURRENT_SETTINGS, ctypes.pointer(dm)
    ):
        raise RuntimeError(
            f"Failed to get current display settings for {adapter_name!r}"
        )

    if (width, height, freq) not in enum_display_modes(adapter_name):
        return DISP_RESULTS.DISP_CHANGE_BADPARAM

    dm.dmPelsWidth = width
    dm.dmPelsHeight = height
    dm.dmDisplayFrequency = freq
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY

    return user32.ChangeDisplaySettingsExA(
        adapter_name, ctypes.byref(dm), None, 0, None
    )


if __name__ == "__main__":
    for d in get_active_displays():
        print(d)
        print(
            "  registry:",
            get_display_settings(d["adapter_name"], ENUM_REGISTRY_SETTINGS),
        )
        print(
            "  powersave freq:",
            best_powersave_freq(
                d["adapter_name"],
                *get_display_settings(d["adapter_name"], ENUM_REGISTRY_SETTINGS)[:2],
            ),
        )
