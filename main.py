import json
import time
import psutil
from pynput import keyboard
from ResChanger import reschanger
# import argparse

Keys = keyboard.Key
last_btn: Keys


def on_press(key):
    global last_btn
    if key != Keys.delete:
        last_btn = key


def on_release(key):
    if key == Keys.delete and last_btn == Keys.shift_r:
        reschanger.set_display_defaults()
        exit()
        

def get_current_state():
    return psutil.sensors_battery().power_plugged


def switch_state(w, h, rate):
    reschanger.set_resolution(w, h, rate)


def switch_rate(current_state, w, h, perf_rate, eff_rate):
    if current_state:
        switch_state(w, h, perf_rate)
    else:
        switch_state(w, h, eff_rate)


def hz60loop(time_step, w, h, perf_rate, eff_rate):
    last_state = get_current_state()
    while True:
        time.sleep(time_step)
        current_state = get_current_state()
        if last_state == current_state:
            continue
        else:
            switch_rate(current_state, w, h, perf_rate, eff_rate)
        last_state = current_state
        

def auto60hz(time_step=1, w=1920, h=1080, perf_rate=144, eff_rate=60, startup_switch=True):
    if startup_switch:
        switch_rate(get_current_state(), w, h, perf_rate, eff_rate)
    hz60loop(time_step, w, h, perf_rate, eff_rate)
    
        
if __name__ == '__main__':
    # arg = argparse.ArgumentParser(
    #     prog="Auto60HZ",
    #     description="Auto switches refresh rate if power state switched",
    # )
    
    # arg.add_argument("-wx", "--width", type=int, help="Resolution width")
    # arg.add_argument("-hx", "--height", type=int, help="Resolution height")
    # arg.add_argument("-pr", "--performance-rate", type=int, help="Resolution refresh rate(charger plugged-in)")
    # arg.add_argument("-er", "--efficiency-rate", type=int, help="Resolution refresh rate(charger plugged-out)")
    
    # arg.add_argument("--do-startup-switch", action="store_true", help="Program comparing current state of charger with current refresh rate and switches it.")
    # params = dict(arg.parse_args())
    
    with open('config.json') as f:
        stream = f.read()
        params = json.JSONDecoder().decode(stream)
    
        with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
            auto60hz(w=params['width'], h=params['height'], 
                    perf_rate=params['performance_refresh_rate'], 
                    eff_rate=params['efficiency_refresh_rate'])
