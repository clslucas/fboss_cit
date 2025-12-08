#!/usr/bin/env python3

import mmap
import struct
import contextlib
import subprocess
from typing import Tuple, Optional

# Constants for XADC registers
XADC_TEMP = [0x200, 0x280, 0x290]
XADC_VCCINT = [0x204, 0x284, 0x294]
XADC_VCCAUX = [0x208, 0x288, 0x298]
XADC_VCCBRAM = [0x218, 0x28c, 0x29c]

IOB_XADC = {
    "Temperature": XADC_TEMP,
    "VCCINT": XADC_VCCINT,
    "VCCAUX": XADC_VCCAUX,
    "VCCBRAM": XADC_VCCBRAM
}

# Define IOB device ID and paths
IOB_DEV_ID = "1d9b:0011"
BDF_PATH = "/sys/bus/pci/devices/0000:{}/"

# Error handling and logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def execute_shell_cmd(cmd: str) -> Tuple[bool, str]:
    """Executes a shell command and returns the status and output."""
    try:
        result = subprocess.run(
            cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
        if result.returncode == 0:
            return True, result.stdout.decode().strip()
        else:
            logging.error(f"Command '{cmd}' failed with error code {result.returncode}")
            return False, (
                result.stdout.decode().strip()
                + f"\n- Error Code: {result.returncode}\n- Error:\n"
                + result.stderr.decode().strip()
            )
    except FileNotFoundError as fne:
        logging.error(f"Command '{cmd}' failed: {fne.strerror}")
        return False, fne.strerror + f": {cmd}"

def get_pci_bdf_info(vendor_id: str) -> Optional[str]:
    """Retrieves the PCI Bus, Device, and Function (BDF) information for a device with the given vendor ID."""
    status, stdout = execute_shell_cmd("lspci -n")
    if not status:
        return None
    for line in stdout.splitlines():
        if vendor_id in line:
            return line.split()[0]
    logging.warning(f"PCI device with vendor ID '{vendor_id}' not found.")
    return None

def get_fpga_path():
    """Gets the FPGA path based on its PCI BDF."""
    fpga_bdf = get_pci_bdf_info(IOB_DEV_ID)
    if fpga_bdf is None:
        return None
    return f"{BDF_PATH}".format(fpga_bdf)

def _fpga_io_operation(reg: int, val=None):
    """Performs FPGA I/O operations."""
    fpga_path = get_fpga_path()
    if fpga_path is None:
        return None
    bdf_fd = f"{fpga_path}resource0"

    try:
        with open(bdf_fd, mode="r+", encoding="utf-8") as fpgaio:
            with contextlib.closing(
                mmap.mmap(
                    fpgaio.fileno(),
                    length=0,
                    flags=mmap.MAP_SHARED,
                    access=mmap.ACCESS_DEFAULT,
                )
            ) as mmap_obj:
                if val is not None:
                    mmap_obj.seek(reg)
                    mmap_obj.write(struct.pack("<I", val))  # Use struct.pack for writing
                    mmap_obj.flush()
                else:
                    mmap_obj.seek(reg)
                    return struct.unpack("<I", mmap_obj.read(4))[0]  # Read as unsigned int
    except IOError as err:
        logging.error(f"I/O error: {err}")
        return None
    except ValueError:
        logging.error("Could not convert data.")
        return None
    except Exception as err:
        logging.exception(f"Unexpected error: {err}")
        return None

def temp_operators(reg_val: int):
    """Calculates temperature from XADC register value."""
    bits_val = (reg_val & 0xFFF0) >> 4
    temp = round((bits_val * 503.975) / 4096 - 273.15, 2)
    return f"{temp} C"

def vcc_operators(reg_val: int):
    """Calculates VCC voltage from XADC register value."""
    bits_val = (reg_val & 0xFFF0) >> 4
    vcc = round((bits_val / 4096) * 3, 3)
    return f"{vcc} V"

def test_iob_xadc():
    """Tests the IOB XADC registers."""
    print(
        "-------------------------------------------------------------------------\n"
        "                          | XADC information |\n"
        "-------------------------------------------------------------------------\n"
        "               | Reg Addr |   Value   |   Max_val   |  Min_val  | status\n"
        "-------------------------------------------------------------------------"
    )
    all_passed = True

    for k, v in IOB_XADC.items():
        if k == "Temperature":
            regval = _fpga_io_operation(v[0])
            if regval is None:
                continue
            val = temp_operators(regval) 
            regval = _fpga_io_operation(v[1])
            if regval is None:
                continue
            max_val = temp_operators(regval)
            regval = _fpga_io_operation(v[2])
            if regval is None:
                continue
            min_val = temp_operators(regval)
        else:
            regval = _fpga_io_operation(v[0])
            if regval is None:
                continue
            val = vcc_operators(regval)
            regval = _fpga_io_operation(v[1])
            if regval is None:
                continue
            max_val = vcc_operators(regval)
            regval = _fpga_io_operation(v[2])
            if regval is None:
                continue
            min_val = vcc_operators(regval)

        status = "\033[1;32mPASS\033[0m"  # Assume pass initially
        if float(val.split(" ")[0]) < float(min_val.split(" ")[0]) or   \
            float(val.split(" ")[0]) > float(max_val.split(" ")[0]):
            status = "\033[1;31mFAIL\033[0m"
            all_passed = False

        print(
            f'{"":>3}{k:12s}{"|":<3}{hex(v[0]):<8}{"|"}{val:>10}{"":>1}{"|"}'
            f'{max_val:>10}{"":>3}{"|"}{min_val:>9}{"":>2}{"|"}{"":>2}{status:<5}'
        )
    print(
        "-------------------------------------------------------------------------\n"
    )

    if all_passed:
        print("All XADC tests passed!")
    else:
        print("Some XADC tests failed.")

if __name__ == "__main__":
    test_iob_xadc()
