import subprocess
import pathlib
import os
import sys
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
                print('\t' * indent, COLOR_MAP.get("yellow", COLOR_YELLOW) + str(key) + COLOR_RESET, ":", value)
            else:
                print('\t' * indent, str(key) + ':', value)


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

def get_platform():
    """
    Determines the platform based on the system product name.

    Returns:
        The platform name (e.g., "montblanc", "janga", "tahan") or "unknown" if not recognized.
    """
    cmd = "dmidecode -s system-product-name"
    _, val = execute_shell_cmd(cmd)
    if not _:
        return None
    
    if val == "MINIPACK3":
        return "montblanc"
    elif val == "JANGA":
        return "janga"
    elif val == "TAHAN":
        return "tahan"
    else:
        return "unknown"
