import asyncio
import dataclasses
import datetime
import json
import os
import sys
import winreg
import psutil
import shutil
import ctypes

from pathlib import Path
from pynput import keyboard
from typing import Union, Dict, SupportsInt, AnyStr, Tuple

import reschanger

Keys = keyboard.Key
last_btn: Keys
TIME_STEP = 1  # seconds
STARTUP_SWITCH = True

PATH_APPDATA_LOCAL = Path(os.getenv("LOCALAPPDATA")).resolve()
PATH_TO_PROGRAM = PATH_APPDATA_LOCAL / "SRR"
PATH_CURRENT_FILE = Path(sys.argv[0]).resolve()
PATH_BASE_DIR = PATH_CURRENT_FILE.parent


@dataclasses.dataclass
class ScreenSettings:
    width: int
    height: int
    refresh_rate: int


def write_logs(e: Union[Exception, BaseException]):
    def write(exception: Union[Exception, BaseException], method: str = 'a'):
        with open((PATH_TO_PROGRAM / "log.txt"), method, encoding='utf-8') as log:
            log.write(f'{datetime.datetime.today()}\n{repr(exception)}\n{reschanger.get_resolution()}\n')

    try:
        write(e, 'a')
    except FileNotFoundError:
        write(e, 'w')


def on_press(key):
    global last_btn
    if key != Keys.backspace:
        last_btn = key


def on_release(key):
    if key == Keys.backspace and last_btn == Keys.shift_r:
        reschanger.set_display_defaults()
        write_logs(Exception("Program termination caused by user"))
        os._exit(-1)


def cur_power_state():
    return psutil.sensors_battery().power_plugged


def cur_monitor_specs() -> Dict[AnyStr, Dict[AnyStr, SupportsInt]]:
    width, height, refresh_rate_max, refresh_rate_min = reschanger.get_resolution()
    params = {
        "powersave-state": {
            "width": width,
            "height": height,
            "refresh_rate": refresh_rate_min
        },
        "performance-state": {
            "width": width,
            "height": height,
            "refresh_rate": refresh_rate_max
        }
    }
    return params


async def change_screen_settings(ss: ScreenSettings):
    try:
        reschanger.set_resolution(ss.width, ss.height, ss.refresh_rate)
    except Exception as e:
        write_logs(e)
        await asyncio.sleep(5)
        reschanger.set_resolution(ss.width, ss.height, ss.refresh_rate)


async def switch_rate(current_state, prss: ScreenSettings, psss: ScreenSettings):
    if current_state:
        await change_screen_settings(prss)
    else:
        await change_screen_settings(psss)


async def srr_loop(time_step, prss: ScreenSettings, psss: ScreenSettings):
    last_state = cur_power_state()
    while True:
        await asyncio.sleep(time_step)
        current_state = cur_power_state()
        if last_state == current_state:
            continue
        else:
            await switch_rate(current_state, prss, psss)
        last_state = current_state


def is_app_running(app_name):
    processes = psutil.process_iter()
    for process in processes:
        if process.name() == app_name:
            return True


def load_config() -> Tuple[ScreenSettings, ScreenSettings]:
    with open(PATH_TO_PROGRAM / "config.json", "r") as config:
        stream = config.read()

        params = json.JSONDecoder().decode(stream)

        powersave_dict = params["powersave-state"]
        powersave_state = ScreenSettings(**powersave_dict)

        performance_dict = params["performance-state"]
        performance_state = ScreenSettings(**performance_dict)

        return powersave_state, performance_state


async def main():
    # print(sys.argv)  # debug info
    if not Path.exists(PATH_TO_PROGRAM) and PATH_CURRENT_FILE.suffix == ".exe":
        PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
        shutil.copy(PATH_CURRENT_FILE, PATH_TO_PROGRAM / "SRR.exe")

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "SRR", 0, winreg.REG_SZ, str(PATH_TO_PROGRAM / "SRR.exe"))
        winreg.CloseKey(key)

    if PATH_BASE_DIR != PATH_TO_PROGRAM:
        if not is_app_running("SRR.exe"):
            os.startfile(PATH_TO_PROGRAM / "SRR.exe")
        else:
            ctypes.windll.user32.MessageBoxW(None, "Another instance of SRR is already running.",
                                             "Warning", 0)
        os._exit(-1)

    if not Path.exists(PATH_TO_PROGRAM / "config.json"):
        with open(PATH_TO_PROGRAM / "config.json", "w") as config:
            params = cur_monitor_specs()
            json.dump(params, config, indent=4)

    powersave_state, performance_state = load_config()

    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release):
            await switch_rate(cur_power_state(), performance_state, powersave_state)
            await srr_loop(TIME_STEP, performance_state, powersave_state)
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(None, f"The SRR program terminated with the following error:\n{repr(e)}",
                                         "Error", 0)
        write_logs(e)


if __name__ == '__main__':
    asyncio.run(main())
