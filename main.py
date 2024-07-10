import dataclasses
import datetime
import json
import os
import sys
import winreg
import psutil
import shutil
import ctypes
import asyncio
import traceback

from pathlib import Path
from pynput import keyboard
from typing import Union, Dict, SupportsInt, AnyStr, Tuple, List

from reschanger import DISP_RESULTS
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
PATH_REG_AUTORUN = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"


@dataclasses.dataclass
class ScreenSettings:
    width: int
    height: int
    refresh_rate: int

    def __iter__(self):
        return iter([self.width, self.height, self.refresh_rate])


def write_logs(e: Union[Exception, BaseException]):
    with open((PATH_BASE_DIR / "log.txt"), 'a', encoding="utf-8") as log:
        max_width = 1

        # error log template
        ls = [
            '-',
            str(datetime.datetime.today().isoformat(" ", timespec="seconds")),
            "Your current screen specs(width, height, refresh rate(max/min)): {}".format(
                reschanger.get_resolution()
            ),
            '-',
            *traceback.format_exc().split('\n')[:-1],
            '-',
            '',
            '',
            '',
        ]

        # calculating max width
        for x in ls:
            cur_len = len(x)
            if cur_len > max_width:
                max_width = cur_len

        # applying max width to horizontal rule
        for index, y in enumerate(ls):
            if y == '-':
                ls[index] = "-" * max_width
        log.write("\n".join(ls))
    ctypes.windll.user32.MessageBoxW(
        None, f"The SRR program terminated with the following error:\n{str(e)}", "Error", 0,
    )


def on_press(key):
    global last_btn
    if key != Keys.backspace:
        last_btn = key


def on_release(key):
    if key == Keys.backspace and last_btn == Keys.shift_r:
        reschanger.set_display_defaults()
        write_logs(Exception("Program termination caused by user"))
        os._exit(-3)


def cur_power_state():
    return psutil.sensors_battery().power_plugged


def cur_monitor_specs() -> Dict[AnyStr, Dict[AnyStr, SupportsInt]]:
    """
    Get current monitor specs and return it as dictionary with two states: 'powersave-state' and 'performance-state'

    :return: A dictionary with two states: 'powersave-state' and 'performance-state'
             'powersave-state' and 'performance-state' are dictionary with keys 'width', 'height', and 'refresh_rate'
             'width' and 'height' are screen resolution
             'refresh_rate' is screen refresh rate
    """
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
    res = reschanger.set_resolution(*ss)

    if res == DISP_RESULTS.DISP_CHANGE_BADPARAM:

        ctypes.windll.user32.MessageBoxW(
            None, "Your parameters wrote in config.json were incorrect.\nCheck log file for available modes.",
            "Resolution Changing Info", 0x00000010
        )
        write_logs(Exception("\n".join(
            [
                "Your parameters wrote in config.json were incorrect.",
                *reschanger.get_resolutions()
            ]
        )))
        await asyncio.sleep(10)

    elif not res == DISP_RESULTS.DISP_CHANGE_SUCCESSFUL:

        await asyncio.sleep(10)
        write_logs(Exception("\n".join(
            [
                "Failed to change screen settings.",
                "This could be due to external interference(like graphic drives)",
                "or the laptop being in a lockscreen or sleep state,",
                "as Windows may prevent changes in those states."
            ]
        )))
        reschanger.set_resolution(*ss)


async def switch_rate(current_state: bool, prss: ScreenSettings, psss: ScreenSettings):
    if current_state:
        await change_screen_settings(prss)
    else:
        await change_screen_settings(psss)


async def srr_loop(time_step: int) -> None:
    """
    This function is an infinite loop that runs every `time_step` seconds and
    checks the current power state and the current configuration. If the power
    state or the configuration has changed, it will switch the screen settings
    accordingly.

    Args:
        time_step (int): The time in seconds between each iteration of the loop.

    Returns:
        None
    """
    last_state = cur_power_state()
    prev_config_state = load_config()
    current_config = load_config()
    counter = 0

    while True:
        await asyncio.sleep(time_step)

        current_state = cur_power_state()

        # I think opening config file every second is not a good idea,
        # so then I made it in 5 time longer to wait.
        if counter == 5:
            current_config = load_config()
            if prev_config_state != current_config:
                ctypes.windll.user32.MessageBoxW(
                    None, "The SRR config was reloaded!", "Info", 0
                )
                await switch_rate(current_state, *current_config)

            prev_config_state = current_config
            counter = 0

        if last_state == current_state:
            continue
        else:
            await switch_rate(current_state, *current_config)

        last_state = current_state
        counter += 1


def get_processes(app_name: AnyStr) -> List[psutil.Process]:
    # returns all processes with given name except the process itself
    processes = psutil.process_iter()
    srr_instances = list(filter(lambda process: process.name() == app_name, processes))
    filtered_instances = list(
        filter(lambda process: process.exe() != PATH_BASE_DIR, srr_instances)
    )

    print("All instances:")
    for instance in srr_instances.copy():
        print(f"{instance.name()}: {instance.pid} - {instance.exe()}")

    print("Filtered instances:")
    for instance in filtered_instances.copy():
        print(f"{instance.name()}: {instance.pid} - {instance.exe()}")
    return filtered_instances


async def srr():
    # program "installer":
    # adding program to its destination and to startup

    if PATH_BASE_DIR != PATH_TO_PROGRAM:

        print(f"{PATH_BASE_DIR} and {PATH_TO_PROGRAM} are not the same")
        if PATH_CURRENT_FILE.suffix == ".exe":
            print(f"{PROJECT_EXECUTABLE} is an exe file")

            # kill all processes except the current one
            for instance in get_processes(PROJECT_EXECUTABLE):
                instance.kill()

            print(f"All {PROJECT_EXECUTABLE} processes were killed except current one")
            print(f"Live processes: {get_processes(PROJECT_EXECUTABLE)}")

            shutil.rmtree(PATH_TO_PROGRAM)
            print(f"{PATH_TO_PROGRAM} was removed")

            PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
            shutil.copy(PATH_CURRENT_FILE, PATH_TO_PROGRAM / PROJECT_EXECUTABLE)
            print(f"{PROJECT_EXECUTABLE} was copied to {PATH_TO_PROGRAM}")

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PATH_REG_AUTORUN, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, PROJECT_NAME, 0, winreg.REG_SZ, str(PATH_TO_PROGRAM / PROJECT_EXECUTABLE))
            winreg.CloseKey(key)
            print(f"{PROJECT_EXECUTABLE} was added to autorun")

        # check if the program is already running
        # if it is, exit the program and show a warning message
        # if it is not, start the program
        if not get_processes(PROJECT_EXECUTABLE):
            os.startfile(PATH_TO_PROGRAM / PROJECT_EXECUTABLE)
            print(f"{PROJECT_EXECUTABLE} is not running, so it was started")
            os._exit(0)
        else:
            ctypes.windll.user32.MessageBoxW(
                None, "Another instance of SRR is already running.", "Warning", 0
            )
            print(f"{PROJECT_EXECUTABLE} is already running")
            os._exit(-2)

    # create config file if it doesn't exist
    if not Path.exists(PATH_TO_PROGRAM / "config.json"):
        with open(PATH_TO_PROGRAM / "config.json", "w") as config:
            params = cur_monitor_specs()
            json.dump(params, config, indent=4)

    # start infinite loop
    with keyboard.Listener(on_press=on_press, on_release=on_release, suppress=False):
        # listener.join()
        await switch_rate(cur_power_state(), *load_config())
        await srr_loop(TIME_STEP)


async def main():
    # catching all possible exceptions and exiting with error code -1
    try:
        await srr()
    except Exception as e:
        write_logs(e)
        os._exit(-1)


if __name__ == "__main__":
    asyncio.run(main())
