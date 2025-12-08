"""gpio module"""

import os
import re
from typing import Tuple

from fboss_utils import execute_shell_cmd, get_platform
import i2cbus

IOB_PCI_DRIVER = "fbiob_pci"
GPIO_CHIP_NAME = "IOB_GPIO_CHIP_0"

GPIO_SUCCESS = "success"
GPIO_ERR_1 = "No fbiob GPIO device"
GPIO_ERR_2 = "No device link in this path : /run/devmap/ {}"
GPIO_ERR_3 = "Please input 'high' or 'low'"
GPIO_ERR_4 = "GPIO set failed"


def detect_gpio_devmap_device() -> str:
    """Detect gpio udev."""
    stat, _ = get_gpiochipnumber()
    if not stat:
        return GPIO_ERR_1

    gpio_udev = f"/run/devmap/gpiochips/{GPIO_CHIP_NAME}"
    if not os.path.exists(gpio_udev):
        return GPIO_ERR_2.format(GPIO_CHIP_NAME)

    return GPIO_SUCCESS


def get_gpiochipnumber() -> Tuple[bool, str]:
    """Get gpio pin number."""
    cmd = "gpiodetect"
    gpio_dev = f"{IOB_PCI_DRIVER}.gpiochip.0"
    pattern = re.compile(gpio_dev)
    stat, value = execute_shell_cmd(cmd)
    if not stat:
        return stat, GPIO_ERR_1

    for line in value.splitlines():
        result = pattern.findall(line)
        if result:
            gpiochip = line.split("[")[0]
            return stat, gpiochip

    return False, GPIO_ERR_1


def set_gpio_output(gpiochip: str, pinnumber: int, write: str) -> str:
    """Set gpio pin direction."""
    if write.lower() == "high":
        value = 1
    elif write.lower() == "low":
        value = 0
    else:
        return GPIO_ERR_3

    cmd = f"gpioset {gpiochip} {pinnumber}={value}"
    stat, _ = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_4

    return GPIO_SUCCESS


def set_gpio_input(gpiochip: str, pinnum: int) -> str:
    """Set gpiochip pin direction as input."""
    cmd = f"gpioget {gpiochip} {pinnum}"
    stat, _ = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_1

    return GPIO_SUCCESS


def check_gpio_direction(gpiochip: str, pinnum: int) -> str:
    """Check gpiochip pin direction."""
    cmd = f"gpioinfo {gpiochip}"
    stat, value = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_1

    lines = value.splitlines()
    if len(lines) > pinnum + 1:
        return lines[pinnum + 1].split()[4]
    else:
        return "Unknown"


def check_set_gpio_output_success() -> str:
    """Test gpio control function."""
    bus_info = "/run/devmap/i2c-busses/IOB_I2C_BUS_6"
    if not os.path.exists(bus_info):
        return GPIO_ERR_2.format("IOB_I2C_BUS_6")

    i2c_number = i2cbus.get_i2c_bus_id("IOB_I2C_BUS_6")
    cmd = f"i2cget -y -f -a {i2c_number} 0x50"
    stat, _ = execute_shell_cmd(cmd)
    if not stat:
        return GPIO_ERR_4

    return GPIO_SUCCESS


def test_gpio_pin_direction(gpiochip: str, pinnum: int) -> Tuple[str, str]:
    """Test gpio pin setup and verify status."""
    status = "FAIL"
    _direction = ""
    set_gpio_output(gpiochip, pinnum, "high")
    _direction = check_gpio_direction(gpiochip, pinnum)
    if _direction == "output":
        status = "PASS"

    return status, _direction


def test_gpio(platform: str = None) -> str:
    """Test gpio function."""
    stat, gpiochip = get_gpiochipnumber()
    if not stat:
        return GPIO_ERR_1

    ret = detect_gpio_devmap_device()
    if ret != GPIO_SUCCESS:
        return ret

    if platform in ("janga", "tahan"):
        # pin 55 test
        ret = set_gpio_output(gpiochip, 55, "high")
        if ret != GPIO_SUCCESS:
            return ret

        ret = check_set_gpio_output_success()
        if ret != GPIO_SUCCESS:
            return ret

        ret = set_gpio_input(gpiochip, 55)
        if ret != GPIO_SUCCESS:
            return ret

    print(
        "  GPIO CHIP | PIN ID | Default Direction | Direction Test | Status\n"
        "-------------------------------------------------------------------------"
    )
    for i in range(72):
        default_direction = check_gpio_direction(gpiochip, i)
        status, direction = test_gpio_pin_direction(gpiochip, i)
        print(
            f'{"":2}{gpiochip:>5} {i:>5d}{"":5}{default_direction:>10s}'
            + f'{"":14}{direction:>6}{"":8}{status.ljust(1)} \n',
            end="",
        )
        set_gpio_input(gpiochip, i)

    return GPIO_SUCCESS


def gpio_chip_test():
    """gpio test functon"""
    print(
        "-------------------------------------------------------------------------\n"
        "                   |     GPIO Controller Test     |\n"
        "-------------------------------------------------------------------------"
    )
    platform = get_platform()
    stat = test_gpio(platform)
    return f'{"PASS" if stat != "success" else stat}'


if __name__ == "__main__":
    gpio_chip_test()
