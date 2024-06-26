#!/usr/bin/env python3
"""Module providing common functions for interacting with system devices."""

import subprocess
import pathlib
import os
import sys, time
from typing import Tuple, Optional

# Constants for clarity
MSG_FILE_NOT_FOUND = "\u001b[31mFAIL\u001b[0m\t{}File not exist."
COLOR_RED = '\033[1;31m'
COLOR_GREEN = '\033[1;32m'
COLOR_YELLOW = '\033[1;33m'
COLOR_BLUE = '\033[1;34m'
COLOR_PURPLE = '\033[1;35m'
COLOR_CYAN = '\033[1;36m'
COLOR_RESET = '\033[00m'

# Define a type for color codes
ColorCode = str

# Map of color codes to their names
COLOR_MAP = {
    "red": COLOR_RED,
    "green": COLOR_GREEN,
    "yellow": COLOR_YELLOW,
    "blue": COLOR_BLUE,
    "purple": COLOR_PURPLE,
    "cyan": COLOR_CYAN,
}

# Chip and GPIO pin mappings
CHIP_MAP = {
    "iob": "N25Q128..3E",
    "dom1": "N25Q128..3E",
    "dom2": "N25Q128..3E",
    "mp3_mcbcpld": "W25X20",
    "mp3_smbcpld": "W25X20",
    "mp3_scmcpld": "W25X20",
    "pwrcpld": "W25X20",
    "smbcpld1": "W25X20",
    "smbcpld2": "W25X20",
}

GPIOPIN_MAP = {
    "dom1": "9",
    "dom2": "10",
    "mp3_mcbcpld": "3",
    "mp3_smbcpld": "7",
    "mp3_scmcpld": "1",
    "pwrcpld": "3",
    "smbcpld1": "1",
    "smbcpld2": "7",
}


def print_dict(dictionary: dict, previous: str = '', indent: int = 0, colors: bool = False) -> None:
    """
    Prints a dictionary in a visually appealing format.

    Args:
        dictionary: The dictionary to print.
        previous: The key of the parent dictionary (used for recursion).
        indent: The indentation level for the current level.
        colors: Whether to use color codes in the output.
    """
    for key, value in dictionary.items():
        if isinstance(value, dict):
            if colors:
                print('\t' * indent, COLOR_MAP.get("cyan", COLOR_CYAN) + str(key) + COLOR_RESET)
            else:
                print('\t' * indent, str(key) + ':')
            print_dict(value, previous=key, indent=indent + 1, colors=colors)
        else:
            if colors:
                print('\t' * (indent - 1), COLOR_MAP.get("yellow", COLOR_YELLOW) + str(previous) + COLOR_RESET, value)
            else:
                print('\t' * (indent - 1), str(previous) + ':', value)


def execute_shell_cmd(cmd: str) -> Tuple[bool, str]:
    """Executes a shell command and returns the status and output."""
    try:
        result = subprocess.run(
            cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
        if result.returncode == 0:
            return True, result.stdout.decode().strip()
        else:
            return False, (
                result.stdout.decode().strip()
                + f"\n- Error Code: {result.returncode}\n- Error:\n"
                + result.stderr.decode().strip()
            )
    except FileNotFoundError as fne:
        return False, fne.strerror + f": {cmd}"


def get_pci_bdf_info(vendor_id: str) -> Optional[str]:
    """Retrieves the PCI Bus, Device, and Function (BDF) information for a device with the given vendor ID."""
    status, stdout = execute_shell_cmd("lspci -n")
    if not status:
        return None
    for line in stdout.splitlines():
        if vendor_id in line:
            return line.split()[0]
    return None


def read_sysfile_value(devfile: str) -> Optional[str]:
    """Reads the value from a sysfs file."""
    if pathlib.Path(devfile).exists():
        try:
            with open(devfile, "r", encoding="utf-8") as devfd:
                return devfd.read().strip()
        except IOError:
            print(f"FAIL\tcannot open {devfile}")
        except Exception as err:
            print(f"FAIL\tUnexpected {err=}, {type(err)=}")
            raise
    else:
        print(MSG_FILE_NOT_FOUND.format(devfile))
    return None


def write_sysfile_value(devfile: str, val: str) -> Tuple[bool, str]:
    """Writes a value to a sysfs file."""
    if pathlib.Path(devfile).exists():
        try:
            with open(devfile, "w", encoding="utf-8") as devfd:
                devfd.write(str(val))
            return True, "PASS"
        except IOError:
            return False, f"FAIL\tcannot open {devfile}"
        except Exception as err:
            print(f"FAIL\tUnexpected {err=}, {type(err)=}")
            raise
    else:
        return False, MSG_FILE_NOT_FOUND.format(devfile)


def select_dom1() -> None:
    """Selects DOM1 by setting the corresponding GPIO pin."""
    gpiocmd = "gpioset gpiochip0 9=1"
    os.system(gpiocmd)

def progress_bar(total, prefix='', suffix='', decimals=1, length=100, fill='█', print_end="\r"):
    """
    Displays a progress bar with customizable options.

    Args:
        total: Total iterations or units to process.
        prefix: Text to display before the progress bar.
        suffix: Text to display after the progress bar.
        decimals: Number of decimal places for the percentage.
        length: Length of the progress bar in characters.
        fill: Character used to fill the progress bar.
        print_end: Character to print at the end of the progress bar (e.g., '\r' for carriage return).
    """
    
    start_time = time.perf_counter()
    for i in range(total + 1):
        percent = ("{0:." + str(decimals) + "f}").format(100 * (i / float(total)))
        filled_length = int(length * i // total)
        bar = fill * filled_length + '-' * (length - filled_length)
        elapsed_time = time.perf_counter() - start_time
        
        print("\n", f"{prefix}|{bar}| {percent}% {suffix} {elapsed_time:.2f}s", end=print_end)
        time.sleep(0.05)

def firmware_upgrade() -> None:
    """Prompts the user for component and firmware file, then performs the upgrade."""
    devices_list = list(CHIP_MAP.keys())
    print(f"Components list: {devices_list}")
    devname = None
    for i in range(3):
        devname = input("Component Name: ")
        if devname in devices_list:
            break
        else:
            print(
                f"Invalid Component, try again.\nComponents list: {devices_list}"
            )
    else:
        print("\nError: Input component over 3 times!\n")
        return

    chipname = CHIP_MAP.get(devname)
    gpionum = GPIOPIN_MAP.get(devname)
    fwimg = input("Firmware Upgrade file path: ")
    if not fwimg or not pathlib.Path(fwimg).exists():
        print("\nError: Firmware file not exist!\n")
        return

    # show image md5 or check image file md5
    status, stdout = execute_shell_cmd(f"md5sum {fwimg}")
    if not status:
        print("Not support md5sum utilty.")
    for line in stdout.splitlines():
        img_md5 = line.split()[0]

    md5_file = f"{fwimg}.md5"
    if pathlib.Path(md5_file).exists():
        read_md5 = read_sysfile_value(md5_file).split()[0]
        if read_md5 != img_md5:
            input("Image md5sum incorrect! Continue upgrade?[Yes/No]")
    
    print("\nFirmware Image MD5:", img_md5, "\n")
    # switch mux to select flash device and upgrade
    select_gpiocmd = f"gpioset gpiochip0 {gpionum}=1" if gpionum else ""
    release_gpiocmd = f"gpioget gpiochip0 {gpionum}" if gpionum else ""
    flash_devmap = f"/run/devmap/flashes/{devname.upper()}_FLASH"
    upgrade_cmd = f"flashrom -p linux_spi:dev={os.readlink(flash_devmap)} -w {fwimg} -c {chipname}"
    print(upgrade_cmd, "\n\nStarting firmware upgrade...\n")
    progress_bar(1, prefix='Progress:', suffix='Complete', length=50)

    if select_gpiocmd:
        os.system(select_gpiocmd)
    os.system(upgrade_cmd)
    if release_gpiocmd:
        os.system(release_gpiocmd)
