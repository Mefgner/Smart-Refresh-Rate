import asyncio
import dataclasses
import datetime
import json
import os
import sys
import winreg
import psutil
import shutil

from pathlib import Path
from pynput import keyboard

import reschanger

Keys = keyboard.Key
last_btn: Keys
TIME_STEP = 1  # seconds
STARTUP_SWITCH = True

PATH_APPDATA_LOCAL = Path(os.getenv("LOCALAPPDATA")).resolve()
PATH_TO_PROGRAM = PATH_APPDATA_LOCAL / "Auto60HZ"
PATH_CURRENT_FILE = Path(sys.argv[0]).resolve()
PATH_BASE_DIR = PATH_CURRENT_FILE.parent


@dataclasses.dataclass
class ScreenSettings:
    width: int
    height: int
    refresh_rate: int


def write_logs(e: Exception | BaseException):
    def write(exception: Exception | BaseException, method: str = 'a'):
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
        exit()


def cur_power_state():
    return psutil.sensors_battery().power_plugged


def cur_monitor_specs() -> dict[str, dict[str, int]]:
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
    except KeyboardInterrupt as k:
        write_logs(k)
        exit()


async def switch_rate(current_state, prss: ScreenSettings, psss: ScreenSettings):
    if current_state:
        await change_screen_settings(prss)
    else:
        await change_screen_settings(psss)


async def hz60loop(time_step, prss: ScreenSettings, psss: ScreenSettings):
    last_state = cur_power_state()
    while True:
        try:
            await asyncio.sleep(time_step)
            current_state = cur_power_state()
            if last_state == current_state:
                continue
            else:
                await switch_rate(current_state, prss, psss)
            last_state = current_state
        except KeyboardInterrupt as k:
            write_logs(k)
            exit()
        except Exception as e:
            write_logs(e)


async def auto60hz(time_step: int, prss: ScreenSettings, psss: ScreenSettings, startup_switch: bool):
    if startup_switch:
        await switch_rate(cur_power_state(), prss, psss)
    await hz60loop(time_step, prss, psss)


async def main():
    print(sys.argv)
    if not Path.exists(PATH_TO_PROGRAM) and PATH_CURRENT_FILE.suffix == ".exe":
        PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
        shutil.copy(PATH_CURRENT_FILE, PATH_TO_PROGRAM / "Auto60HZ.exe")
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "Auto60HZ", 0, winreg.REG_SZ, str(PATH_TO_PROGRAM / "Auto60HZ.exe"))
        winreg.CloseKey(key)

    if not Path.exists(PATH_TO_PROGRAM / "config.json"):
        with open(PATH_TO_PROGRAM / "config.json", "w") as config:
            params = cur_monitor_specs()
            json.dump(params, config, indent=4)

    with open(PATH_TO_PROGRAM / "config.json", "r") as config:
        stream = config.read()
        params = json.JSONDecoder().decode(stream)

        powersave_dict = params["powersave-state"]
        powersave_state = ScreenSettings(**powersave_dict)

        performance_dict = params["performance-state"]
        performance_state = ScreenSettings(**performance_dict)

        fatalities = 0

        while fatalities <= 5:
            try:
                with keyboard.Listener(on_press=on_press, on_release=on_release):
                    await auto60hz(TIME_STEP, performance_state, powersave_state, STARTUP_SWITCH)
            except KeyboardInterrupt as k:
                write_logs(k)
                exit()
            except Exception as e:
                write_logs(e)
                fatalities += 1


if __name__ == '__main__':
    asyncio.run(main())
