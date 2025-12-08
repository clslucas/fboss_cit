import os
import sys

auxdev_path = "/sys/bus/auxiliary/devices/"

b = sys.argv[0]
print(b)  # get current path
print(sys.argv)

files = os.listdir(auxdev_path)
# list files current directory
fnum = len(files)
print(f"devices number: {fnum}")

for file in files:
    print(file)
