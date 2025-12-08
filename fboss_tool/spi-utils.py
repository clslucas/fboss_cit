#!/usr/bin/env python3

import os
import sys
import subprocess
import time

TMP_DIR = "/tmp/.fboss-fwtmp"
IOB_GPIOCHIP = os.path.basename(os.readlink("/run/devmap/gpiochips/IOB_GPIO_CHIP_0"))

def clean_env():
    """Cleanup temporary directory."""
    if os.path.exists(TMP_DIR):
        os.rmdir(TMP_DIR)

def usage():
    """Print usage information."""
    program = os.path.basename(sys.argv[0])
    print(f"Usage: {program} <component> <action> <flash-file>")
    print("    <component> : dom1, dom2, iob, mcbcpld, j3a, j3b, th5, scmcpld, smbcpld, pwrcpld, smb1cpld, smb2cpld")
    print("    <action> : program, verify, read")

def spidev_bind(spi_id, spi_chardev):
    """Bind spidev driver to the flash."""
    if not os.path.exists(f"/dev/{spi_chardev}"):
        print(f"Attaching {spi_id} to spidev driver...")
        with open(f"/sys/bus/spi/devices/{spi_id}/driver_override", "w") as f:
            f.write("spidev")
        with open("/sys/bus/spi/drivers/spidev/bind", "w") as f:
            f.write(spi_id)
        time.sleep(1)

def flash_do_io(spidev, chip, io_type, io_file):
    """Read/Write/Verify flashes using flashrom."""
    command = f"flashrom -p linux_spi:dev={spidev} -c {chip} -{io_type} {io_file}"
    print(command)
    subprocess.run(command, shell=True)

def select_dom1():
    """Select DOM1 flash."""
    print("Selecting DOM1 flash...")
    set_gpio(IOB_GPIOCHIP, 9, 1)

def release_dom1():
    """Release DOM1 flash."""
    print("Releasing DOM1 flash...")
    set_gpio(IOB_GPIOCHIP, 9, 0)

def select_dom2():
    """Select DOM2 flash."""
    print("Selecting DOM2 flash...")
    set_gpio(IOB_GPIOCHIP, 10, 1)

def release_dom2():
    """Release DOM2 flash."""
    print("Releasing DOM2 flash...")
    set_gpio(IOB_GPIOCHIP, 10, 0)

def select_th5():
    """Select TH5 flash."""
    print("Selecting TH5 flash...")
    set_gpio(IOB_GPIOCHIP, 8, 1)

def release_th5():
    """Release TH5 flash."""
    print("Releasing TH5 flash...")
    set_gpio(IOB_GPIOCHIP, 8, 0)

def select_j3a():
    """Select J3A flash."""
    print("Selecting J3A flash...")
    set_gpio(IOB_GPIOCHIP, 8, 1)

def release_j3a():
    """Release J3A flash."""
    print("Releasing J3A flash...")
    set_gpio(IOB_GPIOCHIP, 8, 0)

def select_j3b():
    """Select J3B flash."""
    print("Selecting J3B flash...")
    set_gpio(IOB_GPIOCHIP, 10, 1)

def release_j3b():
    """Release J3B flash."""
    print("Releasing J3B flash...")
    set_gpio(IOB_GPIOCHIP, 10, 0)

def select_iob():
    """Select IOB flash."""
    print("Selecting IOB flash...")

def release_iob():
    """Release IOB flash."""
    print("Releasing IOB flash...")

def select_mcbcpld():
    """Select MCB_CPLD flash."""
    print("Selecting MCB_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 3, 1)

def release_mcbcpld():
    """Release MCB_CPLD flash."""
    print("Releasing MCB_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 3, 0)

def select_scmcpld():
    """Select SCM_CPLD flash."""
    print("Selecting SCM_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 1, 1)

def release_scmcpld():
    """Release SCM_CPLD flash."""
    print("Releasing SCM_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 1, 0)

def select_smbcpld():
    """Select SMB_CPLD flash."""
    print("Selecting SMB_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 7, 1)

def release_smbcpld():
    """Release SMB_CPLD flash."""
    print("Releasing SMB_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 7, 0)

def select_pwrcpld():
    """Select PWR_CPLD flash."""
    print("Selecting PWR_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 3, 1)

def release_pwrcpld():
    """Release PWR_CPLD flash."""
    print("Releasing PWR_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 3, 0)

def select_smb1cpld():
    """Select SMB1_CPLD flash."""
    print("Selecting SMB1_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 1, 1)

def release_smb1cpld():
    """Release SMB1_CPLD flash."""
    print("Releasing SMB1_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 1, 0)

def select_smb2cpld():
    """Select SMB2_CPLD flash."""
    print("Selecting SMB2_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 7, 1)

def release_smb2cpld():
    """Release SMB2_CPLD flash."""
    print("Releasing SMB2_CPLD flash...")
    set_gpio(IOB_GPIOCHIP, 7, 0)

def select_i210():
    """Select I210 flash."""
    print("Selecting I210 flash...")
    set_gpio(IOB_GPIOCHIP, 2, 1)

def release_i210():
    """Release I210 flash."""
    print("Releasing I210 flash...")
    set_gpio(IOB_GPIOCHIP, 2, 0)

def select_comenic():
    """Select Comenic flash."""
    print("Selecting Comenic flash...")
    set_gpio(IOB_GPIOCHIP, 0, 1)
    set_gpio(IOB_GPIOCHIP, 2, 1)

def release_comemic():
    """Release Comenic flash."""
    print("Releasing Comenic flash...")
    set_gpio(IOB_GPIOCHIP, 0, 0)
    set_gpio(IOB_GPIOCHIP, 2, 0)

def set_gpio(chip, pin, value):
    """Set GPIO pin value."""
    subprocess.run(f"gpioset {chip} {pin}={value}", shell=True)

def generate_binary_file(user_file, flash_size):
    """Generate full size binary file for CPLD flashes."""
    imgsize = os.path.getsize(user_file)
    if imgsize == flash_size:
        print("Full size image, no need to convert.")
        return user_file
    elif imgsize > flash_size:
        print("Image file size mismatch, exiting.")
        sys.exit(1)
    else:
        print("Generating full size binary file.")
        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)
        tmpfile = os.path.join(TMP_DIR, "tmpbinary")
        cpld_header = os.path.join(TMP_DIR, "cpldheader")

        with open(cpld_header, "wb") as f:
            f.write(b"\xff" * 65536)

        with open(tmpfile, "wb") as f:
            with open(cpld_header, "rb") as header:
                f.write(header.read())
            with open(user_file, "rb") as img:
                f.write(img.read())

        # Extend the image size to fit flash size
        filesize = os.path.getsize(tmpfile)
        addsize = flash_size - filesize

        if addsize > 0:
            with open(tmpfile, "ab") as f:
                f.write(b"\xff" * addsize)

        return tmpfile

if __name__ == "__main__":
    if len(sys.argv) != 4:
        usage()
        sys.exit(1)

    component = sys.argv[1]
    action = sys.argv[2]
    user_file = sys.argv[3]

    # Validate firmware component
    flash_config = {
        "iob": {"spi_bus": 0, "chip": "N25Q128..3E", "flash_size": 16384 * 1024},
        "dom1": {"spi_bus": 1, "chip": "N25Q128..3E", "flash_size": 16384 * 1024},
        "dom2": {"spi_bus": 2, "chip": "N25Q128..3E", "flash_size": 16384 * 1024},
        "j3b": {"spi_bus": 2, "chip": "N25Q128..1E", "flash_size": 32768 * 1024},
        "pwrcpld": {"spi_bus": 3, "chip": "W25X20", "flash_size": 256 * 1024},
        "mcbcpld": {"spi_bus": 3, "chip": "W25X20", "flash_size": 256 * 1024},
        "smbcpld": {"spi_bus": 4, "chip": "W25X20", "flash_size": 256 * 1024},
        "smb2cpld": {"spi_bus": 4, "chip": "W25X20", "flash_size": 256 * 1024},
        "th5": {"spi_bus": 5, "chip": "N25Q128..1E", "flash_size": 32768 * 1024},
        "j3a": {"spi_bus": 5, "chip": "N25Q128..1E", "flash_size": 32768 * 1024},
        "scmcpld": {"spi_bus": 6, "chip": "W25X20", "flash_size": 256 * 1024},
        "smb1cpld": {"spi_bus": 6, "chip": "W25X20", "flash_size": 256 * 1024},
        "comenic": {"spi_bus": 6, "chip": "W25Q32JV", "flash_size": 4096 * 1024},
        "i210": {"spi_bus": 7, "chip": "W25Q32JV", "flash_size": 4096 * 1024},
    }

    if component not in flash_config:
        print(f"Invalid <component>: {component}")
        usage()
        sys.exit(1)

    spi_bus = flash_config[component]["spi_bus"]
    chip = flash_config[component]["chip"]
    flash_size = flash_config[component]["flash_size"]

    # Validate I/O type
    flash_op = {
        "read": "r",
        "program": "w",
        "verify": "v",
    }.get(action)

    if flash_op is None:
        print(f"Invalid <action>: {action}")
        usage()
        sys.exit(1)

    spi_cs = 0
    spi_id = f"spi{spi_bus}.{spi_cs}"
    spi_chardev = f"spidev{spi_bus}.{spi_cs}"

    # Prepare flash I/O
    globals()[f"select_{component}"]()
    spidev_bind(spi_id, spi_chardev)

    # Launch flash I/O
    if action == "program":
        tmpfile = generate_binary_file(user_file, flash_size)
        print(f"{action} flash (tmpfile={tmpfile})...")
        flash_do_io(f"/dev/{spi_chardev}", chip, flash_op, tmpfile)
    else:
        print(f"{action} flash (usefile={user_file})...")
        flash_do_io(f"/dev/{spi_chardev}", chip, flash_op, user_file)

    # Release flash I/O
    globals()[f"release_{component}"]()
    clean_env()

