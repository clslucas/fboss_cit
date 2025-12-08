#!/usr/bin/env python3

"""Module providing test functions for fboss and fpga."""
import struct
import random
import string
import mmap
import contextlib
import re
import json
from time import sleep
from datetime import timedelta
from fboss_utils import *
import i2cbus
from spibus import SPIBUS

IOB_PCI_DRIVER="fbiob_pci"

# Define constants for IOB registers
IOB_REGS = {
    "Revision": 0x00,
    "Scratch_Pad": 0x04,
    "System_LED": 0x0C,
    "UP_TIME": 0x14,
    "MSI_Debug": 0x18,
    "Latency_Debug": 0x1C,
    "Logic_Reset": 0x20,
    "Thread_Control": 0x24,
    "Interrupt_Status": 0x2C,
    "Soft_Error_Detection": 0x30,
    "DOM1 Revision": 0x40000,
    "DOM2 Revision": 0x48000,
}

# Define constant for IOB UP_TIME register
FBIOB_REG_UP_TIME = 0x14

# Define color codes for output formatting
FMT_RED = "\033[31m{}\033[0m"
FMT_GRN = "\033[32m{}\033[0m"

# Define IOB device ID and paths
IOB_DEV_ID = "1d9b:0011"
DEV_PATH = "/sys/bus/auxiliary/devices/"
BDF_PATH = "/sys/bus/pci/devices/0000:{}/"

# Define SPI device names for different platforms
MONTBLANC_SPI_DEV = ("iob", "dom1", "dom2", "i210", "scm", "smb", "mcb", "th5")
TAHAN_SPI_DEV = ("iob", "dom", "i210", "smb_1", "smb_2", "pwr", "th5")
JANGA_SPI_DEV = ("iob", "dom", "i210", "smb_1", "smb_2", "pwr", "j3a", "j3b")

# Define project stage names
PROJECT_STAGE = ("EVT1", "EVT2", "EVT3", "DVT1", "DVT2", "PVT", "MP", "TBD")

# Define I2C bus and address constants
I2C_BUS_SMBCPLD1 = "IOB_I2C_BUS_3"
I2C_ADDR_SMBCPLD1 = 0x35
I2C_BUS_SMBCPLD2 = "IOB_I2C_BUS_10"
I2C_ADDR_SMBCPLD2 = 0x33
I2C_BUS_PWRCPLD = "IOB_I2C_BUS_16"
I2C_ADDR_PWRCPLD = 0x60

I2C_BUS_SCMCPLD = "IOB_I2C_BUS_3"
I2C_ADDR_SCMCPLD = 0x35
I2C_BUS_SMBCPLD = "IOB_I2C_BUS_10"
I2C_ADDR_SMBCPLD = 0x33
I2C_BUS_MCBCPLD = "IOB_I2C_BUS_14"
I2C_ADDR_MCBCPLD = 0x33


def platform_data_parse(config_file):
    """Parses platform data from a JSON configuration file."""
    # Open JSON file
    with open(config_file, "r", encoding="utf-8") as fd:
        # Returns JSON object as a dictionary
        platform_data = json.load(fd)

    return platform_data


def get_board_id(platformDict) -> str:
    """Gets the current board type."""
    platform = "NA"
    path_file = f"{IOB_PCI_DRIVER}.fpga_info_iob.0/board_id"
    devfile = f"{DEV_PATH}{path_file}"
    board_id = read_sysfile_value(devfile)
    if board_id:
        platform = platformDict.get(board_id)

    return platform


def get_board_revision():
    """Gets the current board revision."""
    board_rev = "NA"
    path_file = f"{IOB_PCI_DRIVER}.fpga_info_iob.0/board_rev"
    devfile = f"{DEV_PATH}{path_file}"
    board_rev = read_sysfile_value(devfile)
    if board_rev:
        board_rev = PROJECT_STAGE[int(board_rev, 16)]

    return board_rev


def get_fpga_path():
    """Gets the FPGA path based on its PCI BDF."""
    fpga_bdf = get_pci_bdf_info(IOB_DEV_ID)

    return f"{BDF_PATH}".format(fpga_bdf)


class Fboss:
    """Represents the Fboss platform."""

    def __init__(self, config_file):
        """Initializes the Fboss object."""
        self.platform_data = platform_data_parse(config_file)
        self.fpga_path = get_fpga_path()
        self._platform = get_board_id(self.platform_data["platformName"])
        spi_map = f"{self._platform}_spidev_map"
        self.SPI_DICT = self.platform_data["spiMasterConfigs"].get(spi_map)
        self.spibus = SPIBUS(self.SPI_DICT, self.fpga_path)

    def _fpga_io_operation(self, reg: hex, val=None):
        """Performs FPGA I/O operations."""
        bdf_fd = f"{self.fpga_path}resource0"

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
                        mmap_obj.write(bytes.fromhex(val))
                        mmap_obj.flush()
                    else:
                        mmap_obj.seek(reg)
                        strout = struct.pack(
                            "<l", *struct.unpack(">l", mmap_obj.read(4))
                        )
                        return bytes.hex(strout)
        except IOError as err:
            print("I/O error:", err)
        except ValueError:
            print("Could not convert data.")
        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")
            raise

    def _execute_i2cget(self, bus: int, addr: int, reg: int) -> tuple[bool, list[int]]:
        """Executes an I2C get command."""
        i2cget_cmd = f"i2cget -y -f {bus} {addr:#4x} {reg:#4x}"
        stat, res = execute_shell_cmd(i2cget_cmd)
        if not stat:
            return False, []

        return True, [int(i, 16) for i in res.split()]

    def gen_random_hex_string(self, size):
        """Generates a random hexadecimal string."""
        return "".join(random.choices(string.hexdigits, k=size))

    def iob_logic_reset_active(self):
        """Activates the IOB logic reset and checks the Scratch Pad register."""
        print(
            "-------------------------------------------------------------------------\n"
            "               | IOB Logic Reset Activation Operation |\n"
            "-------------------------------------------------------------------------"
        )
        start = self._fpga_io_operation(4)
        print(f"Read Scratch Pad register(Before write random value): [{start}]")
        self._fpga_io_operation(0x20, "0x1")
        end = self._fpga_io_operation(4)
        print(f"Read Scratch Pad register(After write random value): [{end}]")
        return f'{"PASS" if end == 0 else "FAIL"}'

    def iob_scratch_pad(self):
        """Tests the IOB Scratch Pad register."""
        print(
            "-------------------------------------------------------------------------\n"
            "                       | IOB Scratch Pad test |\n"
            "-------------------------------------------------------------------------\n"
            " Scratch Original Value |  Random Value  | Scratch New Value | Status\n"
            "-------------------------------------------------------------------------"
        )
        start = self._fpga_io_operation(4)
        random_val = self.gen_random_hex_string(8)
        temp_val = bytes.fromhex(random_val)
        temp_val = temp_val[::-1]
        temp_val = hex(int.from_bytes(temp_val, "big"))[2:]
        self._fpga_io_operation(4, random_val)
        end = self._fpga_io_operation(4)
        status = f'{"PASS" if int(end,16) == int(temp_val,16) else "FAIL"}'
        print(f'{"":>6}0x{start:<16}{"|"}{"":>3}0x{temp_val:<7}{"":>3}{"|"}{"":>4}0x{end:<10}{"":>3}{"|"}{"":>2}{status}')
        print(
            "-------------------------------------------------------------------------\n"
        )
        return status

    def iob_reg_raw_data_show(self):
        """Displays raw data from IOB general registers."""
        print(
            "-------------------------------------------------------------------------\n"
            "               | IOB General register information |\n"
            "-------------------------------------------------------------------------\n"
            "     Reg Name          |       Reg Addr       |     Reg Value\n"
            "-------------------------------------------------------------------------"
        )
        for n in IOB_REGS.keys():
            reg = IOB_REGS.get(n)
            regval = self._fpga_io_operation(reg)
            print(
                f'{"":>5}{n:<20s}{"":>6}{hex(reg):<7}{"":>14}' f"0x{regval:<10} \n",
                end="",
            )
        print(
            "-------------------------------------------------------------------------\n"
        )

    def iob_up_time_test(self, sleep_time: int = None):
        """Tests the IOB UP_TIME register."""
        start = self._fpga_io_operation(FBIOB_REG_UP_TIME)
        if sleep_time:
            stat = FMT_GRN.format("PASS")
            print(
                "-------------------------------------------------------------------------\n"
                "                         | IOB up time test |\n"
                "-------------------------------------------------------------------------\n"
                "   start time  |  sleep time  |   end time   |  diff val  |   Status\n"
                "-------------------------------------------------------------------------"
            )
            sleep(int(sleep_time))
            end = self._fpga_io_operation(FBIOB_REG_UP_TIME)
            stat = f'{FMT_GRN.format("PASS") if sleep_time==(int(end, 16) - int(start, 16)) else FMT_RED.format("FAIL")}'
            print(
                f'{"":5}{int(start, 16)}{"":>12}{sleep_time:<5}{"":>8}'
                f'{int(end, 16):<5}{"":>12}{int(end, 16) - int(start, 16):<5}{"":>6}'
                f"{stat:<5}"
            )
            print(
                "-------------------------------------------------------------------------\n"
            )
            return start, end
        print(
            f"IOB FPGA Up time register value: {start} up time: {int(start, 16)}s(encod)\n"
        )
        return start

    def _show_iob_dev_info(self) -> str:
        """Gets and formats IOB device information."""
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_iob.0/device_id"
        iob_device_id = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_iob.0/fpga_ver"
        iob_version = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_iob.0/board_id"
        iob_board_id = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_iob.0/board_rev"
        iob_board_rev = read_sysfile_value(f"{DEV_PATH}{path_file}")
        uptime_val = self.iob_up_time_test()
        iob_uptime = timedelta(seconds=int(uptime_val, 16))

        return f"""\
IOB Device ID      : {iob_device_id}
IOB FPGA Revision  : {iob_version}
IOB Board ID       : {iob_board_id}
IOB Board Revision : {iob_board_rev}
IOB Uptime         : {iob_uptime}
"""

    def _show_dom1_dev_info(self) -> str:
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.1/device_id"
        dom1_device_id = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.1/fpga_ver"
        dom1_version = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.1/board_id"
        dom1_board_id = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.1/board_rev"
        dom1_board_rev = read_sysfile_value(f"{DEV_PATH}{path_file}")

        return f"""\
DOM1 Device ID     : {dom1_device_id}
DOM1 FPGA Revision : {dom1_version}
DOM1 Board ID      : {dom1_board_id}
DOM1 Board Revision: {dom1_board_rev}
"""

    def _show_dom2_dev_info(self) -> str:
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.2/device_id"
        dom2_device_id = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.2/fpga_ver"
        dom2_version = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.2/board_id"
        dom2_board_id = read_sysfile_value(f"{DEV_PATH}{path_file}")
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.2/board_rev"
        dom2_board_rev = read_sysfile_value(f"{DEV_PATH}{path_file}")

        return f"""\
DOM2 Device ID     : {dom2_device_id}
DOM2 FPGA Revision : {dom2_version}
DOM2 Board ID      : {dom2_board_id}
DOM2 Board Revision: {dom2_board_rev}
"""

    def system_info(self) -> str:
        """get system info test functon"""
        return f"""\
[System Info]
Platform        : {self._platform.title()}
Board revision  : {get_board_revision()}
System Date     : {execute_shell_cmd('date')[1].strip()}
System Uptime   : {execute_shell_cmd('uptime -p')[1].strip()}
"""

    def _bios_version(self) -> str:
        # BIOS Version
        bios_version = "Getting BIOS version error."
        cmd = "dmidecode -s bios-version"
        _, bios_info = execute_shell_cmd(cmd)
        if _:
            bios_version = bios_info

        return bios_version

    def _diagos_version(self) -> str:
        # DiagOS Version
        cmd = "cat /etc/VERSION"
        diagos_version = "Getting DiagOS version error."
        _, os_info = execute_shell_cmd(cmd)
        if _:
            diagos_version = os_info

        return diagos_version.split("=")[1]

    def _bsp_version(self) -> str:
        # FBOSS BSP Version
        cmd = "cat /etc/BSPVER"
        bsp_version = "Getting FBOSS BSP version error."
        _, bsp_info = execute_shell_cmd(cmd)
        if not _:
            return bsp_version

        bsp_version = re.findall(r"BSP_VER\S+", bsp_info, re.M)
        if not bsp_version:
            return None

        version_str = bsp_version[0].split("=")[1]
        return re.sub('["v]', "", version_str)

    def _cplds_version(self, dev_info, dev_addr) -> str:
        # Get CPLD Version
        cpld_version = []
        msg = "\u001b[31mGetting CPLD firmware version error.\u001b[0m"
        busid = i2cbus.get_i2c_bus_id(dev_info)
        if int(busid) < 0:
            return "x", "x", "x"
        for reg in range(1, 4):
            _, val = self._execute_i2cget(busid, dev_addr, reg)
            if not _:
                cpld_version.append(msg)
            cpld_version.append(val)

        return cpld_version[0], cpld_version[1], cpld_version[2]

    def firmware_version_info(self) -> str:
        """get firmware version functon"""
        # IOB/DOM FPGA Version
        _major, _minor, _patch = "x", "x", "x"
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_iob.0/fpga_ver"
        val = read_sysfile_value(f"{DEV_PATH}{path_file}")
        if not val:
            iob_version = "NA"
        else:
            iob_version = f"0.{int(val, 16)}"
        path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.1/fpga_ver"
        val = read_sysfile_value(f"{DEV_PATH}{path_file}")
        if not val:
            dom1_version = "NA"
        else:
            dom1_version = f"0.{int(val, 16)}"

        if self._platform == "montblanc":
            path_file = f"{IOB_PCI_DRIVER}.fpga_info_dom.2/fpga_ver"
            val = read_sysfile_value(f"{DEV_PATH}{path_file}")
            if not val:
                dom2_version = "NA"
            else:
                dom2_version = f"0.{int(val, 16)}"
            # SCM CPLD version
            _major, _minor, _patch = self._cplds_version(
                I2C_BUS_SCMCPLD, I2C_ADDR_SCMCPLD
            )
            scm_version = f"{_major[0] & 0x7f}.{_minor[0]}.{_patch[0]}"

            # SMB CPLD version
            _major, _minor, _patch = self._cplds_version(
                I2C_BUS_SMBCPLD, I2C_ADDR_SMBCPLD
            )
            smb_version = f"{_major[0] & 0x7f}.{_minor[0]}.{_patch[0]}"

            # MCB CPLD version
            _major, _minor, _patch = self._cplds_version(
                I2C_BUS_MCBCPLD, I2C_ADDR_MCBCPLD
            )
            mcb_version = f"{_major[0] & 0x7f}.{_minor[0]}.{_patch[0]}"
            return f"""\
[Firmware Version Info]
{self._platform.title()} BIOS      : {self._bios_version()}
{self._platform.title()} DiagOS    : {self._diagos_version()}
{self._platform.title()} FBOSS BSP : {self._bsp_version()}
{self._platform.title()} IOB FPGA  : {iob_version}
{self._platform.title()} DOM1 FPGA : {dom1_version}
{self._platform.title()} DOM2 FPGA : {dom2_version}
{self._platform.title()} SCM CPLD  : {scm_version}
{self._platform.title()} SMB CPLD  : {smb_version}
{self._platform.title()} MCB CPLD  : {mcb_version}
"""
        if self._platform == "janga" or self._platform == "tahan":
            # PWR CPLD Version
            _major, _minor, _patch = self._cplds_version(
                I2C_BUS_PWRCPLD, I2C_ADDR_PWRCPLD
            )
            pwr_version = f"{_major[0] & 0x7f}.{_minor[0]}.{_patch[0]}"

            # SMB CPLD1 Version
            _major, _minor, _patch = self._cplds_version(
                I2C_BUS_SMBCPLD1, I2C_ADDR_SMBCPLD1
            )
            smb1_version = f"{_major[0] & 0x7f}.{_minor[0]}.{_patch[0]}"

            # SMB CPLD2 Version
            _major, _minor, _patch = self._cplds_version(
                I2C_BUS_SMBCPLD2, I2C_ADDR_SMBCPLD2
            )
            smb2_version = f"{_major[0] & 0x7f}.{_minor[0]}.{_patch[0]}"

            return f"""\
[Firmware Version Info]
{self._platform.title()} BIOS      : {self._bios_version()}
{self._platform.title()} DiagOS    : {self._diagos_version()}
{self._platform.title()} FBOSS BSP : {self._bsp_version()}
{self._platform.title()} IOB FPGA  : {iob_version}
{self._platform.title()} DOM FPGA  : {dom1_version}
{self._platform.title()} PWR CPLD  : {pwr_version}
{self._platform.title()} SMB CPLD1 : {smb1_version}
{self._platform.title()} SMB CPLD2 : {smb2_version}
"""

    def show_version_info(self):
        """show version function"""
        print(
            "-------------------------------------------------------------------------\n"
            "                         | Platfom information |\n"
            "-------------------------------------------------------------------------"
        )
        print(self.system_info())
        print(self.firmware_version_info())

    def show_fpga_info(self):
        """show fpga info function"""
        print(
            "-------------------------------------------------------------------------\n"
            "                         | FPGA information |\n"
            "-------------------------------------------------------------------------"
        )
        print(self._show_iob_dev_info())
        print(self._show_dom1_dev_info())
        if self._platform == "montblanc":
            print(self._show_dom2_dev_info())       

    def detect_i2c_drv_udev(self):
        """i2c controller driver and udev test"""
        print(
            "-------------------------------------------------------------------------\n"
            " Master |  DEV   |          I2C Adapter         |      UDEV      | Status\n"
            "-------------------------------------------------------------------------"
        )
        status, sta_info = i2cbus.check_drv_udev_status()

        return f'{"PASS" if status else sta_info}'

    def detect_iob_i2c_buses(self):
        """iob i2c bus scan"""
        max_bus = self.platform_data["i2cDeviceConfigs"].get("iobBusCount")
        i2cDeviceInfo = f"{self._platform}_i2c_bus_map"
        dev_map = self.platform_data["i2cDeviceConfigs"].get(i2cDeviceInfo)
        print(
            "-------------------------------------------------------------------------\n"
            " Status | CH ID | BUSID |   UDEV Name   |   Slave Devices List\n"
            "-------------------------------------------------------------------------"
        )
        for bus_name in dev_map.keys():
            status, sta_info = i2cbus.scan_verify_i2c_bus(
                self._platform, "IOB", bus_name, dev_map
            )

        return status, sta_info

    def detect_doms_i2c_buses(self):
        """dom1 i2c bus scan"""
        I2CBusCount = f"{self._platform}XcvrCount"
        max_bus = self.platform_data["i2cDeviceConfigs"].get(I2CBusCount)
        dev_map = self.platform_data["i2cDeviceConfigs"].get("xcvrDevicesMap")
        print(
            "-------------------------------------------------------------------------\n"
            " Status | CH ID | BUSID |  UDEV  |  REG  |  PRE  | RST | Slave Devices List\n"
            "-------------------------------------------------------------------------"
        )
        for n in range(max_bus):
            bus_name = f"XCVR_{n + 1}"
            status, sta_info = i2cbus.scan_verify_i2c_bus(
                self._platform, "DOM", bus_name, dev_map
            )

        return status, sta_info

    def scan_spi_device_test(self, devs: tuple[str, ...]) -> tuple[int, str]:
        """detect spidev flash functon"""
        err_cnt: int = 0
        print(
            "-------------------------------------------------------------------------\n"
            "  Device Name | BusID | GPIOMUX |  Vendor  |   Chip   |   Size   | Status\n"
            "-------------------------------------------------------------------------"
        )
        for dev in devs:
            res = self.spibus.spi_scan(dev)
            print(f'{"PASS" if res else "FAILED":>6s} ')
            err_cnt += 1 if not res else 0

        return err_cnt, f"Scanned {len(devs)} spi devices, {err_cnt} failed."

    def detect_spi_device(self):
        """spidev test functon"""
        spi_dev = f"{self._platform.upper()}_SPI_DEV"
        return self.scan_spi_device_test(eval(spi_dev))

    def spi_bus_udev_test(self):
        """spi master udev test functon"""
        print(
            "-------------------------------------------------------------------------\n"
            " Master ID  |  SPI BUS  |   spidev    |       SPI UDEV       |  Status\n"
            "-------------------------------------------------------------------------"
        )
        stat, status = self.spibus.spi_master_detect()
        print(
            "-------------------------------------------------------------------------\n"
        )
        return f'{"PASS" if stat else status}'

    def fboss_sensor_test(self):
        """sensors test functon"""
        print(
            "-------------------------------------------------------------------------\n"
            "                        |  Sensor devices Test  |\n"
            "-------------------------------------------------------------------------"
        )
        sensor.sensors_folder_list()
        return sensor.sensor_test(self._platform)

    def detect_i2c_devices(self):
        print(
            "-------------------------------------------------------------------------\n"
            "                        |  I2C buses detect Test  |\n"
            "-------------------------------------------------------------------------\n"
            "                           IOB I2C buses Detect\n"
            "-------------------------------------------------------------------------"
        )
        max_bus = self.platform_data["i2cDeviceConfigs"].get("iobBusCount")
        i2cDeviceInfo = f"{self._platform}_i2c_bus_map"
        dev_map = self.platform_data["i2cDeviceConfigs"].get(i2cDeviceInfo)
        for bus_name in dev_map.keys():
            i2cbus.detect_i2c_devices(bus_name)

        print(
            "-------------------------------------------------------------------------\n"
            "                           DOM I2C buses Detect\n"
            "-------------------------------------------------------------------------"
        )
        max_bus = self.platform_data["i2cDeviceConfigs"].get("iobBusCount")
        i2cDeviceInfo = f"{self._platform}_i2c_bus_map"
        for n in range(max_bus):
            bus_name = f"XCVR_{n + 1}"
            i2cbus.detect_i2c_devices(bus_name)
        print(
            "-------------------------------------------------------------------------\n"
        )

    def fboss_end_flag_test(self):
        """fboss end test flag"""
        print(
            "-------------------------------------------------------------------------\n"
        )
