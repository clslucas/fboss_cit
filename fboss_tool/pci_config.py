import pathlib
import subprocess
from typing import Tuple, Optional

PASS = "\033[1;32mPASS\033[00m"
FAILED = "\033[1;31mFAIL\033[0m"

DEV_INOF = {
    "vendor": "0x1d9b",
    "device": "0x0011",
    "subsystem_vendor": "0x10ee",
    "subsystem_device": "0x0007",
}

IOB_BDF = "17:00.0"

PCI_PATH = "/sys/bus/pci/devices/0000:{}"

MSG_FILE_NOT_FOUND = "\u001b[31mFAIL\u001b[0m\t{}File not exist."

# Error handling and logging
# import logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def execute_shell_cmd(cmd: str) -> Tuple[bool, str]:
    """Executes a shell command and returns the status and output."""
    try:
        result = subprocess.run(
            cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
        if result.returncode == 0:
            return True, result.stdout.decode().strip()
        else:
            # logging.error(f"Command '{cmd}' failed with error code {result.returncode}")
            return False, (
                result.stdout.decode().strip()
                + f"\n- Error Code: {result.returncode}\n- Error:\n"
                + result.stderr.decode().strip()
            )
    except FileNotFoundError as fne:
        # logging.error(f"Command '{cmd}' failed: {fne.strerror}")
        return False, fne.strerror + f": {cmd}"


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


def store_config():
    cmd = f"lspci -s {IOB_BDF} -xxx"
    status, stdout = execute_shell_cmd(cmd)
    if not status:
        # logging.error(f"PCI device with BDF '{IOB_BDF}' not found.")
        return None

    return stdout


def compare_config(stored_config):
    # read current config data
    cur_config = store_config()

    if cur_config == stored_config:
        return True

    return False


def compare_data(sys_file, data):
    vendor_file = PCI_PATH.format(IOB_BDF)
    vendor_id = read_sysfile_value(f"{vendor_file}/{sys_file}")
    if vendor_id == data:
        return True

    return False


if __name__ == "__main__":
    print(
        "-------------------------------------------------------------------------\n"
        "                        |  FPGA Config Test  |\n"
        "-------------------------------------------------------------------------"
    )
    # save the config data
    iob_config = store_config()
    stat = compare_config(iob_config)
    print(iob_config)
    print("-------------------------------------------------------------------------")
    config_status = PASS if stat else FAILED
    print("PCI Config raw data compared: ", config_status)
    print(
        "----------------------+------------+-----------\n"
        "     Test items       |    Value   |  Status\n"
        "----------------------+------------+-----------"
    )
    for k, v in DEV_INOF.items():
        stat = compare_data(k, v)
        data_status = PASS if stat else FAILED
        print(f'{"":4}{k:<18}{"|":<4}{v:<7}{"":>2}{"|":<3}{data_status}')
        print("----------------------+------------+-----------")