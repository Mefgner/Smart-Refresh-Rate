import dataclasses
import json
import logging
import os
import sys
import psutil
import shutil
import ctypes
import asyncio

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
    logging.info("Writing logs")

    logging.error(f"Error occurred: {str(e)}", exc_info=e)

    ctypes.windll.user32.MessageBoxW(
        None, f"The SRR program terminated with the following error:\n{str(e)}", "Error", 0x00000010,
    )


def on_press(key):
    global last_btn
    if key != Keys.backspace:
        last_btn = key


def on_release(key):
    if key == Keys.backspace and last_btn == Keys.shift_r:
        reschanger.set_display_defaults()
        logging.info("Display settings were reset to default and the program was terminated")
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

    logging.info("Getting current monitor specs")
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


async def load_config() -> Tuple[ScreenSettings, ScreenSettings]:
    logging.info(f"Loading config from {PATH_TO_PROGRAM / 'config.json'}")
    with open(PATH_TO_PROGRAM / "config.json", "r") as config:
        stream = config.read()

        params = json.JSONDecoder().decode(stream)

        performance_dict = params["performance-state"]
        performance_state = ScreenSettings(**performance_dict)

        powersave_dict = params["powersave-state"]
        powersave_state = ScreenSettings(**powersave_dict)

        return performance_state, powersave_state


async def change_screen_settings(ss: ScreenSettings):
    logging.info(f"Changing screen settings to {ss}")
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
    """
    last_state = cur_power_state()

    current_config = await load_config()
    prev_config_state = current_config

    counter = 0

    while True:
        await asyncio.sleep(time_step)

        current_state = cur_power_state()

        # I think opening config file every second is not a good idea,
        # so then I made it in 10 time longer to wait.
        if counter == 10:
            logging.info(f"Counter now = {counter}, reloading config")
            current_config = await load_config()
            if prev_config_state != current_config:
                ctypes.windll.user32.MessageBoxW(
                    None, "The SRR config was reloaded!", "Info", 0x00000040
                )
                await switch_rate(current_state, *current_config)

            prev_config_state = current_config
            counter = 0

        if last_state != current_state:
            await switch_rate(current_state, *current_config)

        last_state = current_state
        counter += 1


async def get_processes(app_name: AnyStr) -> List[psutil.Process]:
    # returns all processes with given name except the current process
    processes = psutil.process_iter()
    srr_instances = list(filter(lambda process: process.name() == app_name, processes))
    filtered_instances = list(
        filter(
            lambda process: (process.exe() != str(PATH_CURRENT_FILE) and process.pid != os.getpid()),
            srr_instances
        )
    )

    logging.debug("Current process:" + str(PATH_CURRENT_FILE))
    logging.debug("All instances:")
    for instance in srr_instances.copy():
        logging.debug(f"{instance.name()}: {instance.pid} - {instance.exe()}")

    logging.debug("Filtered instances:")
    for instance in filtered_instances.copy():
        logging.debug(f"{instance.name()}: {instance.pid} - {instance.exe()}")
    return filtered_instances


async def srr():
    # program "installer":
    # adding program to its destination and to startup
    logging.info("Program started")

    if PATH_BASE_DIR != PATH_TO_PROGRAM:

        logging.info(f"{PATH_BASE_DIR} and {PATH_TO_PROGRAM} are not the same")
        if PATH_CURRENT_FILE.suffix == ".exe":
            logging.info(f"{PROJECT_EXECUTABLE} is an exe file")

            # kill all processes except the current one
            for instance in await get_processes(PROJECT_EXECUTABLE):
                instance.kill()

            await asyncio.sleep(2)

            logging.info(f"All {PROJECT_EXECUTABLE} processes were killed except current one")
            logging.info(f"Live processes: {await get_processes(PROJECT_EXECUTABLE)}")

            shutil.rmtree(PATH_TO_PROGRAM)
            logging.info(f"{PATH_TO_PROGRAM} was removed")

            PATH_TO_PROGRAM.mkdir(parents=True, exist_ok=True)
            shutil.copy(PATH_CURRENT_FILE, PATH_TO_PROGRAM / PROJECT_EXECUTABLE)
            logging.info(f"{PROJECT_EXECUTABLE} was copied to {PATH_TO_PROGRAM}")

            # os.system(f'sc create SRR-service binpath="{PATH_TO_PROGRAM / PROJECT_EXECUTABLE}" start=delayed-auto')

            os.system(f"reg add HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run /v "
                      f"{PROJECT_NAME} /t REG_SZ /d {PATH_TO_PROGRAM / PROJECT_EXECUTABLE} /f")
            logging.info(f"{PROJECT_EXECUTABLE} was added to autorun")

            os.startfile(PATH_TO_PROGRAM / PROJECT_EXECUTABLE)
            logging.info(f"{PROJECT_EXECUTABLE} is not running, so it was started")
            logging.info(f"{PATH_CURRENT_FILE} terminating itself")
            os._exit(0)

    # create config file if it doesn't exist
    if not Path.exists(PATH_TO_PROGRAM / "config.json"):
        logging.info("Config file was not found, so it was created")
        with open(PATH_TO_PROGRAM / "config.json", "w") as config:
            params = cur_monitor_specs()
            json.dump(params, config, indent=4)

    # start infinite loop
    with keyboard.Listener(on_press=on_press, on_release=on_release, suppress=False):
        logging.info("Starting infinite loop")
        await switch_rate(cur_power_state(), *(await load_config()))
        await srr_loop(TIME_STEP)


async def main():
    # catching all possible exceptions and exiting with error code -1
    try:
        await srr()
    except Exception as e:
        write_logs(e)
        os._exit(-1)


if __name__ == "__main__":
    if not PATH_TO_PROGRAM.exists():
        PATH_TO_PROGRAM.mkdir()
    logging.basicConfig(level=logging.INFO, filename=PATH_BASE_DIR / "logs.txt", filemode="w")
    asyncio.run(main())
