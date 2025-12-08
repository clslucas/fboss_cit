import os
from fboss_utils import read_sysfile_value, write_sysfile_value, get_platform

# Constants
XCVR_UDEV_PATH = "/run/devmap/xcvrs/"
BASE_VALUE = "0x0"

# Platform-specific XCVR counts (move to a config file)
montblanc_XcvrCount = 64
janga_XcvrCount = 46
tahan_XcvrCount = 33

class XcvrManager:
    """Manages XCVR devices."""

    def __init__(self):
        self.platform = get_platform()
        self.xcvr_count = eval(f"{self.platform}_XcvrCount")

    def _check_xcvr_device(self, device_name):
        """Checks if the XCVR device exists and is properly linked."""
        xcvr_file = os.path.join(XCVR_UDEV_PATH, device_name)
        if not os.path.exists(xcvr_file):
            raise ValueError(f"XCVR device not found: {xcvr_file}")
        if not os.path.islink(xcvr_file):
            raise ValueError(f"XCVR device is not a symbolic link: {xcvr_file}")
        if not os.readlink(xcvr_file):
            raise ValueError(f"XCVR device has an invalid symbolic link: {xcvr_file}")

    def _get_xcvr_value(self, device_name):
        """Reads the current value of the XCVR device."""
        devfile = os.path.join(XCVR_UDEV_PATH, device_name)
        value = read_sysfile_value(devfile)
        if not value:
            raise ValueError(f"Failed to read value from XCVR device: {devfile}")
        return value

    def _set_xcvr_value(self, device_name, set_value):
        """Sets the value of the XCVR device."""
        devfile = os.path.join(XCVR_UDEV_PATH, device_name)
        stat, _ = write_sysfile_value(devfile, int(set_value, 16))
        if not stat:
            raise ValueError(f"Failed to set value for XCVR device: {devfile}")

    def _validate_xcvr_mode(self, device_name):
        """Validates the XCVR mode by switching it and restoring the original value."""
        self._check_xcvr_device(device_name)
        default_val = self._get_xcvr_value(device_name)
        
        # Switch to the opposite mode
        set_val = "0x1" if default_val == BASE_VALUE else "0x0"
        self._set_xcvr_value(device_name, set_val)

        # Verify the switch was successful
        new_val = self._get_xcvr_value(device_name)
        if int(new_val, 16) != int(set_val, 16):
            raise ValueError(f"Failed to switch XCVR mode for device: {device_name}")

        # Restore the original value
        self._set_xcvr_value(device_name, default_val)

        return default_val, new_val

    def test_xcvr_devices(self):
        """Tests the XCVR devices."""
        print(
            "-------------------------------------------------------------------------\n"
            "                        |  XCVR Function Test  |\n"
            "-------------------------------------------------------------------------\n"
            "  PORT ID  |   XCVR UDEV NAME   |  Default Value  |  Test Value  | Status\n"
            "-------------------------------------------------------------------------"
        )
        for mode in ("xcvr_low_power", "xcvr_reset"):
            for i in range(self.xcvr_count):
                device_name = f"xcvr_{i + 1}/{mode}_{i + 1}"
                try:
                    default_val, new_val = self._validate_xcvr_mode(device_name)
                    status = "PASS"
                    print(
                        f'{"":>4}{i:>2}{"":>9}{device_name.split("/")[1]:<18}{"":>7}{default_val:<3}{"":>12}'
                        + f'{new_val:<3}{"":>9}{status.ljust(1)} \n',
                        end="",
                    )
                except ValueError as e:
                    print(
                        f'{"":>4}{i:>2}{"":>9}{device_name.split("/")[1]:<18}{"":>7}NA{"":>12}'
                        + f'NA{"":>9}\033[31mFAIL\033[0m\t{e} \n',
                        end="",
                    )

if __name__ == "__main__":
    xcvr_manager = XcvrManager()
    xcvr_manager.test_xcvr_devices()