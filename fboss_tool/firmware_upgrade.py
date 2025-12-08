import os
import time
import pathlib
from fboss_utils import execute_shell_cmd

# Chip and GPIO pin mappings
CHIP_MAP = {
    "iob": "N25Q128..3E",
    "dom1": "N25Q128..3E",
    "dom2": "N25Q128..3E",
    "mcbcpld": "W25X20",
    "smbcpld": "W25X20",
    "scmcpld": "W25X20",
    "pwrcpld": "W25X20",
    "smbcpld1": "W25X20",
    "smbcpld2": "W25X20",
}

GPIOPIN_MAP = {
    "dom1": "9",
    "dom2": "10",
    "mcbcpld": "3",
    "smbcpld": "7",
    "scmcpld": "1",
    "pwrcpld": "3",
    "smbcpld1": "1",
    "smbcpld2": "7",
}

def select_gpio(gpio_pin: str) -> None:
    """Selects the specified GPIO pin."""
    gpiocmd = f"gpioset gpiochip0 {gpio_pin}=1"
    os.system(gpiocmd)

def release_gpio(gpio_pin: str) -> None:
    """Releases the specified GPIO pin."""
    gpiocmd = f"gpioset gpiochip0 {gpio_pin}=0"
    os.system(gpiocmd)

# Removed progress_bar function

def get_firmware_image_md5(fwimg: str) -> str:
    """Calculates and returns the MD5 checksum of the firmware image."""
    status, stdout = execute_shell_cmd(f"md5sum {fwimg}")
    if not status:
        print("Not support md5sum utilty.")
        return ""
    for line in stdout.splitlines():
        return line.split()[0]

def verify_firmware_md5(fwimg: str) -> bool:
    """Verifies the MD5 checksum of the firmware image against a .md5 file."""
    img_md5 = get_firmware_image_md5(fwimg)
    fwimg_folder = os.path.dirname(fwimg)  # Get the folder path
    md5_file = os.path.join(fwimg_folder, os.path.basename(fwimg) + ".md5")  # Construct the MD5 file path
    if pathlib.Path(md5_file).exists():
        with open(md5_file, 'r') as f:
            read_md5 = f.read().strip().split()[0]
        if read_md5 != img_md5:
            print("Image MD5 checksum mismatch!")
            return False
    return True

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

    # Verify MD5 checksum
    if not verify_firmware_md5(fwimg):
        if input("Continue upgrade despite MD5 mismatch? (y/n): ").lower() != 'y':
            return

    # Show image MD5
    img_md5 = get_firmware_image_md5(fwimg)
    print("\nFirmware Image MD5:", img_md5, "\n")

    # Switch mux to select flash device and upgrade
    if gpionum:
        select_gpio(gpionum)

    flash_devmap = f"/run/devmap/flashes/{devname.upper()}_FLASH"
    if devname == "scmcpld":
        flash_devmap = f"/run/devmap/flashes/I210_{devname.upper()}_FLASH"
    upgrade_cmd = f"flashrom -p linux_spi:dev={os.readlink(flash_devmap)} -w {fwimg} -c {chipname}"
    print(upgrade_cmd, "\n\nStarting firmware upgrade...\n")

    os.system(upgrade_cmd)

    # Release GPIO pin
    if gpionum:
        release_gpio(gpionum)

def fboss_firmware_test():
    print(
        "-------------------------------------------------------------------------\n"
        "                       |  Firmware Upgrade test  |\n"
        "-------------------------------------------------------------------------\n"
    )
    firmware_upgrade()
    print(
        "\n-------------------------------------------------------------------------\n"
    )

if __name__ == "__main__":
    fboss_firmware_test()
