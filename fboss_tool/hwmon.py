import os

from fboss_utils import print_dict

class Hwmon():

    def __init__(self):
        self.master_path = '/sys/class/hwmon'
        self.attributes_list = ["_max", "_min", "_crit", "_lcrit"]

    def value_format(self, attributes_file, value):

         # See https://www.kernel.org/doc/Documentation/hwmon/sysfs-interface
        if attributes_file.lower().startswith('in'):
            return str(round(int(value) / 1000 ,2)) + ' V'
        elif attributes_file.lower().startswith('fan'):
            return value + ' RPM'
        elif attributes_file.lower().startswith('pwm'):
            return str(round(int(value) / 255, 2)) + ' PWM (%)'
        elif attributes_file.lower().startswith('temp'):
            return str(round(int(value) / 1000, 2)) + ' C'
        elif attributes_file.lower().startswith('curr'):
            return str(round(int(value) / 1000, 2)) + ' A'
        elif attributes_file.lower().startswith('power'):
            return str(round(int(value) / 1000000, 2)) + ' W'
        elif attributes_file.lower().startswith('freq'):
            return str(round(int(value) / 1000000, 2)) + ' MHz'

    def read_data(self, data_path):
        """Reads data from a file."""
        with open(data_path, 'r') as file:
            return file.read().strip()

    def extract_data(self, sub_folder_path, file_):
        """Extracts data for a specific sensor attribute."""
        hwmon_data = [None for _ in range(5)]
        data = {}
        idx = 0
        file_key = file_.split('_')[0]

        if os.path.exists(os.path.join(sub_folder_path, file_key + '_label')):
            label_name = file_key + '_label'
            label_name = self.read_data(os.path.join(sub_folder_path, label_name))
            if '_input_' not in file_:
                value = self.read_data(os.path.join(sub_folder_path, file_))
        else:
            label_name = file_key
            value = self.read_data(os.path.join(sub_folder_path, file_))

        hwmon_data[idx] = self.value_format(file_, value)

        for file in self.attributes_list:
            idx += 1
            file_id = file_key + file

            if os.path.exists(os.path.join(sub_folder_path, file_id)):
                value = self.read_data(os.path.join(sub_folder_path, file_id))
                hwmon_data[idx] = self.value_format(file_id, value)

        data[label_name] = hwmon_data
        return data
    
    def data(self):
        """Collects and organizes sensor data."""
        data = {}

        for folder in os.listdir(self.master_path):
            sub_folder_path = os.path.join(self.master_path, folder)

            name_key = None
            if os.path.exists(os.path.join(sub_folder_path, 'name')):
                name_key = self.read_data(os.path.join(sub_folder_path, 'name'))

            symlink = os.readlink(os.path.join(sub_folder_path, 'device')).strip().split("/")[-1]
            sensor_name = f"{name_key}-{symlink}"
            data[sensor_name] = {}

            for file_ in os.listdir(sub_folder_path):
                if '_input' in file_ or '_average' in file_:
                    try:
                        hwmon_data = self.extract_data(sub_folder_path, file_)
                        data[sensor_name].update(hwmon_data)
                    except Exception:
                        pass

            # estimate_w = []

            # for sensor in data.keys():

            #     for value in data[sensor].keys():

            #         if data[sensor][value].endswith("V"):

            #             try:
            #                 v = float(data[sensor][value].split(" ")[0])
            #                 i = float(data[sensor]["I" + value[1:]].split(" ")[0])
            #                 estimate_w.append([sensor, "W" + value[1:] + "*", round(v*i,4)])
            #             except Exception:
            #                 pass

            # for value in estimate_w:
            #     data[value[0]][value[1]] = str(value[2]) + " w"

        return data

    def compare_element(self, list_data):
        """Compares elements in a list to check for status."""
        status = True
        if isinstance(list_data, list):
            for n in range(len(list_data)):
                if list_data[n]:
                    if n % 2 == 0:
                        if float(list_data[0].split(" ")[0]) < float(list_data[n].split(" ")[0]):
                            status = False
                    else:
                        if float(list_data[0].split(" ")[0]) > float(list_data[n].split(" ")[0]):
                            status = False
        return status

    def print_data_format(self):
        """Prints sensor data in a tabular format."""
        ret = "\033[1;32mPASS\033[00m"
        TABLE_FLAG = "-----------+"
        dictionary = self.data()
        print("+--------" + TABLE_FLAG * 7)
        if isinstance(dictionary, dict):
            for key in sorted(dictionary.keys()):
                indent = 1
                status = "\033[1;32mPASS\033[00m"
                print("|" + f"{key:^19}", end="")
                print("|   Value   | Max Value | Min Value | Crit Max  | Crit Min  |  Status   |")
                print("+--------" + TABLE_FLAG * 7)
                
                if isinstance(dictionary[key], dict):
                    for key_list in sorted(dictionary[key].keys()):
                        print("|", f"{key_list:^18}", end="")
                        for n in range(5):
                            if dictionary[key][key_list][n]:
                                print("|", f"{dictionary[key][key_list][n]:^10}", end="")
                            else:
                                print("|", "-".center(10), end="")

                        if not self.compare_element(dictionary[key][key_list]):
                            status = "\033[1;31mFAIL\033[0m"
                            ret = "\033[1;31mFAIL\033[0m"

                        print("|   ", status, "  |")

                    print("+--------" + TABLE_FLAG * 7)
        return ret
    
    def hwmon_test(self):
        """sensors hwmon functon"""
        print(
            "-------------------------------------------------------------------------\n"
            "                        |  system hwmon Test  |\n"
            "-------------------------------------------------------------------------"
        )
        return self.print_data_format()