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

DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

ENUM_CURRENT_SETTINGS = -1

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
    DISP_CHANGE_FAILED = (-1)
    DISP_CHANGE_BADMODE = (-2)
    DISP_CHANGE_NOTUPDATED = (-3)
    DISP_CHANGE_BADFLAGS = (-4)
    DISP_CHANGE_BADPARAM = (-5)
    DISP_CHANGE_BADDUALVIEW = (-6)


class DUMMYSTRUCT(ctypes.Structure):
    _fields_ = [
        ("dmOrientation", ctypes.c_short),
        ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short),
        ("dmPaperWidth", ctypes.c_short),
        ("dmScale;", ctypes.c_short),
        ("dmCopies;", ctypes.c_short),
        ("dmDefaultSource;", ctypes.c_short),
        ("dmPrintQuality;", ctypes.c_short)
    ]


class DUMMYSTRUCT2(ctypes.Structure):
    _fields_ = [
        ("dmPosition", ctypes.wintypes.POINTL),
        ("dmDisplayOrientation", ctypes.wintypes.DWORD),
        ("dmDisplayFixedOutput", ctypes.wintypes.DWORD)
    ]


class DUMMYUNION(ctypes.Union):
    _anonymous_ = ["s1", "s2"]
    _fields_ = [
        ("s1", DUMMYSTRUCT),
        ("s2", DUMMYSTRUCT2)
    ]


class DUMMYUNION2(ctypes.Union):
    _fields_ = [
        ("dmDisplayFlags", ctypes.wintypes.DWORD),
        ("dmNup", ctypes.wintypes.DWORD)
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
        # if(WINVER >= 0x0400)
        ("dmICMMethod", ctypes.wintypes.DWORD),
        ("dmICMIntent", ctypes.wintypes.DWORD),
        ("dmMediaType", ctypes.wintypes.DWORD),
        ("dmDitherType", ctypes.wintypes.DWORD),
        ("dmReserved1", ctypes.wintypes.DWORD),
        ("dmReserved2", ctypes.wintypes.DWORD),
        # if (WINVER >= 0x0500) || (_WIN32_WINNT >= 0x0400)
        ("dmPanningWidth", ctypes.wintypes.DWORD),
        ("dmPanningHeight", ctypes.wintypes.DWORD)
        # endif
        # endif /* WINVER >= 0x0400 */
    ]


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("DeviceName", ctypes.wintypes.CHAR * 32),
        ("DeviceString", ctypes.wintypes.CHAR * 128),
        ("StateFlags", ctypes.wintypes.DWORD),
        ("DeviceID", ctypes.wintypes.CHAR * 128),
        ("DeviceKey", ctypes.wintypes.CHAR * 128)
    ]


def get_primary_device():
    """Gets the primary display device; ie screen"""
    dd = DISPLAY_DEVICE()
    dd.cb = ctypes.sizeof(dd)
    index = 0
    while user32.EnumDisplayDevicesA(None, index, ctypes.pointer(dd), 0):
        index = index + 1
        if dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE:
            return dd

    return dd


def get_resolutions():
    """Gets all available resolutions"""
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(dm)
    i_mode_num = 0

    while user32.EnumDisplaySettingsA(None, i_mode_num, ctypes.pointer(dm)) != 0:
        yield dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency
        i_mode_num += 1


def get_resolution():
    """
    Gets screen info tuple special for srr

    :return: A tuple of four integers: width, height, highest_refresh_rate, lowest_refresh_rate
    """
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(dm)
    i_mode_num = 0
    highest_resolution = (0, 0)
    highest_refresh_rate = 0
    lowest_refresh_rate = 14440

    mult = lambda x, y: x * y
    while user32.EnumDisplaySettingsA(None, i_mode_num, ctypes.pointer(dm)) != 0:

        current_resolution = dm.dmPelsWidth, dm.dmPelsHeight
        current_frequency = dm.dmDisplayFrequency

        if mult(*highest_resolution) < mult(*current_resolution):
            highest_resolution = current_resolution

        if highest_refresh_rate < current_frequency:
            highest_refresh_rate = current_frequency

        if lowest_refresh_rate > current_frequency:
            lowest_refresh_rate = current_frequency

        i_mode_num += 1

    # return alias: width, height, highest_refresh_rate, lowest_refresh_rate
    return *highest_resolution, highest_refresh_rate, lowest_refresh_rate


def set_display_defaults():
    """Reset to default settings."""
    user32.ChangeDisplaySettingsA(None, 0)


def set_resolution(width, height, freq) -> int:
    """Set the resolution of the screen
    :param width: width of screen
    :param height: height of screen
    :param freq: frequency of screen
    """
    dd = get_primary_device()
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(dm)

    if not user32.EnumDisplaySettingsA(dd.DeviceName, ENUM_CURRENT_SETTINGS, ctypes.pointer(dm)):
        raise Exception("Failed to get display settings.")

    if (width, height, freq) not in list(get_resolutions()):
        return DISP_RESULTS.DISP_CHANGE_BADPARAM

    dm.dmPelsWidth = width
    dm.dmPelsHeight = height
    dm.dmDisplayFrequency = freq
    dm.dmFields = (DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY)

    return user32.ChangeDisplaySettingsA(ctypes.byref(dm), 0)


if __name__ == '__main__':
    print(get_resolutions())
