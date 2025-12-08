#!/usr/bin/env python3

import unittest
import argparse
import os
import sys
from fboss import Fboss
from xadc import test_iob_xadc
from xcvr import XcvrManager
from leds import port_led_status_test, port_led_loop_test
from hwmon import Hwmon
from sensor import sensor_test
from gpio import gpio_chip_test
from firmware_upgrade import fboss_firmware_test

def arg_parser():
    """Parses command-line arguments."""

    cit_description = """
    CIT supports running following classes of tests:

    Running tests on target FBOSS: test pattern "test_*"
    Running tests on target FBOSS from outside BMC: test pattern "external_*"
    Running tests on target FBOSS from outside BMC: test pattern "external_fw_upgrade*"
    Running stress tests on target FBOSS: test pattern "stress_*"

    Usage Examples:
    On devserver:
    List tests : python cit_runner.py --platform wedge100 --list-tests --start-dir tests/
    List tests that need to connect to BMC: python cit_runner.py --platform wedge100 --list-tests --start-dir tests/ --external --host "NAME"
    List real upgrade firmware external tests that connect to BMC: python cit_runner.py --platform wedge100 --list-tests --start-dir tests/ --upgrade-fw
    Run tests that need to connect to BMC: python cit_runner.py --platform wedge100 --start-dir tests/ --external --bmc-host "NAME"
    Run real upgrade firmware external tests that connect to BMC: python cit_runner.py --platform wedge100 --run-tests "path" --upgrade --bmc-host "NAME" --firmware-opt-args="-f -v"
    Run single/test that need connect to BMC: python cit_runner.py --run-test "path" --external --host "NAME"
    """

    parser = argparse.ArgumentParser(
        prog="fboss_test",
        usage="%(prog)s [options]",
        epilog=cit_description,
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "--run-test",
        "-r",
        help="""Path to run a single test. Example:
            tests.wedge100.test_eeprom.EepromTest.test_odm_pcb""",
    )

    parser.add_argument(
        "-c",
        "--cmd",
        default="iob_version",
        help="""bsp command sets.
command list:
    iob_reset
    iob_uptime
    iob_general
    iob_scatch
    iob_version
    iob_info
    iob_xadc
    spi_udev
    spi_detect
    gpio
    i2c_udev
    i2c_detect
    i2c_buses
    port_led
    loop_leds
    xcvrs
    sensors
    hwmon
    firmware_upgrade
    all""",
    )

    return parser.parse_args()


class TestFboss(unittest.TestCase):
    """Test suite for FBOSS functionality."""

    def setUp(self):
        """Setup method for the test suite."""
        self.fboss = Fboss("./fboss_dvt.json")

    def test_iob_reset(self):
        """Test IOB logic reset."""
        self.fboss.iob_logic_reset_active()

    def test_iob_uptime(self):
        """Test IOB uptime."""
        self.fboss.iob_up_time_test(5)

    def test_iob_general(self):
        """Test IOB general register data."""
        self.fboss.iob_reg_raw_data_show()

    def test_iob_scatch(self):
        """Test IOB scratch pad."""
        self.fboss.iob_scratch_pad()

    def test_iob_version(self):
        """Test IOB version information."""
        self.fboss.show_version_info()

    def test_iob_info(self):
        """Test IOB FPGA information."""
        self.fboss.show_fpga_info()

    def test_iob_xadc(self):
        """Tests the IOB XADC registers."""
        test_iob_xadc()

    def test_spi_udev(self):
        """Test SPI bus udev."""
        self.fboss.spi_bus_udev_test()

    def test_spi_detect(self):
        """Test SPI device detection."""
        self.fboss.detect_spi_device()

    def test_i2c_udev(self):
        """Test I2C driver udev."""
        self.fboss.detect_i2c_drv_udev()

    def test_i2c_detect(self):
        """Test I2C bus detection."""
        self.fboss.detect_iob_i2c_buses()
        self.fboss.detect_doms_i2c_buses()

    def test_i2c_buses(self):
        """Test I2C device detection."""
        self.fboss.detect_i2c_devices()

    def test_gpio(self):
        """Test GPIO chip."""
        gpio_chip_test()

    def test_port_led(self):
        """Test port LED status."""
        port_led_status_test()

    def test_loop_leds(self):
        """Test port LED loop."""
        port_led_loop_test()

    def test_xcvrs(self):
        """Test XCVRs."""
        xcvr_manager = XcvrManager()
        xcvr_manager.test_xcvr_devices()

    def test_sensors(self):
        """Test sensors."""
        sensor_test()

    def test_hwmon(self):
        """Test HWMON."""
        hwmon = Hwmon()
        hwmon.hwmon_test()

    def test_firmware_upgrade(self):
        """Test firmware upgrade."""
        fboss_firmware_test()


if __name__ == "__main__":
    # Parse command-line arguments
    args = arg_parser()

    # Construct the command based on the chosen command
    if args.cmd == "all":
        cmd = f"python -m unittest runner.TestFboss"
    else:
        cmd = f"python -m unittest runner.TestFboss.test_{args.cmd}"

    # Execute the command
    os.system(cmd)
