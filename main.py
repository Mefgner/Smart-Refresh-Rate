import asyncio
import dataclasses
import json
import datetime
import pathlib
import os

from pynput import keyboard
import psutil
import reschanger

Keys = keyboard.Key
last_btn: Keys
TIME_STEP = 1
STARTUP_SWITCH = True

PATH_TO_PROGRAM = pathlib.Path(os.getenv("LOCALAPPDATA")) / "Auto60HZ"


@dataclasses.dataclass
class ScreenSettings:
    width: int
    height: int
    refresh_rate: int


def write_logs(e: Exception):
    with open(pathlib.Path(os.getenv("LOCALAPPDATA")) / "Auto60HZ" / "log.txt", 'a', encoding='utf-8') as log:
        log.write(f'{datetime.datetime.today()}\n{repr(e)}\n{reschanger.get_resolution()}\n')


def on_press(key):
    global last_btn
    if key != Keys.delete:
        last_btn = key


def on_release(key):
    if key == Keys.delete and last_btn == Keys.shift_r:
        reschanger.set_display_defaults()
        write_logs(Exception("Emergence exit from the program"))
        exit()


def get_current_power_state():
    return psutil.sensors_battery().power_plugged


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


async def hz60loop(time_step, prss: ScreenSettings, psss: ScreenSettings):
    last_state = get_current_power_state()
    while True:
        try:
            await asyncio.sleep(time_step)
            current_state = get_current_power_state()
            if last_state == current_state:
                continue
            else:
                await switch_rate(current_state, prss, psss)
            last_state = current_state
        except Exception as e:
            write_logs(e)


async def auto60hz(time_step: int, prss: ScreenSettings, psss: ScreenSettings, startup_switch: bool):
    if startup_switch:
        await switch_rate(get_current_power_state(), prss, psss)
    await hz60loop(time_step, prss, psss)


async def main():
    with open(PATH_TO_PROGRAM / "config.json") as config:
        stream = config.read()
        params = json.JSONDecoder().decode(stream)

        powersave_dict = params["powersave-state"]
        powersave_state = ScreenSettings(
            width=powersave_dict["width"],
            height=powersave_dict["height"],
            refresh_rate=powersave_dict["refresh-rate"]
        )

        performance_dict = params["performance-state"]
        performance_state = ScreenSettings(
            width=performance_dict["width"],
            height=performance_dict["height"],
            refresh_rate=performance_dict["refresh-rate"]
        )

        fatalities = 0

        while fatalities <= 5:
            try:
                with keyboard.Listener(on_press=on_press, on_release=on_release):
                    await auto60hz(TIME_STEP, performance_state, powersave_state, STARTUP_SWITCH)
            except Exception as e:
                write_logs(e)
                fatalities += 1


if __name__ == '__main__':
    asyncio.run(main())
