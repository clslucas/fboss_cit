#!/usr/bin/env python3

import os
import re
import csv
from pathlib import Path

# Constants for sensor status and error messages
SENSOR_SUCCESS = "success"
PASS = "\033[1;32mPASS\033[00m"
FAILED = "\033[1;31mFAIL\033[0m"

# Define paths and constants
IOB_PCI_DRIVER = "fbiob_pci"
I2C_PATH = "/sys/bus/auxiliary/devices/{}.{}_i2c_master.{}/"
HWMON_PATH = "/sys/bus/auxiliary/devices/{}.{}_i2c_master.{}/i2c-{}/{}-00{}/hwmon"
MUX_DEV_PATH = (
    "/sys/bus/auxiliary/devices/{}.{}_i2c_master.{}/i2c-{}/{}-0070/channel-{}"
)
CPU_TEMP = "/sys/devices/platform/coretemp.0/hwmon"


# Sensor data structure (more organized)
class Sensor:
    """
    Represents a sensor with its attributes.
    """

    def __init__(
        self,
        sensor_name,
        local,
        busid,
        addr,
        sysfs_link,
        position,
        coefficient,
        unit,
        maxval,
        minval,
    ):
        self.sensor_name = sensor_name
        self.local = local
        self.busid = busid
        self.addr = addr
        self.sysfs_link = sysfs_link
        self.position = position
        self.coefficient = coefficient
        self.unit = unit
        self.maxval = maxval
        self.minval = minval

    def value_format(self, unit: str, value: str) -> str:
        """
        Formats the sensor value based on its unit.
        """
        if value:
            if unit == "V":
                return round(int(value) / 1000, 2)
            elif unit == "RPM":
                return value
            elif unit == "°C":
                return round(int(value) / 1000, 2)
            elif unit == "A":
                return round(int(value) / 1000, 2)
            elif unit == "W":
                return round(int(value) / 1000000, 2)
            elif unit == "Hz":
                return round(int(value) / 1000000, 2)

    def get_i2c_bus(self, directory):
        """
        Searches for the I2C bus ID within files in a given directory.
        """
        # Use pathlib to iterate over files in the directory
        for file in Path(directory).iterdir():
            dev = re.findall(r"i2c-\d+", file.name, re.M)
            if dev:
                return dev[0].split("-")[1]
        return None

    def _read_sensor_data(self):
        """
        Reads sensor data from either sysfs link or device path.
        """
        file = self.sysfs_link

        data = self._read_sysfs_data(file)
        if data:
            return data

        data = self._read_device_data()
        if data:
            return data

        return None

    def _read_sysfs_data(self, file_path):
        """
        Reads sensor data from the sysfs link.
        """
        if not Path(file_path).exists():
            return None
        with open(file_path, "r") as f:
            sensor_data = f.read().strip()
            if self.coefficient:
                sensor_data = round(float(sensor_data) * float(self.coefficient), 3)
        return sensor_data

    def _read_device_data(self):
        """
        Reads sensor data from the device path.
        """

        local = self.local.lower()
        dev_name = self.sysfs_link.split("/")[-1]

        if "mux_" in local:
            dev_local = local.split("_")[1].lower()
            mux_busid = local.split("_")[2].lower()
            bus_path = I2C_PATH.format(IOB_PCI_DRIVER, dev_local, mux_busid)
        else:
            bus_path = I2C_PATH.format(IOB_PCI_DRIVER, local, self.busid)

        if Path(bus_path).exists():
            devid = self.get_i2c_bus(bus_path)
            if "mux_" in local:
                tmp_path = MUX_DEV_PATH.format(
                    IOB_PCI_DRIVER, dev_local, mux_busid, devid, devid, self.busid
                )
                for files in os.listdir(tmp_path):
                    if self.addr[2:] in files:
                        tmp_path = f"{tmp_path}/{files}/hwmon"
                        for dirs in Path(tmp_path).iterdir():
                            dev_file = f"{tmp_path}/{dirs.name}/{dev_name}"
            else:
                dev_path = HWMON_PATH.format(
                    IOB_PCI_DRIVER, local, self.busid, devid, devid, self.addr[2:]
                )
                if local == "COME":
                    dev_path = CPU_TEMP
                if Path(dev_path).exists():
                    for dirs in Path(dev_path).iterdir():
                        dev_file = f"{dev_path}/{dirs.name}/{dev_name}"
                else:
                    return None

            with open(dev_file, "r") as f:
                sensor_data = f.read().strip()

            if self.coefficient:
                sensor_data = round(int(sensor_data) * float(self.coefficient), 3)

            return sensor_data
        return None

    def test_sensor_data(self):
        """
        Tests the sensor data against its thresholds.
        """
        raw_data = self.value_format(self.unit, self._read_sensor_data())
        if raw_data:
            return raw_data, self._compare_data(raw_data)
        # print(f"Invalid data for sensor: {raw_data}")
        return "NA", "NA"

    def _compare_data(self, raw_data):
        """
        Compares the sensor data against its thresholds.
        """
        try:
            data = float(raw_data)
        except ValueError:
            print(f"Invalid data format for sensor: {self.sysfs_link}")
            return None

        # Check if data is within the minimum and maximum thresholds
        if self.minval != "NA" and data < self.minval:
            return FAILED
        if self.maxval != "NA" and data > self.maxval:
            return FAILED

        # If no thresholds are violated, return PASS
        return PASS


def read_config_file(filename):
    """
    Reads sensor configuration from a CSV file.
    """
    sensors = []
    with open(filename, "r", newline="") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            sensors.append(
                Sensor(
                    sensor_name=row["Sensor rail name DVT"],
                    local=row["Device location"],
                    busid=row["Bus Num"],
                    addr=row["Address"].strip(),
                    sysfs_link=row["Software point"],
                    position=row["Sensor Position"],
                    coefficient=(row["Multiply"]),
                    unit=row["Sensor Unit"],
                    maxval=(
                        float(row["Max_Design"])
                        if any(char.isdigit() for char in row["Max_Design"])
                        else "NA"
                    ),
                    minval=(
                        float(row["Min_Design"])
                        if any(char.isdigit() for char in row["Min_Design"])
                        else "NA"
                    ),
                )
            )
    return sensors


def sensor_data(sensors):
    """
    Tests the sensors based on the provided configuration.
    """
    print(
        "--------------------+-------+-----+------+--------+---------+---------+------+-------\n"
        "  Sensor rail name  | Local | Bus | Addr |  Data  | Max val | Min val | Unit | Status\n"
        "--------------------+-------+-----+------+--------+---------+---------+------+-------"
    )

    for sensor in sensors:
        status = PASS
        data, status = sensor.test_sensor_data()
        if status:

            print(
                f'{"":2}{sensor.sensor_name[:17]:<18}{"|":<2}{sensor.local[:4]:<4}{"":>2}{"|":<2}'
                + f'{sensor.busid:<4}{"|":<2}{sensor.addr:<5}{"|":<2}'
                + f'{data:<7}{"|":<2}{str(sensor.maxval):<8}{"|":<2}'
                + f'{str(sensor.minval):<8}{"|":<2}{sensor.unit:<5}{"|":<2}{status:<5}'
            )
        print(
            "--------------------+-------+-----+------+--------+---------+---------+------+-------"
        )
    return status


def sensor_test(config_file="Minipack 3 sensors threshold list_20240719.csv"):
    """
    Main function to test sensors.
    """
    sensors = read_config_file(config_file)
    sensor_data(sensors)


if __name__ == "__main__":
    sensor_test()
