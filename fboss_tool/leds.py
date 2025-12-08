#! /usr/bin/env python
"""Test port LEDs using /sys/class/leds."""

import time
import os
from fboss_utils import read_sysfile_value, write_sysfile_value, get_platform

LEDS_CLASS = "/sys/class/leds/"
INPUT_MSG = "Light led mode: [A]Automated or [M]Manual running leds"

LED_ON = 1
LED_OFF = 0

# Define LED counts for different platforms
MONTBLANC_LEDS_COUNT = 64
JANGA_LEDS_COUNT = 46
TAHAN_LEDS_COUNT = 33

TABLE_FLAG = "-----+-----+-----+-----+"

def test_led_udev_path():
    """Check if the LED driver and udev mapping are present."""
    if not os.path.exists(LEDS_CLASS) or not os.listdir(LEDS_CLASS):
        return False, "\033[31mFAIL\033[0m\t, LED driver error."
    return True, "PASS"


def get_port_led_status(leds_path, portid, ledidx):
    """Get the status of a port LED."""
    for color in ["yellow", "blue", "green"]:
        led_status = f"port{portid}_led{ledidx}:{color}:status/brightness"
        devfile = f"{leds_path}{led_status}"
        color_val = read_sysfile_value(devfile)
        if color_val is not None and int(color_val):
            return color
    return "off"


def save_led_default_status(ports):
    """Save the default status of all port LEDs."""
    port_info_dict = {}
    for num in range(ports):
        port = num + 1
        for ledidx in range(1, 3):
            port_info = f"{port}_{ledidx}"
            color = get_port_led_status(LEDS_CLASS, port, ledidx)
            port_info_dict[port_info] = color
    return port_info_dict


def port_led_on(portid, ledidx, color):
    """Turn on a port LED."""
    led_status = f"port{portid}_led{ledidx}:{color}:status/brightness"
    devfile = f"{LEDS_CLASS}{led_status}"
    if write_sysfile_value(devfile, LED_ON):
        return "PASS"
    return "\033[31mFAIL\033[0m\tcontrol led command error"


def port_led_off(portid, ledidx):
    """Turn off a port LED."""
    color = get_port_led_status(LEDS_CLASS, portid, ledidx)
    led_status = f"port{portid}_led{ledidx}:{color}:status/brightness"
    devfile = f"{LEDS_CLASS}{led_status}"
    if write_sysfile_value(devfile, LED_OFF):
        return "PASS"
    return "\033[31mFAIL\033[0m\tcontrol led command error"


def restore_leds_default_status(leds_status):
    """Restore the default status of all port LEDs."""
    for port_info, color in leds_status.items():
        portid, ledidx = map(int, port_info.split("_"))
        if color == "off":
            port_led_off(portid, ledidx)
        else:
            port_led_on(portid, ledidx, color)


def turn_off_ports_led(port_nums):
    """Turn off all port LEDs."""
    status = "PASS"
    for i in range(port_nums):
        portid = i + 1
        for ledidx in range(1, 3):
            status = port_led_off(portid, ledidx)
    if status == "PASS":
        print("\n-----------------------led:turn off all port leds.-----------------------\n")
    return status


def turn_on_ports_left_led(port_nums, color):
    """Turn on the left LED of all ports."""
    status = "PASS"
    for i in range(port_nums):
        portid = i + 1
        status = port_led_on(portid, 1, color)
    return status


def turn_on_ports_right_led(port_nums, color):
    """Turn on the right LED of all ports."""
    status = "PASS"
    for i in range(port_nums):
        portid = i + 1
        status = port_led_on(portid, 2, color)
    return status


def loop_port_leds(portid):
    """Loop through all colors and LEDs on a single port."""
    status = "PASS"
    for ledidx in range(1, 3):
        for color in ["blue", "green", "yellow"]:
            stat = port_led_on(portid, ledidx, color)
            if not stat:
                status = "\033[31mFAIL\033[0m\tcontrol led command error"
            time.sleep(0.2)  # switch color delay 0.2 seconds
            print(f"led:turn on port: \033[1;32m{portid}\033[00m \
                  index: \033[1;34m{ledidx}\033[00m {color}  ",
                  end="\r", flush = True)
    return status


def port_led_status(pnum, portid, status):
    """Generate a string representing the LED status for a group of ports."""
    line_info = ""
    for i in range(pnum):
        _left = status[portid + 6 * i]
        _right = status[portid + 1 + 6 * i]
        left_flag = f'{"x" if _left == "off" else _left}'
        right_flag = f'{"x" if _right == "off" else _right}'
        line_info += f" {left_flag.upper()[0]} {right_flag.upper()[0]} |"
    return line_info


def janga_port_led_status(status):
    """Generate a string representing the LED status for a Janga blade."""
    port_left = f'{"x" if status[0] == "off" else status[0]}'
    port_right = f'{"x" if status[1] == "off" else status[1]}'
    first_line = f"| {port_left.upper()[0]} {port_right.upper()[0]} |"
    port_left = f'{"x" if status[2] == "off" else status[2]}'
    port_right = f'{"x" if status[3] == "off" else status[3]}'
    second_line = f"| {port_left.upper()[0]} {port_right.upper()[0]} |"
    third_line = "|     |     |"
    first_line += port_led_status(15, 6, status)
    second_line += port_led_status(15, 4, status)
    third_line += port_led_status(14, 8, status)
    return first_line, second_line, third_line


def tahan_port_led_status(status):
    """Generate a string representing the LED status for a Tahan blade."""
    first_line = "|"
    second_line = "|"
    third_line = "|     |"
    first_line += port_led_status(11, 2, status)
    second_line += port_led_status(11, 0, status)
    third_line += port_led_status(11, 4, status)
    return first_line, second_line, third_line


def montblanc_port_led_status(status):
    """Generate a string representing the LED status for a Montblanc blade."""
    for n in range(4):
        line_info = ""
        print(("+" + TABLE_FLAG * 2) * 2)
        for i in range(16):
            _left = status[2 * n + 8 * i]
            _right = status[2 * n + 1 + 8 * i]
            left_flag = f'{"x" if _left == "off" else _left}'
            right_flag = f'{"x" if _right == "off" else _right}'
            line_info += f" {left_flag.upper()[0]} {right_flag.upper()[0]} |"
            if i == 7:
                line_info += "|"
        leds_status = "".join(line_info)
        print("|" + leds_status)
    print(("+" + TABLE_FLAG * 2) * 2)


def janga_port_led_status_test(port_count):
    """Test the LED status for a Janga blade."""
    current_color_dict = save_led_default_status(port_count)
    if not current_color_dict:
        return False, "FAIL"
    color_info = list(current_color_dict.values())
    first_line, second_line, third_line = janga_port_led_status(color_info)
    print("+" + TABLE_FLAG * 4)
    print(first_line)
    print("+" + TABLE_FLAG * 4)
    print(second_line)
    print("+" + TABLE_FLAG * 4)
    print(third_line)
    print("+" + TABLE_FLAG * 4)
    return True, "PASS"


def tahan_port_led_status_test(port_count):
    """Test the LED status for a Tahan blade."""
    current_color_dict = save_led_default_status(port_count)
    if not current_color_dict:
        return False, "FAIL"
    color_info = list(current_color_dict.values())
    first_line, second_line, third_line = tahan_port_led_status(color_info)
    print("+" + TABLE_FLAG * 3)
    print(first_line)
    print("+" + TABLE_FLAG * 3)
    print(second_line)
    print("+" + TABLE_FLAG * 3)
    print(third_line)
    print("+" + TABLE_FLAG * 3)
    return True, "PASS"


def montblanc_port_led_status_test(port_count):
    """Test the LED status for a Montblanc blade."""
    current_color_dict = save_led_default_status(port_count)
    if not current_color_dict:
        return False, "FAIL"
    color_info = list(current_color_dict.values())
    montblanc_port_led_status(color_info)
    return True, "PASS"


def port_led_turn_on_off(port_nums, platform="janga"):
    """Turn on and off all port LEDs in a loop."""
    status = "PASS"
    status = turn_off_ports_led(port_nums)
    for num in range(1, port_nums + 1):
        loop_port_leds(num)
    status = turn_off_ports_led(port_nums)
    return status


def ports_led_light_status_test(port_nums, platform="tahan"):
    """Test the LED status for a specific platform."""
    stat, status = test_led_udev_path()
    if not stat:
        return stat, status

    func_name = f"{platform}_port_led_status_test"
    default_color_dict = save_led_default_status(port_nums)
    if not default_color_dict:
        return False, "FAIL"

    print(
        "-------------------------------------------------------------------------\n"
        "                   |    Ports Led Default status    |"
    )
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status

    time.sleep(0.5)  # wait 0.5 seconds check leds status
    status = turn_off_ports_led(port_nums)
    print(
        "-------------------------------------------------------------------------\n"
        "                  |    Turn off all ports Led Test    |"
    )
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status

    time.sleep(0.5)  # wait 0.5 seconds check leds status
    status = turn_on_ports_left_led(port_nums, "green")
    print(
        "-------------------------------------------------------------------------\n"
        "               |    Turn on left ports Led green Test    |"
    )
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status

    time.sleep(0.5)  # wait 0.5 seconds check leds status
    status = turn_off_ports_led(port_nums)
    status = turn_on_ports_right_led(port_nums, "blue")
    print(
        "-------------------------------------------------------------------------\n"
        "               |    Turn on right ports Led blue Test    |"
    )
    stat, status = eval(func_name)(port_nums)
    if not stat:
        return stat, status

    time.sleep(0.5)  # wait 0.5 seconds check leds status
    restore_leds_default_status(default_color_dict)
    return stat, status


def port_led_status_test():
    """port led status test functon"""
    platform = get_platform()
    leds_count = eval(f"{platform.upper()}_LEDS_COUNT")
    print(
        "-------------------------------------------------------------------------\n"
        "                   |     Ports Led Status Test     |\n"
        "-------------------------------------------------------------------------"
    )
    stat, status = ports_led_light_status_test(leds_count, platform)
    return f'{"PASS" if stat else status}'

def port_led_loop_test():
    """port led loop test functon"""
    platform = get_platform()
    leds_count = eval(f"{platform.upper()}_LEDS_COUNT")
    print(
        "-------------------------------------------------------------------------\n"
        "                   |     Ports Led loop Test     |\n"
        "-------------------------------------------------------------------------"
    )
    status = port_led_turn_on_off(leds_count, platform)
    return status

if __name__ == "__main__":
    ports_led_light_status_test(TAHAN_LEDS_COUNT)
