#!/usr/bin/env python3
"""Module providing common function."""

# common code
import subprocess
import pathlib
import os

MSG = "\u001b[31mFAIL\u001b[0m\t{}File not exist."

term_colors = [
    '\033[1;31m', #red,
    '\033[1;32m', #green,
    '\033[1;33m', #yellow,
    '\033[1;34m', #blue,
    '\033[1;35m', #purple,
    '\033[1;36m', #cian,
]
last_color = 0

def print_dict(dictionary, previous='', indent=0, colors=False):

    """
    Description:
        Function that prints out a dictionary beautifully.

    Args:
        dictionary (dict): Simple or composite Python dictionary to be printed on screen
        previous (str, optional): Support variable used by the function when working in a recursive way.
                                  To avoid performance problems, it is recommended to leave the variable
                                  at its default value.. Defaults to ''.
        indent (int, optional): Total tabs used by the function to print a dictionary on the screen.
                                Defaults to 0.
    
    Return:
        None
    """
    global last_color
    if isinstance(dictionary,dict):
        for key in dictionary.keys():
            if isinstance(dictionary[key],dict):
                if colors:
                    print('\t'*indent, term_colors[indent]+str(key)+':\033[00m')
                else:
                    print('\t'*indent, str(key)+':')
            print_dict(dictionary[key], previous=key, indent=indent+1, colors=colors)
    else:
        if colors:
            print('\t'*(indent-1), term_colors[indent+1]+str(previous)+':\033[00m', dictionary)
        else:
            print('\t'*(indent-1), str(previous)+':', dictionary)

def print_red(str_val):
    print("\t", term_colors[0]+str(str_val)+'\033[00m', end="")
    
def print_green(str_val):
    print("\t", term_colors[1]+str(str_val)+'\033[00m', end="")

def print_yellow(str_val):
    print("\t", term_colors[2]+str(str_val)+'\033[00m', end="")

def print_blue(str_val):
    print("\t", term_colors[3]+str(str_val)+'\033[00m', end="")
    
def execute_shell_cmd(cmd: str) -> tuple[bool, str]:
    """Run shell command"""
    stat = True
    try:
        fp = subprocess.run(
            cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
    except FileNotFoundError as fne:
        res = fne.strerror + f": {cmd}"
        stat = False
    else:
        if fp.returncode:
            res = (
                fp.stdout.rstrip(b"\t\n\r")
                + f"\n- Error Code: {fp.returncode}\n- Error:\n".encode()
                + fp.stderr.rstrip(b"\t\n\r")
            ).decode()
            stat = False
        else:
            res = fp.stdout.rstrip(b"\t\n\r").decode()
    return stat, res


def get_pci_bdf_info(vendor_id):
    """Get the fpga device bdf"""
    stat, stdout = execute_shell_cmd("lspci -n")
    if not stat:
        return None
    for line in stdout.splitlines():
        if vendor_id in line:
            bdf_info = line.split()[0]

    return bdf_info


def read_sysfile_value(devfile):
    """read sysfs file value"""
    if pathlib.Path(devfile).exists():
        try:
            with open(devfile, "r", encoding="utf-8") as devfd:
                val = devfd.read().strip()
        except IOError:
            print(f"FAIL\tcannot open {devfile}")
            val = None
        except Exception as err:
            print(f"FAIL\tUnexpected {err=}, {type(err)=}")
            val = None
            raise
    else:
        print(MSG.format(devfile))
        val = None

    return val


def write_sysfile_value(devfile, val):
    """write sysfs file value"""
    status = "PASS"
    stat = True
    if pathlib.Path(devfile).exists():
        try:
            with open(devfile, "w", encoding="utf-8") as devfd:
                devfd.write(str(val))
        except IOError:
            status = f"FAIL\tcannot open {devfile}"
            stat = False
        except Exception as err:
            status = f"FAIL\tUnexpected {err=}, {type(err)=}"
            stat = False
            print(status)
            raise
    else:
        status = MSG.format(devfile)
        stat = False

    return stat, status


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


def select_dom1():
    gpiocmd = "gpioset gpiochip0 9=1"
    os.system(gpiocmd)


def firmware_upgrade():
    """Upgrade firmware functionality"""
    devices_list = list(CHIP_MAP.keys())
    print(f"Components list: {devices_list}")
    try:
        for i in range(5):
            if i < 3:
                i = i + 1
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
        select_gpiocmd = f"gpioset gpiochip0 {gpionum}=1"
        release_gpiocmd = f"gpioget gpiochip0 {gpionum}"
        flash_devmap = f"/run/devmap/flashes/{devname.upper()}_FLASH"
        upgrade_cmd = f"flashrom -p linux_spi:dev={os.readlink(flash_devmap)} -w {fwimg} -c {chipname}"
        print(upgrade_cmd)
        if gpionum:
            os.system(select_gpiocmd)
        os.system(upgrade_cmd)
        if gpionum:
            os.system(release_gpiocmd)
    except EOFError:
        print(f"Error: No input or {devname} is reached!")
