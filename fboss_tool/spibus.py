"""Module providing spi master and spidev test."""

import os
import pathlib
import re
from ast import literal_eval
from typing import Dict, List, Tuple

from fboss_utils import execute_shell_cmd

IOB_PCI_DRIVER="fbiob_pci"

DEVMAP_SPI = "/run/devmap/flashes/"
SPI_VENDOR_PATTERN = re.compile(r"vendor=\"([\w\d]+)\"\sname=\"([\w\d.]+)\"")

FMTOUT = "\u001b[31m{}\u001b[0m"


def generate_spidev():
    """Generate spidev devices."""
    for busid in range(8):
        drv_path = f"/sys/bus/spi/devices/spi{busid}.0/driver_override"
        dev_path = f"/dev/spidev{busid}.0"
        bind_path = "/sys/bus/spi/drivers/spidev/bind"
        if not pathlib.Path(drv_path).exists() or not pathlib.Path(bind_path).exists():
            break
        if not pathlib.Path(dev_path).exists():
            with open(drv_path, "w", encoding="utf-8") as fd:
                fd.write("spidev")
            with open(bind_path, "w", encoding="utf-8") as fd:
                fd.write(f"spi{busid}.0")


class SPIBUS:
    """spi master and spidev class."""

    def __init__(self, spi_info: Dict, fpga_path: str):
        self._fpga_path = fpga_path
        self.spi_dict = spi_info
        generate_spidev()

    def _get_spidev_from_udev(self, spidev_name: str) -> Tuple[bool, str]:
        """get spidev info."""
        dev_name = f"{DEVMAP_SPI}{spidev_name}"
        if pathlib.Path(dev_name).exists():
            chardev = os.readlink(dev_name)
            if pathlib.Path(chardev).exists():
                spidev_info = os.path.basename(chardev)
                return True, spidev_info
        return False, "NA"

    def _detect_gpio(self) -> str:
        """detect gpio info."""
        stat, stdout = execute_shell_cmd("gpiodetect")
        if stat:
            return stdout.strip().split(" ")[0]
        return "NA"

    def parse_spidev_udev(self, busid: int) -> Tuple[bool, str, str]:
        """parse spidev info."""
        spidev_info = ""
        spidev_udev = ""
        udev_flag = False
        # get spi flash device udev
        if not pathlib.Path(DEVMAP_SPI).exists():
            return False, "NA", "NA"
        spi_udev = os.listdir(DEVMAP_SPI)
        for value in self.spi_dict.values():
            if busid == value["bus"]:
                udev_flag = True
                spidev_udev = value["udev"]
                if spidev_udev in spi_udev:
                    sta, spidev_dev = self._get_spidev_from_udev(spidev_udev)
                    if not sta:
                        return False, FMTOUT.format("FAIL - udev Invalid."), "NA"
                    spidev_info = re.findall(r"\d+?d*", spidev_dev)[0]
                    return True, spidev_info, spidev_udev
                return False, FMTOUT.format(f"FAIL - match error {spi_udev}."), "NA"
        if not udev_flag:
            return True, str(busid), "NA"
        return False, "NA", "NA"

    def spi_master_detect(self) -> Tuple[bool, str]:
        """detect spi master info."""
        for busid in range(8):
            errcode, status = True, "PASS"
            dev_path = f"/sys/bus/spi/devices/spi{busid}.0"
            master_path = f"{self._fpga_path}{IOB_PCI_DRIVER}.spi_master.{busid}"

            if pathlib.Path(dev_path).exists() and pathlib.Path(master_path).exists():
                cmd_str = f"basename {dev_path}"
                sta, res = execute_shell_cmd(cmd_str)
                if sta:
                    spibus = res.split()[0]
                    masterid = re.findall(r"\d+?d*", spibus)[0]
                    spidev_info = f"spidev{masterid}.0"
                else:
                    errcode = False
                    spidev_info = "NA"
                    status = FMTOUT.format("FAIL - SPI Bus devive Error.")

                sta, spidevid, spidev_udev = self.parse_spidev_udev(busid)
                if not sta:
                    if spidevid != str(busid):
                        errcode = False
                else:
                    if int(spidevid) != int(masterid):
                        errcode = False
                        status = FMTOUT.format(
                            f"FAIL - UDEV map Error.[spi.{spidevid}]"
                        )
            else:
                spibus = spidev_info = spidev_udev = "NA"
                errcode = False
                status = FMTOUT.format("FAIL - SPI Master or Driver Error.")

            print(
                f'{busid:>7d}{"":2}{spibus:>12}{"":5}{spidev_info:>10}'
                + f'{spidev_udev:>20s}{"":8}{status:<7s}'
            )
        return errcode, status

    def spi_scan(self, dev: str) -> bool:
        """detect spi flash chip info."""
        dev_info = self.spi_dict.get(dev)
        res = True
        vendor, name, size = "NA", "NA", "NA"
        gpiopin = self.spi_dict[dev].get("gpiopin")

        gpiochip = self._detect_gpio()
        if dev_info is None:
            return False

        if gpiopin:
            self._set_gpio_pins(gpiochip, gpiopin, 1)

        spidev = f'/dev/spidev{self.spi_dict[dev]["bus"]}.0'
        if not os.path.exists(spidev):
            return False

        if dev == "iob":
            cmd = (
                f"flashrom -p linux_spi:dev={spidev} -c"
                + f' {self.spi_dict[dev]["chip"]} --flash-name'
            )
            stat, stdout = execute_shell_cmd(cmd)

        cmd = (
            f"flashrom -p linux_spi:dev={spidev} -c"
            + f' {self.spi_dict[dev]["chip"]} --flash-name'
        )
        stat, stdout = execute_shell_cmd(cmd)
        if not stat:
            return False
        try:
            vendor, name = SPI_VENDOR_PATTERN.findall(stdout.splitlines()[-1])[0]
        except ValueError:
            return False
        cmd = (
            f"flashrom -p linux_spi:dev={spidev} -c"
            + f' {self.spi_dict[dev]["chip"]} --flash-size'
        )
        stat, stdout = execute_shell_cmd(cmd)
        if not stat:
            size = "NA"
        else:
            size = f"{literal_eval(stdout.splitlines()[-1])//1024} KB"

        if gpiopin:
            self._set_gpio_pins(gpiochip, gpiopin, 0)

        mux = self.spi_dict[dev]["gpiopin"]
        print(
            f'{dev.upper():>7s} Flash   {self.spi_dict[dev]["bus"]:>3d}   '
            + f'{"".join(map(str, mux)) if mux else "NA":>6}{"":7}{vendor.ljust(7)}  '
            + f" {name.ljust(10)}{size:>9} ",
            end="",
        )

        return res

    def _set_gpio_pins(self, gpiochip: str, gpiopin: List[int], value: int):
        """Set GPIO pins to a specific value."""
        for pinid in gpiopin:
            cmd = f"gpioset {gpiochip} {pinid}={value}"
            stat, _ = execute_shell_cmd(cmd)
            if not stat:
                raise RuntimeError(f"Failed to set GPIO pin {pinid} to {value}")
