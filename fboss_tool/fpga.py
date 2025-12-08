# -*- coding: utf-8 -*-
import os
import re
import yaml
import mmap
import random
from typing import Tuple
import struct

from fboss_utils import execute_shell_cmd
import i2cbus

OFFSET_REVISION = 0x00000
OFFSET_REVISION_DOM1 = 0x40000

IOB_RESOURCE0 = ""

def _fetch_resourse0() -> str:
    status, stdout = execute_shell_cmd("lspci -nd 1d9b:0011")
    if not status:
        return None
    pcie_bdf = stdout.split()[0]
    return f"/sys/bus/pci/devices/0000:{pcie_bdf}/resource0"

IOB_RESOURCE0 = _fetch_resourse0()

def load_yaml_file() :
    yaml_file_name = "MP3_FPGA.yaml"

    with open(yaml_file_name , 'r', encoding='utf-8') as file :
        data = yaml.load(file, Loader=yaml.FullLoader)

    return data

def _iob_read(offset: int, length: int)  -> bytes:
    with open(IOB_RESOURCE0, "r+b") as fpga_fd, mmap.mmap(
        fpga_fd.fileno(), 0
    ) as mm_fpga:
        mm_fpga.seek(offset)
        return mm_fpga.read(length)

def verify_fpag_data():
    data = load_yaml_file()
    fpga_number = data["FPGA"]['FPAG_NUMBER']
    for i in range(1, fpga_number + 1):
        fpga_read_write = data["FPGA"]['fpga_read_write_{}'.format(i)]
        fpga_start_bit = data["FPGA"]['fpga_start_bit_{}'.format(i)]
        fpga_length = 4
        fpga_value_1 = data["FPGA"]['fpga_value1_{}'.format(i)]
        fpga_value_2 = data["FPGA"]['fpga_value2_{}'.format(i)]
        fpga_value_3 = data["FPGA"]['fpga_value3_{}'.format(i)]
        fpga_value_4 = data["FPGA"]['fpga_value4_{}'.format(i)]

        if fpga_read_write == "read" or fpga_read_write == "READ":
            value_1, value_2, value_3, value_4 = _iob_read(fpga_start_bit, fpga_length)
            if value_1 != fpga_value_1 or value_2 != fpga_value_2 or value_3 != fpga_value_3 or value_4 != fpga_value_4:
                print(f"Check data \033[0;31;40m error \033[0m: fpga_read_offset = {fpga_start_bit:#8x}, fpga_length = {fpga_length}, fpga_value = {fpga_value_1:#4x}, {fpga_value_2:#4x}, {fpga_value_3:#4x}, {fpga_value_4:#4x}, get data = {value_1:#4x}, {value_2:#4x}, {value_3:#4x}, {value_4:#4x}")
                continue
        
            print(f"Check data success: fpga_read_offset = {fpga_start_bit:#8x}, fpga_length = {fpga_length}, fpga_value = {fpga_value_1:#4x}, {fpga_value_2:#4x}, {fpga_value_3:#4x}, {fpga_value_4:#4x}, get data = {value_1:#4x}, {value_2:#4x}, {value_3:#4x}, {value_4:#4x}")


if __name__ == "__main__":
    verify_fpag_data()

    exit()