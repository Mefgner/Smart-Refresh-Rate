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
import traceback

from pathlib import Path
from pynput import keyboard
from typing import Union, Dict, SupportsInt, AnyStr, Tuple

import reschanger

Keys = keyboard.Key
last_btn: Keys

# constants
TIME_STEP = 1  # seconds
STARTUP_SWITCH = True

PROJECT_NAME = "SRR"
PROJECT_EXECUTABLE = PROJECT_NAME + ".exe"

PATH_APPDATA_LOCAL = Path(os.getenv("LOCALAPPDATA")).resolve()
PATH_TO_PROGRAM = PATH_APPDATA_LOCAL / PROJECT_NAME
PATH_CURRENT_FILE = Path(sys.argv[0]).resolve()
PATH_BASE_DIR = PATH_CURRENT_FILE.parent


@dataclasses.dataclass
class ScreenSettings:
    width: int
    height: int
    refresh_rate: int


def write_logs(e: Union[Exception, BaseException]):
    def write(exception: Union[Exception, BaseException], method: str = "a"):
        with open((PATH_TO_PROGRAM / "log.txt"), method, encoding="utf-8") as log:
            pass
        log.write('\n'.join([
            datetime.datetime.today(),
            repr(exception),
            f'Your, current screen specs (width, height, refresh rate(min/max)): {reschanger.get_resolution()}',
            f'Traceback: {"\n".join(traceback.format_exception(exception))}'
        ]))
        ctypes.windll.user32.MessageBoxW(
            None,
            f"The SRR program terminated with the following error:\n{str(e)}",
            "Error",
            0,
        )

    try:
        write(e, "a")
    except FileNotFoundError:
        write(e, "w")


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
            "refresh_rate": refresh_rate_min,
        },
        "performance-state": {
            "width": width,
            "height": height,
            "refresh_rate": refresh_rate_max,
        },
    }
    return params


def load_config() -> Tuple[ScreenSettings, ScreenSettings]:
    with open(PATH_TO_PROGRAM / "config.json", "r") as config:
        stream = config.read()

        params = json.JSONDecoder().decode(stream)

        performance_dict = params["performance-state"]
        performance_state = ScreenSettings(**performance_dict)

        powersave_dict = params["powersave-state"]
        powersave_state = ScreenSettings(**powersave_dict)

        return performance_state, powersave_state


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


async def srr_loop(time_step: int):
    last_state = cur_power_state()
    prev_config_state = load_config()
    while True:
        await asyncio.sleep(time_step)

        current_state = cur_power_state()
        current_config = load_config()
        if prev_config_state != current_config:
            ctypes.windll.user32.MessageBoxW(
                None, "The SRR config was reloaded!", "Info", 0
            )
            await switch_rate(current_state, *current_config)

        prev_config_state = current_config

        if last_state == current_state:
            continue
        else:
            await switch_rate(current_state, *current_config)

        last_state = current_state


def is_app_running(app_name):
    processes = psutil.process_iter()
    for process in processes:
        if (
                process.name() == app_name
                and process.exe() == PATH_TO_PROGRAM / PROJECT_EXECUTABLE
        ):
            return True


async def srr():
    if not Path.exists(PATH_TO_PROGRAM) and PATH_CURRENT_FILE.suffix == ".exe":
        PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
        shutil.copy(PATH_CURRENT_FILE, PATH_TO_PROGRAM / PROJECT_EXECUTABLE)

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(
            key,
            PROJECT_NAME,
            0,
            winreg.REG_SZ,
            str(PATH_TO_PROGRAM / PROJECT_EXECUTABLE),
        )
        winreg.CloseKey(key)

    if PATH_BASE_DIR != PATH_TO_PROGRAM:
        if not is_app_running(PROJECT_EXECUTABLE):
            os.startfile(PATH_TO_PROGRAM / PROJECT_EXECUTABLE)
        else:
            ctypes.windll.user32.MessageBoxW(
                None, "Another instance of SRR is already running.", "Warning", 0
            )
        os._exit(-1)

    if not Path.exists(PATH_TO_PROGRAM / "config.json"):
        with open(PATH_TO_PROGRAM / "config.json", "w") as config:
            params = cur_monitor_specs()
            json.dump(params, config, indent=4)

    with keyboard.Listener(on_press=on_press, on_release=on_release):
        await switch_rate(cur_power_state(), *load_config())
        await srr_loop(TIME_STEP)


async def main():
    try:
        await srr()
    except Exception as e:
        write_logs(e)
        os._exit(-1)


if __name__ == "__main__":
    asyncio.run(main())
