#!/usr/bin/env python3

import getpass
import os # Added for path manipulation and directory creation
from functools import wraps
import sys
import json # Added for loading external configuration
from remote_client import RemoteClient
import re
from utils import Colors

# --- Configuration ---
BUS_DEFAULT = 10
ADDR_DEFAULT = 0x23

CONFIG_FILE = "config.json"

def test_wrapper(title):
    """A decorator to wrap test functions with a consistent header and footer."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            print(f"\n{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
            print(f"{Colors.YELLOW}  START: {title}{Colors.NC}")
            print(f"{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
            
            func(self, *args, **kwargs)
            
            print(f"\n{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
            print(f"{Colors.YELLOW}  END: {title}{Colors.NC}")
            print(f"{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
        return wrapper
    return decorator

def load_configuration():
    """Loads configuration from config.json, creating it with defaults if it doesn't exist."""
    # New structure with profiles, including a list for TH6 devices
    default_profile_data = {
        "rmc_ip": "192.168.1.103",
        "w400_ip": "192.168.1.121",
        "username": "root",
        "password": "0penBmc",
        "w400_x86_ip": "fe80::ff:fe00:2%usb0",
        "w400_x86_username": "root",
        "w400_x86_password": "11",
        "th6_devices": [
            {"ip": "192.168.1.191", "username": "root", "password": "11"},
            {"ip": "192.168.1.206", "username": "root", "password": "11"},
            {"ip": "192.168.1.123", "username": "root", "password": "11"},
            {"ip": "192.168.1.216", "username": "root", "password": "11"},
            {"ip": "192.168.1.221", "username": "root", "password": "11"},
            {"ip": "192.168.1.131", "username": "root", "password": "11"},
            {"ip": "192.168.1.190", "username": "root", "password": "11"},
            {"ip": "192.168.1.156", "username": "root", "password": "11"},
            {"ip": "192.168.1.215", "username": "root", "password": "11"},
            {"ip": "192.168.1.166", "username": "root", "password": "11"},
            {"ip": "192.168.1.232", "username": "root", "password": "11"},
            {"ip": "192.168.1.208", "username": "root", "password": "11"}
        ] # Default 12 TH6 devices
    }
    # Ensure default TH6 IPs are unique and within a reasonable range for example
    for i, th6 in enumerate(default_profile_data["th6_devices"]):
        th6["ip"] = f"192.168.1.{100 + i}" # Example IPs for TH6-1 to TH6-12
    default_config_structure = {
        "active_profile": "default",
        "profiles": {
            "default": default_profile_data
        },
        "default_log_dir": "logs"
    }

    if not os.path.exists(CONFIG_FILE):
        print(f"{Colors.YELLOW}Configuration file '{CONFIG_FILE}' not found. Creating with default values.{Colors.NC}")
        save_configuration(default_config_structure)
        return default_config_structure

    try:
        with open(CONFIG_FILE, 'r') as f:
            # Read the file and remove comments and trailing commas for more robust parsing
            content = f.read()
            # Remove single-line comments
            content = re.sub(r"//.*", "", content)
            # Remove trailing commas from objects and arrays
            content = re.sub(r",\s*([}\]])", r"\1", content)
            
            config = json.loads(content)

            # --- Migration logic for old config format ---
            if "profiles" not in config:
                print(f"{Colors.YELLOW}Old configuration format detected. Migrating to new profile structure...{Colors.NC}")
                migrated_profile = {
                    "rmc_ip": config.get("default_rmc_ip", default_profile_data["rmc_ip"]),
                    "w400_ip": config.get("default_w400_ip", default_profile_data["w400_ip"]),
                    "username": config.get("default_username", default_profile_data["username"]),
                    "password": config.get("configured_password", default_profile_data["password"]),
                    "w400_x86_ip": config.get("w400_x86_ip", default_profile_data["w400_x86_ip"]),
                    "w400_x86_username": config.get("w400_x86_username", default_profile_data["w400_x86_username"]),
                    "w400_x86_password": config.get("w400_x86_password", default_profile_data["w400_x86_password"]),
                    # Migrate TH6 devices if they existed in some other form, or use default
                    "th6_devices": config.get("th6_devices", default_profile_data["th6_devices"])
                }
                # Ensure all keys are present in the migrated profile
                for key, value in default_profile_data.items():
                    migrated_profile.setdefault(key, value)
                config = {
                    "active_profile": "default",
                    "profiles": {"default": migrated_profile},
                    "default_log_dir": config.get("default_log_dir", "logs")
                }
                save_configuration(config)
                print(f"{Colors.GREEN}Migration complete. Configuration saved.{Colors.NC}")

            return config
    except (json.JSONDecodeError, IOError) as e:
        print(f"{Colors.RED}Error reading '{CONFIG_FILE}': {e}. Using default values.{Colors.NC}")
        return default_config_structure

def save_configuration(config):
    """Saves the configuration object to config.json."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

class Diagnostics:
    """Container for all diagnostic test functions."""

    def __init__(self, rmc_client, w400_client, w400_x86_client=None, th6_clients=None):
        self.rmc = rmc_client
        self.w400 = w400_client
        self.w400_x86 = w400_x86_client
        self.th6_clients = th6_clients if th6_clients is not None else []

    # --- RMC Specific Functions ---
    @test_wrapper("Running RMC Status Check")
    def run_rmc_status_check(self):
        remote_script_path = "/home/root/rmc_status_check.sh"
        print(f"Executing script on remote host: {remote_script_path}")
        cmd = f"chmod +x {remote_script_path} && {remote_script_path} {BUS_DEFAULT} {ADDR_DEFAULT}"
        self.rmc.run_command(cmd)

    @test_wrapper("Checking AALC LC GPIO Cable Detect (RMC)")
    def check_aal_gpio_cable(self):
        output, exit_code = self.rmc.run_command(f"i2cget -y {BUS_DEFAULT} 0x{ADDR_DEFAULT:x} 0x13")
        if exit_code != 0 or not output.strip():
            print(f"{Colors.RED}Could not read AALC GPIO status.{Colors.NC}")
            return

        try:
            value = int(output.strip(), 16)
            # Low active: a bit value of 0 means PRESENT
            statuses = {
                "AALC1 presence": ((value >> 3) & 1) == 0,
                "AALC1 presence spare": ((value >> 2) & 1) == 0,
                "AALC2 presence": ((value >> 1) & 1) == 0,
                "AALC2 presence spare": (value & 1) == 0,
            }
            print("\n--- Parsed Status ---")
            for name, is_present in statuses.items():
                color = Colors.GREEN if is_present else Colors.RED
                status_text = "PRESENT" if is_present else "NOT PRESENT"
                print(f"{name}: {color}{status_text}{Colors.NC}")
        except (ValueError, IndexError):
            print(f"{Colors.RED}Failed to parse the hexadecimal output: '{output.strip()}'{Colors.NC}")

    @test_wrapper("Checking AALC RPU Ready Status (RMC)")
    def check_aal_rpu_ready(self):
        output, exit_code = self.rmc.run_command(f"i2cget -y {BUS_DEFAULT} 0x{ADDR_DEFAULT:x} 0x00")
        if exit_code != 0 or not output.strip():
            print(f"{Colors.RED}Could not read AALC RPU status.{Colors.NC}")
            return

        try:
            value = int(output.strip(), 16)
            statuses = {
                "AALC1 RPU READY": (value >> 7) & 1,
                "AALC1 PRU READY SPARE": (value >> 6) & 1,
                "AALC2 RPU READY": (value >> 5) & 1,
                "AALC2 PRU READY SPARE": (value >> 4) & 1,
            }
            print("\n--- Parsed Status ---")
            for name, status in statuses.items():
                color = Colors.GREEN if status == 1 else Colors.RED
                status_text = "READY" if status == 1 else "NOT READY"
                print(f"{name}: {color}{status_text}{Colors.NC}")
        except (ValueError, IndexError):
            print(f"{Colors.RED}Failed to parse the hexadecimal output: '{output.strip()}'{Colors.NC}")

    @test_wrapper("Checking RMC Software & Firmware Versions")
    def check_rmc_version(self):
        self.rmc.run_command("mfg-tool version-display")

    @test_wrapper("Checking TH6 LC Cable Detect (RMC)")
    def check_th6_lc_cable(self):
        statuses = {}
        # Register 0x10 for Trays 1-7
        output_10, code_10 = self.rmc.run_command("i2cget -f -y 10 0x23 0x10")
        if code_10 == 0 and output_10.strip():
            try:
                val = int(output_10.strip(), 16)
                # Bits 6 down to 0 for Trays 1-7
                for i in range(7):
                    statuses[f"Tray {i+1}"] = ((val >> (6 - i)) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}Failed to parse register 0x10 output: '{output_10.strip()}'{Colors.NC}")

        # Register 0x11 for Trays 8-10
        output_11, code_11 = self.rmc.run_command("i2cget -f -y 10 0x23 0x11")
        if code_11 == 0 and output_11.strip():
            try:
                val = int(output_11.strip(), 16)
                statuses["Tray 8"] = ((val >> 7) & 1) == 0
                statuses["Tray 9"] = ((val >> 6) & 1) == 0
                statuses["Tray 10"] = ((val >> 5) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}Failed to parse register 0x11 output: '{output_11.strip()}'{Colors.NC}")

        # Register 0x12 for Trays 11-12
        output_12, code_12 = self.rmc.run_command("i2cget -f -y 10 0x23 0x12")
        if code_12 == 0 and output_12.strip():
            try:
                val = int(output_12.strip(), 16)
                statuses["Tray 11"] = ((val >> 4) & 1) == 0
                statuses["Tray 12"] = ((val >> 3) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}Failed to parse register 0x12 output: '{output_12.strip()}'{Colors.NC}")

        print("\n--- Parsed Tray Presence Status (Low active = PRESENT) ---")
        for i in range(1, 13):
            name = f"Tray {i}"
            is_present = statuses.get(name, False) # Default to NOT PRESENT if key is missing
            color = Colors.GREEN if is_present else Colors.RED
            status_text = "PRESENT" if is_present else "NOT PRESENT"
            print(f"{name}: {color}{status_text}{Colors.NC}")

    @test_wrapper("Checking Drip Pan Leak Sensor Presence (RMC)")
    def check_drip_pan_leak_sensor(self):
        statuses = {}
        # Register 0x14 for sensors 0, 1
        output_14, code_14 = self.rmc.run_command("i2cget -y 10 0x23 0x14")
        if code_14 == 0 and output_14.strip():
            try:
                val = int(output_14.strip(), 16)
                statuses["Leak Sensor 0"] = ((val >> 1) & 1) == 0
                statuses["Leak Sensor 1"] = (val & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}Failed to parse register 0x14 output: '{output_14.strip()}'{Colors.NC}")

        # Register 0x15 for sensor 2
        output_15, code_15 = self.rmc.run_command("i2cget -y 10 0x23 0x15")
        if code_15 == 0 and output_15.strip():
            try:
                val = int(output_15.strip(), 16)
                statuses["Leak Sensor 2"] = ((val >> 7) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}Failed to parse register 0x15 output: '{output_15.strip()}'{Colors.NC}")

        # Register 0x16 for sensors 3, 4
        output_16, code_16 = self.rmc.run_command("i2cget -y 10 0x23 0x16")
        if code_16 == 0 and output_16.strip():
            try:
                val = int(output_16.strip(), 16)
                statuses["Leak Sensor 3"] = ((val >> 6) & 1) == 0
                statuses["Leak Sensor 4"] = ((val >> 5) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}Failed to parse register 0x16 output: '{output_16.strip()}'{Colors.NC}")

        print("\n--- Parsed Leak Sensor Presence Status (Low active = PRESENT) ---")
        for i in range(5):
            name = f"Leak Sensor {i}"
            is_present = statuses.get(name, False)
            color = Colors.GREEN if is_present else Colors.RED
            status_text = "PRESENT" if is_present else "NOT PRESENT"
            print(f"{name}: {color}{status_text}{Colors.NC}")

    @test_wrapper("Checking RMC FRU Information")
    def check_rmc_fru_info(self):
        self.rmc.run_command("mfg-tool inventory")

    @test_wrapper("Checking RMC Sensor Status")
    def check_rmc_sensor_status(self):
        self.rmc.run_command("mfg-tool sensor-display")

    @test_wrapper("Checking RMC Boot Slot")
    def check_rmc_boot_slot(self):
        output, exit_code = self.rmc.run_command("cat /run/media/slot")
        if exit_code != 0 or not output.strip():
            print(f"{Colors.RED}Could not read RMC boot slot status.{Colors.NC}")
            return

        try:
            slot_str = output.strip()
            print("\n--- Parsed Boot Slot Status ---")
            if slot_str == "0":
                print(f"Boot Slot: {Colors.GREEN}0 (Primary){Colors.NC}")
            elif slot_str == "1":
                print(f"Boot Slot: {Colors.GREEN}1 (Alternate){Colors.NC}")
            else:
                print(f"{Colors.YELLOW}Unknown Boot Slot: {slot_str}{Colors.NC}")
        except Exception:
            print(f"{Colors.RED}Failed to parse boot slot output: '{output.strip()}'{Colors.NC}")

    # --- W400 Specific Functions ---
    @test_wrapper("Checking PSU Shelf Ishare Cable Status (W400)")
    def check_psu_ishare_cable(self):
        for addr in [32, 33]:
            print(f"{Colors.YELLOW}Checking dev-addr {addr}:{Colors.NC}")
            self.w400.run_command(f"rackmoncli data --dev-addr {addr} --latest | grep -i ISHARE_Cable_Connected")

    @test_wrapper("Checking BBU Shelf Ishare Cable Status (W400)")
    def check_bbu_ishare_cable(self):
        for addr in [16, 17]:
            print(f"{Colors.YELLOW}Checking dev-addr {addr}:{Colors.NC}")
            self.w400.run_command(f"rackmoncli data --dev-addr {addr} --latest | grep -i ISHARE_Cable_Connected")

    @test_wrapper("Checking Power Source Detect (W400)")
    def check_power_source(self):
        self.w400.run_command("rackmoncli list")

    @test_wrapper("Checking Power AC Loss Cable Detect (W400)")
    def check_power_ac_loss(self):
        for addr in list(range(48, 54)) + list(range(58, 64)):
            print(f"{Colors.YELLOW}Checking dev-addr {addr}:{Colors.NC}")
            self.w400.run_command(f"rackmoncli data --dev-addr {addr} --latest | grep -i AC_Loss_")

    @test_wrapper("Checking Power Shelf Version (W400)")
    def check_power_shelf_version(self):
        for addr in [16, 17, 32, 33]:
            print(f"{Colors.YELLOW}Checking dev-addr {addr}:{Colors.NC}")
            self.w400.run_command(f"rackmoncli data --dev-addr {addr} --latest | grep PMM_FW_Revision")

    @test_wrapper("Checking PSU and BBU Versions (W400)")
    def check_psu_bbu_versions(self):
        addrs = list(range(48, 54)) + list(range(58, 64)) + list(range(144, 150)) + list(range(154, 160))
        for addr in addrs:
            print(f"{Colors.YELLOW}Checking dev-addr {addr}:{Colors.NC}")
            self.w400.run_command(f"rackmoncli data --dev-addr {addr} --latest | grep FW_Revision")

    @test_wrapper("Checking Power FRU Info (W400)")
    def check_power_fru_info(self):
        addrs = [16, 17, 32, 33] + list(range(144, 150)) + list(range(154, 160))
        for addr in addrs:
            print(f"{Colors.YELLOW}Checking dev-addr {addr}:{Colors.NC}")
            self.w400.run_command(f"rackmoncli data --dev-addr {addr} --latest")

    @test_wrapper("Checking Wedge400 FRU Information")
    def check_w400_fru_info(self):
        self.w400.run_command("weutil; seutil; bsm-eutil; psu-util psu2 --get_eeprom_info")

    @test_wrapper("Checking ALLC Sensor Status (W400)")
    def check_allc_sensor_status(self):
        print(f"{Colors.YELLOW}Checking dev-addr 12 for ALLC sensor status:{Colors.NC}")
        cmd = "rackmoncli data --dev-addr 12 | grep -E 'TACH_RPM|temp|Hum_Pct_RH|HSC_P48V|Alarm'"
        self.w400.run_command(cmd)

    @test_wrapper("Checking AALC Leakage Sensor Status (W400)")
    def check_aalc_leakage_sensor_status(self):
        print(f"{Colors.YELLOW}Checking dev-addr 12 for AALC Leakage sensor status:{Colors.NC}")
        self.w400.run_command("rackmoncli read 12 0x9202")

    # --- W400 x86 Specific Functions ---
    @test_wrapper("Checking x86 CPU and Memory Info (W400 x86)")
    def check_x86_resources(self):
        self.w400_x86.run_command("lscpu | grep 'Model name'; free -h")

    @test_wrapper("Checking Wedge400 x86 SW/FW Versions")
    def check_w400_x86_versions(self):
        cmd = """
            echo '--- Common Versions ---';
            (cd /usr/local/cls_diag/rack/ && ./cls_version);
            (cd /usr/local/cls_diag/bin && ./cel-version-test --show);
            echo '--- SSD Version ---';
            (cd /usr/local/cls_diag/bin/ && ./cel-nvme-test -i | grep 'Version');
            echo '--- SDK Version ---';
            (cd /usr/local/cls_diag/SDK/ && cat Version);
        """
        self.w400_x86.run_command(cmd)

    @test_wrapper("Checking Wedge400 Sensor Status (W400 x86)")
    def check_w400_sensor_status(self):
        self.w400.run_command("cd /mnt/data1/BMC_Diag/bin && ./cel-sensor-test -s")

    # --- TH6 Specific Functions (Direct SSH) ---
    @test_wrapper("Checking TH6 Uptime")
    def check_th6_uptime(self):
        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Checking Uptime on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            th6_client.run_command("uptime")

    @test_wrapper("Checking TH6 Disk Usage")
    def check_th6_disk_usage(self):
        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Checking Disk Usage on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            th6_client.run_command("df -h")

    @test_wrapper("Checking TH6 1.6T Optical Module Version)")
    def check_th6_optical_module_version(self):
        self.rmc.run_command("unidiag_cli osfp prbs get 3")

    @test_wrapper("Checking TH6 Transceiver Reset Signal Status")
    def check_th6_xcvr_reset_status(self):
        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Checking Reset Status on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            command = "for f in /sys/bus/auxiliary/devices/fboss_iob_pci.xcvr_ctrl.*/xcvr_reset_*; do echo \"$f:$(cat $f)\"; done"
            output, exit_code = th6_client.run_command(command, print_output=False)

            if exit_code == 0 and output.strip():
                for line in output.strip().splitlines():
                    try:
                        path, value = line.split(':', 1)
                        raw_value = value.strip()
                        if raw_value == '0x0':
                            status_text = f"{Colors.GREEN}Release{Colors.NC}"
                        elif raw_value == '0x1':
                            status_text = f"{Colors.YELLOW}Reset{Colors.NC}"
                        else:
                            status_text = f"{Colors.RED}Unknown{Colors.NC}"
                        print(f"{path.strip()}: {raw_value} ({status_text})")
                    except ValueError:
                        continue # Ignore lines that don't parse correctly

    @test_wrapper("Checking TH6 OM Low Power Status")
    def check_th6_om_low_power_status(self):
        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Checking Low Power Status on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            command = "for f in /sys/bus/auxiliary/devices/fboss_iob_pci.xcvr_ctrl.*/xcvr_low_power_*; do echo \"$f:$(cat $f)\"; done"
            output, exit_code = th6_client.run_command(command, print_output=False)

            if exit_code == 0 and output.strip():
                for line in output.strip().splitlines():
                    try:
                        path, value = line.split(':', 1)
                        raw_value = value.strip()
                        if raw_value == '0x0':
                            status_text = f"{Colors.GREEN}High Power Mode{Colors.NC}"
                        elif raw_value == '0x1':
                            status_text = f"{Colors.YELLOW}Low Power Mode{Colors.NC}"
                        else:
                            status_text = f"{Colors.RED}Unknown{Colors.NC}"
                        print(f"{path.strip()}: {raw_value} ({status_text})")
                    except ValueError:
                        continue # Ignore lines that don't parse correctly

    @test_wrapper("Set TH6 Transceivers Reset Mode")
    def set_th6_xcvr_reset_mode(self):
        while True:
            mode_choice = input("Enter reset mode ('reset' to assert, 'release' to deassert): ").lower()
            if mode_choice == 'reset':
                value = 1
                break
            elif mode_choice == 'release':
                value = 0
                break
            else:
                print(f"{Colors.RED}Invalid choice. Please enter 'reset' or 'release'.{Colors.NC}")

        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Setting Reset Mode to '{mode_choice}' on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            command = f"for f in /sys/bus/auxiliary/devices/fboss_iob_pci.xcvr_ctrl.*/xcvr_reset_*; do echo {value} > \"$f\" && echo \"Set $f to {value}\"; done"
            th6_client.run_command(command)

    @test_wrapper("Set TH6 Transceivers Low Power Mode")
    def set_th6_xcvr_low_power_mode(self):
        while True:
            mode_choice = input("Enter low power mode ('low' to assert, 'high' to deassert): ").lower()
            if mode_choice == 'low':
                value = 1
                break
            elif mode_choice == 'high':
                value = 0
                break
            else:
                print(f"{Colors.RED}Invalid choice. Please enter 'low' or 'high ' power.{Colors.NC}")

        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Setting Low Power Mode to '{mode_choice}' on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            command = f"for f in /sys/bus/auxiliary/devices/fboss_iob_pci.xcvr_ctrl.*/xcvr_low_power_*; do echo {value} > \"$f\" && echo \"Set $f to {value}\"; done"
            th6_client.run_command(command)

    @test_wrapper("Checking Total PSU Output Power (W400)")
    def check_psu_output_power(self):
        psu_addrs = list(range(144, 150)) + list(range(154, 160))
        total_power = 0.0
        
        print("Running initial rescan...")
        self.w400.run_command("rackmoncli rescan", print_output=False)

        for addr in psu_addrs:
            print(f"Querying PSU at address {addr} for Output Power...")
            # Use a more specific grep to avoid matching _Inst or other variants
            command = f"rackmoncli data --dev-addr {addr} | grep -w PSU_Output_Power"
            output, exit_code = self.w400.run_command(command, print_output=False)
            if exit_code == 0 and output.strip():
                try:
                    for line in output.strip().splitlines():
                        if 'PSU_Output_Power' in line and 'Inst' not in line:
                            power_str = line.split(':')[1].strip()
                            power_value = float(power_str)
                            total_power += power_value
                            print(f"  -> Found: {power_value:.3f} Watts")
                            break # Found the correct line
                except (ValueError, IndexError):
                    print(f"{Colors.RED}  -> Could not parse power value from: {output.strip()}{Colors.NC}")
        
        print(f"\n{Colors.GREEN}Total PSU Output Power: {total_power:.3f} Watts{Colors.NC}")

    @test_wrapper("Checking Total PSU Input Power (W400)")
    def check_psu_input_power(self):
        psu_addrs = list(range(144, 150)) + list(range(154, 160))
        total_power = 0.0

        print("Running initial rescan...")
        self.w400.run_command("rackmoncli rescan", print_output=False)

        for addr in psu_addrs:
            print(f"Querying PSU at address {addr} for Input Power...")
            # Use a more specific grep to avoid matching _Inst or other variants
            command = f"rackmoncli data --dev-addr {addr} | grep -w PSU_Input_Power"
            output, exit_code = self.w400.run_command(command, print_output=True) # Print output for this one
            if exit_code == 0 and output.strip():
                try:
                    for line in output.strip().splitlines():
                        if 'PSU_Input_Power' in line and 'Inst' not in line:
                            power_str = line.split(':')[1].strip()
                            power_value = float(power_str)
                            total_power += power_value
                            break # Found the correct line
                except (ValueError, IndexError):
                    # The value is printed by run_command, so we just note the parsing failure
                    print(f"{Colors.RED}  -> Could not parse power value from line above.{Colors.NC}")

        print(f"\n{Colors.GREEN}Total PSU Input Power: {total_power:.3f} Watts{Colors.NC}")

    @test_wrapper("Checking TH6 Fan PWM Values")
    def check_fan_pwm_values(self):
        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Checking Fan PWM Values on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            command = "for f in /sys/class/hwmon/hwmon*/pwm[1-4]; do val=$(cat \"$f\"); percent=$(awk -v v=\"$val\" 'BEGIN { printf \"%.0f\", (v / 64) * 100 }'); echo \"$f: $val ($percent%)\"; done"
            th6_client.run_command(command)

    @test_wrapper("Set TH6 Fan PWM Value")
    def set_fan_pwm_value(self):
        # Get PWM channel from user
        while True:
            channel_choice = input("Enter PWM channel to set (1-4, or 'all'): ").lower()
            if channel_choice == 'all' or (channel_choice.isdigit() and 1 <= int(channel_choice) <= 4):
                break
            else:
                print(f"{Colors.RED}Invalid input. Please enter a number from 1-4 or 'all'.{Colors.NC}")

        # Get PWM value from user
        while True:
            try:
                pwm_value = int(input("Enter PWM value to set (0-64): "))
                if 0 <= pwm_value <= 64:
                    break
                else:
                    print(f"{Colors.RED}Invalid value. Please enter a number between 0 and 64.{Colors.NC}")
            except ValueError:
                print(f"{Colors.RED}Invalid input. Please enter a number.{Colors.NC}")

        target_glob = "pwm[1-4]" if channel_choice == 'all' else f"pwm{channel_choice}"
        command = f"for f in /sys/class/hwmon/hwmon*/{target_glob}; do echo {pwm_value} > \"$f\" && echo \"Set $f to {pwm_value}\"; done"

        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Setting Fan PWM on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            th6_client.run_command(command)

    @test_wrapper("Checking TH6 Fan Speed (RPM)")
    def check_fan_speed_rpm(self):
        for i, th6_client in enumerate(self.th6_clients, 1):
            print(f"\n{Colors.CYAN}--- Checking Fan Speed (RPM) on TH6-{i} ({th6_client.hostname}) ---{Colors.NC}")
            command = "for f in /sys/class/hwmon/hwmon*/fan*_input; do echo -n \"$f: \"; cat \"$f\"; done"
            th6_client.run_command(command)

    # --- One-Key Block Test Functions ---
    def run_all_rmc_tests(self):
        print(f"\n{Colors.BLUE}======================================={Colors.NC}")
        print(f"{Colors.BLUE}    Running All RMC Diagnostic Tests   {Colors.NC}")
        print(f"{Colors.BLUE}======================================={Colors.NC}")
        self.run_rmc_status_check()
        self.check_aal_rpu_ready()
        self.check_aal_gpio_cable()
        self.check_th6_lc_cable()
        self.check_drip_pan_leak_sensor()
        self.check_rmc_version()
        self.check_rmc_fru_info()
        self.check_rmc_sensor_status()
        self.check_rmc_boot_slot()
        print(f"\n{Colors.GREEN}All RMC tests complete.{Colors.NC}")

    def run_all_th6_tests(self):
        print(f"\n{Colors.BLUE}======================================={Colors.NC}")
        print(f"{Colors.BLUE}    Running All TH6 Diagnostic Tests   {Colors.NC}")
        print(f"{Colors.BLUE}======================================={Colors.NC}")
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return
        for i, th6_client in enumerate(self.th6_clients):
            print(f"\n{Colors.CYAN}--- Running tests on TH6-{i+1} ({th6_client.hostname}) ---{Colors.NC}")
            self.check_th6_uptime()
            self.check_th6_disk_usage()
            self.check_th6_xcvr_reset_status()
            self.check_th6_om_low_power_status()
            # Note: set functions are interactive and not typically run in "all" tests
            self.check_fan_pwm_values()
            self.check_fan_speed_rpm()
            # The optical module version is RMC-side, not TH6-side
            self.check_th6_optical_module_version()
        print(f"\n{Colors.GREEN}All TH6 tests complete.{Colors.NC}")

    def run_all_w400_tests(self):
        print(f"\n{Colors.BLUE}======================================={Colors.NC}")
        print(f"{Colors.BLUE}   Running All W400 Diagnostic Tests   {Colors.NC}")
        print(f"{Colors.BLUE}======================================={Colors.NC}")
        self.check_power_source()
        self.check_psu_ishare_cable()
        self.check_bbu_ishare_cable()
        self.check_power_ac_loss()
        self.check_power_shelf_version()
        self.check_psu_bbu_versions()
        self.check_power_fru_info()
        self.check_allc_sensor_status()
        self.check_w400_fru_info()
        self.check_aalc_leakage_sensor_status()
        self.check_w400_sensor_status()
        print(f"\n{Colors.GREEN}All W400 tests complete.{Colors.NC}")

    def run_all_w400_x86_tests(self):
        print(f"\n{Colors.BLUE}======================================={Colors.NC}")
        print(f"{Colors.BLUE}  Running All W400 x86 Diagnostic Tests  {Colors.NC}")
        print(f"{Colors.BLUE}======================================={Colors.NC}")
        self.check_x86_resources()
        self.check_w400_x86_versions()
        print(f"\n{Colors.GREEN}All W400 x86 tests complete.{Colors.NC}")


class Menu:
    """Handles the user-facing menu system."""

    def __init__(self, diag, rmc_ip, w400_ip, user, w400_x86_ip=None, w400_x86_user=None, th6_clients=None):
        self.diag = diag
        self.rmc_ip = rmc_ip
        self.w400_ip = w400_ip
        self.user = user
        self.w400_x86_ip = w400_x86_ip
        self.w400_x86_user = w400_x86_user
        self.th6_clients = th6_clients if th6_clients is not None else []

        self.rmc_menu_items = [
            ("Run Full RMC Status Check", self.diag.run_rmc_status_check),
            ("Check AALC RPU Ready Status", self.diag.check_aal_rpu_ready),
            ("Check AALC LC GPIO Cable Detect", self.diag.check_aal_gpio_cable),
            ("Check TH6 LC Cable Detect", self.diag.check_th6_lc_cable),
            ("Check Drip Pan Leak Sensor Presence", self.diag.check_drip_pan_leak_sensor),
            ("Check RMC SW/FW Versions", self.diag.check_rmc_version),
            ("Check RMC FRU Information", self.diag.check_rmc_fru_info),
            ("Check RMC Sensor Status", self.diag.check_rmc_sensor_status),
            ("Check RMC Boot Slot", self.diag.check_rmc_boot_slot),
        ]
        self.w400_menu_items = [
            ("Power Source Detect", self.diag.check_power_source),
            ("Check PSU Shelf Ishare Cable Status", self.diag.check_psu_ishare_cable),
            ("Check BBU Shelf Ishare Cable Status", self.diag.check_bbu_ishare_cable),
            ("Check Power AC Loss Cable Detect", self.diag.check_power_ac_loss),
            ("Check Power Shelf Version", self.diag.check_power_shelf_version),
            ("Check PSU and BBU Versions", self.diag.check_psu_bbu_versions),
            ("Check Power FRU Info", self.diag.check_power_fru_info),
            ("Check ALLC Sensor Status", self.diag.check_allc_sensor_status),
            ("Check W400 FRU Information", self.diag.check_w400_fru_info),
            ("Check AALC Leakage Sensor Status", self.diag.check_aalc_leakage_sensor_status),
            ("Check Total PSU Output Power", self.diag.check_psu_output_power),
            ("Check Total PSU Input Power", self.diag.check_psu_input_power),
        ]
        self.w400_x86_menu_items = [
            ("Check CPU and Memory Info", self.diag.check_x86_resources),
            ("Check W400 x86 SW/FW Versions", self.diag.check_w400_x86_versions),
        ]
        self.th6_menu_items = [
            ("Check Uptime", self.diag.check_th6_uptime),
            ("Check Disk Usage", self.diag.check_th6_disk_usage),
            ("Check Transceiver Reset Status", self.diag.check_th6_xcvr_reset_status),
            ("Check Transceiver Low Power Status", self.diag.check_th6_om_low_power_status),
            ("Set Transceivers Reset Mode", self.diag.set_th6_xcvr_reset_mode),
            ("Set Transceivers Low Power Mode", self.diag.set_th6_xcvr_low_power_mode),
            ("Check 1.6T Optical Module Version", self.diag.check_th6_optical_module_version),
            ("Check Fan PWM Values", self.diag.check_fan_pwm_values),
            ("Set Fan PWM Value", self.diag.set_fan_pwm_value),
            ("Check Fan Speed (RPM)", self.diag.check_fan_speed_rpm),
        ]

    def _show_menu(self, title, menu_items):
        while True:
            print(f"\n{Colors.BLUE}======================================={Colors.NC}")
            print(f"{Colors.BLUE}        {title.center(30)}{Colors.NC}")
            print(f"{Colors.BLUE}======================================={Colors.NC}")
            for i, (text, _) in enumerate(menu_items, 1):
                print(f"{i}. {text}")
            back_option = len(menu_items) + 1
            print(f"{back_option}. Back to Main Menu")
            print(f"{Colors.BLUE}---------------------------------------{Colors.NC}")

            choice = input("Enter your choice: ")
            try:
                choice_idx = int(choice)
                if 1 <= choice_idx <= len(menu_items):
                    print()
                    menu_items[choice_idx - 1][1]() # Execute the function
                    input(f"\n{Colors.YELLOW}Press Enter to continue...{Colors.NC}")
                elif choice_idx == back_option:
                    return
                else:
                    print(f"{Colors.RED}Invalid option. Please try again.{Colors.NC}")
            except ValueError:
                print(f"{Colors.RED}Invalid input. Please enter a number.{Colors.NC}")

    def rmc_menu(self):
        self._show_menu("RMC Diagnostics Menu", self.rmc_menu_items)

    def w400_menu(self):
        self._show_menu("Wedge400 Diagnostics Menu", self.w400_menu_items)

    def th6_menu(self):
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            input(f"\n{Colors.YELLOW}Press Enter to continue...{Colors.NC}")
            return

        self._show_menu("TH6 Diagnostics Menu", self.th6_menu_items)

    def w400_x86_menu(self):
        self._show_menu("Wedge400 x86 Diagnostics Menu", self.w400_x86_menu_items)

    def _run_custom_command(self):
        """Prompts the user for a target device and a command, then executes it."""
        target_client, target_name = self._select_target_device("Execute command on")
        if not target_client:
            return

        command_to_run = input(f"Enter the command to run on {target_name}: ").strip()
        if command_to_run:
            print(f"\n{Colors.YELLOW}Executing custom command on {target_name}: '{command_to_run}'{Colors.NC}")
            target_client.run_command(command_to_run)
        else:
            print(f"{Colors.RED}No command entered. Aborting.{Colors.NC}")

    def _upload_and_run_script(self):
        """Prompts user to upload a script and then execute it."""
        local_script_path = input("Enter the local path of the script to upload: ")
        if not os.path.isfile(local_script_path):
            print(f"{Colors.RED}Error: Local file '{local_script_path}' not found.{Colors.NC}")
            return

        target_client, target_name = self._select_target_device("Upload & execute on")
        if not target_client:
            return

        default_remote_path = f"/tmp/{os.path.basename(local_script_path)}"
        remote_script_path = input(f"Enter the remote destination path (default: {default_remote_path}): ") or default_remote_path

        # Upload the file
        if not target_client.upload_file(local_script_path, remote_script_path):
            print(f"{Colors.RED}Aborting execution due to upload failure.{Colors.NC}")
            return

        # Execute the script
        script_args = input("Enter any arguments for the script (optional): ")
        command_to_run = f"chmod +x {remote_script_path} && {remote_script_path} {script_args}"

        print(f"\n{Colors.YELLOW}Executing uploaded script on {target_name}: '{command_to_run}'{Colors.NC}")
        target_client.run_command(command_to_run)

    def find_ip_from_mac(self):
        """Finds a device's IP address from its MAC address using the arp command."""
        print(f"\n{Colors.BLUE}--- Find IP from MAC Address ---{Colors.NC}")
        scanner_client, scanner_name = self._select_target_device("Select a device to run 'arp' on")
        if not scanner_client:
            return

        mac_to_find = input("Enter the MAC address to find (e.g., 00:1a:2b:3c:4d:5e): ").lower().strip()
        if not mac_to_find:
            print(f"{Colors.RED}No MAC address entered. Aborting.{Colors.NC}")
            return

        print(f"\n{Colors.YELLOW}Searching for MAC {mac_to_find} using {scanner_name}...{Colors.NC}")
        output, exit_code = scanner_client.run_command("arp -n")

        found = False
        for line in output.splitlines():
            if mac_to_find in line.lower():
                ip_address = line.split()[0]
                print(f"{Colors.GREEN}Found matching device! IP Address: {ip_address}{Colors.NC}")
                found = True
                break
        
        if not found:
            print(f"{Colors.RED}Could not find a device with MAC address {mac_to_find} in the ARP table of {scanner_name}.{Colors.NC}")

    def _select_target_device(self, action_text):
        """
        Dynamically builds a menu of available targets and prompts the user for a selection.
        Returns the selected client object and its name, or (None, None) if invalid.
        """
        targets = {
            'r': (self.diag.rmc, "RMC"),
            'w': (self.diag.w400, "W400 BMC")
        }
        prompt_parts = ["(R)MC", "(W)400 BMC"]

        if self.diag.w400_x86:
            targets['x'] = (self.diag.w400_x86, "W400 x86")
            prompt_parts.append("(X)86")

        prompt = f"{action_text} {', '.join(prompt_parts)}? ({'/'.join(targets.keys())}): "

        # Dynamically add TH6 devices to the selection
        if self.diag.th6_clients:
            print("Or select a TH6 device:")
            for i, th6_client in enumerate(self.diag.th6_clients, 1):
                key = f"t{i}"
                targets[key] = (th6_client, f"TH6-{i} ({th6_client.hostname})")
                print(f"  ({key}) TH6-{i} ({th6_client.hostname})")

        while True:
            choice = input(prompt).lower()
            if choice in targets:
                return targets[choice]
            else:
                print(f"{Colors.RED}Invalid choice. Please try again.{Colors.NC}")

    def main_menu(self):
        main_menu_items = [
            ("Run All RMC Diagnostics (One-Key Test)", self.diag.run_all_rmc_tests),
            ("Run All W400 Diagnostics (One-Key Test)", self.diag.run_all_w400_tests),
            ("RMC Diagnostics (Individual Tests)", self.rmc_menu),
            ("Wedge400 BMC Diagnostics (Individual Tests)", self.w400_menu),
        ]
        if self.diag.w400_x86:
            main_menu_items.append(("Run All W400 x86 Diagnostics", self.diag.run_all_w400_x86_tests))
            main_menu_items.append(("Wedge400 x86 Diagnostics (Individual Tests)", self.w400_x86_menu))

        # Add a single entry for all TH6 devices
        if self.diag.th6_clients:
            main_menu_items.append(("TH6 Diagnostics (Individual Tests)", self.th6_menu))

        main_menu_items.append(("Run Custom Command", self._run_custom_command))
        main_menu_items.append(("Upload and Execute Script", self._upload_and_run_script))
        main_menu_items.append(("Find IP from MAC Address", self.find_ip_from_mac))

        while True:
            print(f"\n{Colors.BLUE}======================================={Colors.NC}")
            print(f"{Colors.BLUE}  Rack Diagnostics & Status Check Menu {Colors.NC}")
            print(f"  RMC Target:      {Colors.YELLOW}{self.user}@{self.rmc_ip}{Colors.NC}")
            print(f"  W400 BMC Target: {Colors.YELLOW}{self.user}@{self.w400_ip}{Colors.NC}")
            if self.diag.w400_x86:
                print(f"  W400 x86 Target: {Colors.YELLOW}{self.w400_x86_user}@{self.w400_x86_ip} (via BMC){Colors.NC}")
            if self.diag.th6_clients:
                # Display a summary of TH6 targets
                th6_ips = ", ".join([c.hostname for c in self.diag.th6_clients])
                print(f"  TH6 Targets:     {Colors.YELLOW}{th6_ips}{Colors.NC}")
            print(f"{Colors.BLUE}======================================={Colors.NC}")

            for i, (text, _) in enumerate(main_menu_items, 1):
                print(f"{i}. {text}")
            change_target_option = len(main_menu_items) + 1
            exit_option = len(main_menu_items) + 2
            print(f"{change_target_option}. Change Target Device")
            print(f"{exit_option}. Exit")
            print(f"{Colors.BLUE}---------------------------------------{Colors.NC}")

            choice = input("Enter your choice: ")
            try:
                choice_idx = int(choice)
                if 1 <= choice_idx <= len(main_menu_items):
                    print()
                    main_menu_items[choice_idx - 1][1]() # Execute the function
                    input(f"\n{Colors.YELLOW}Press Enter to continue...{Colors.NC}")
                elif choice_idx == change_target_option:
                    return "change_target"
                elif choice_idx == exit_option:
                    return "exit"
                else:
                    print(f"{Colors.RED}Invalid option. Please try again.{Colors.NC}")
            except ValueError:
                print(f"{Colors.RED}Invalid input. Please enter a number.{Colors.NC}")

def create_new_profile():
    """Gathers connection details from the user to create a new profile dictionary."""
    print(f"\n{Colors.BLUE}--- Create New Connection Profile ---{Colors.NC}")
    profile = {}
    profile['rmc_ip'] = input("Enter the RMC device IP address: ")
    profile['w400_ip'] = input("Enter the Wedge400 (W400) device IP address: ")
    profile['username'] = input("Enter the remote username (e.g., root): ")
    profile['w400_x86_ip'] = input("Enter the W400 x86 internal IP: ")
    profile['w400_x86_username'] = input("Enter the W400 x86 username: ")

    use_pass = input("Use password authentication for this profile? (y/n, default: n): ").lower()
    if use_pass == 'y':
        profile['password'] = getpass.getpass("Enter password for RMC/W400-BMC: ")
        profile['w400_x86_password'] = getpass.getpass("Enter password for W400-x86: ")
    else:
        profile['password'] = ""
        profile['w400_x86_password'] = ""

    profile['th6_devices'] = []
    print(f"\n{Colors.BLUE}--- TH6 Devices Configuration (up to 12 units) ---{Colors.NC}")
    for i in range(1, 13): # Allow up to 12 TH6 units
        th6_ip = input(f"Enter IP for TH6-{i} (leave blank to stop adding TH6s): ")
        if not th6_ip: break
        th6_username = input(f"Enter username for TH6-{i} (default: root): ") or "root"
        th6_password = getpass.getpass(f"Enter password for TH6-{i} (or blank for key-based): ") if use_pass == 'y' else ""
        profile['th6_devices'].append({"ip": th6_ip, "username": th6_username, "password": th6_password})
    return profile

def delete_profile(config):
    """Handles the deletion of a saved connection profile."""
    profiles = config.get("profiles", {})
    if not profiles:
        print(f"{Colors.YELLOW}No profiles to delete.{Colors.NC}")
        return

    print(f"\n{Colors.BLUE}--- Delete a Profile ---{Colors.NC}")
    print("Available profiles to delete:")
    for name in profiles:
        print(f"  - {name}")

    profile_to_delete = input("Enter the name of the profile to delete (or press Enter to cancel): ").lower()

    if not profile_to_delete:
        print("Deletion cancelled.")
        return

    if profile_to_delete not in profiles:
        print(f"{Colors.RED}Profile '{profile_to_delete}' not found.{Colors.NC}")
        return

    if len(profiles) == 1:
        print(f"{Colors.RED}Cannot delete the last remaining profile.{Colors.NC}")
        return

    confirm = input(f"Are you sure you want to delete the profile '{profile_to_delete}'? This cannot be undone. (y/n): ").lower()
    if confirm == 'y':
        del config["profiles"][profile_to_delete]
        print(f"{Colors.GREEN}Profile '{profile_to_delete}' has been deleted.{Colors.NC}")

        if config["active_profile"] == profile_to_delete:
            new_active = next(iter(config["profiles"])) # Get the first available profile
            config["active_profile"] = new_active
            print(f"'{new_active}' is now the active profile.")
        
        save_configuration(config)

def select_profile(config):
    """Displays available profiles and prompts the user to select, create, or exit."""
    while True:
        print(f"\n{Colors.BLUE}--- Connection Profiles ---{Colors.NC}")
        profiles = config.get("profiles", {})
        if not profiles:
            print(f"{Colors.YELLOW}No profiles found. Please create one.{Colors.NC}")
        else:
            print("Available profiles:")
            for name in profiles:
                active_marker = f"{Colors.GREEN} (active){Colors.NC}" if name == config.get("active_profile") else ""
                print(f"  - {name}{active_marker}")

        choice = input("\nEnter a profile name to load, (c)reate, (d)elete, or (e)xit: ").lower()

        if choice == 'e' or choice == 'exit':
            return None, None # Signal to exit the program
        elif choice == 'c' or choice == 'create':
            return "create", None
        elif choice == 'd' or choice == 'delete':
            delete_profile(config)
            continue # Loop back to show the updated profile list
        elif choice in profiles:
            return "load", choice
        else:
            print(f"{Colors.RED}Profile '{choice}' not found. Please try again.{Colors.NC}")

def get_log_dir(config):
    """Gets logging preference from the user."""
    return input(f"Enter a directory to save command logs (default: {config.get('default_log_dir', 'logs')}): ") or config.get('default_log_dir', 'logs')

def display_profile(profile, log_dir):
    """Displays the details of the currently active profile."""
    print(f"{Colors.GREEN}Configuration set.{Colors.NC}")
    print(f"RMC Target:   {Colors.YELLOW}{profile['username']}@{profile['rmc_ip']}{Colors.NC}")
    print(f"W400 BMC Target:  {Colors.YELLOW}{profile['username']}@{profile['w400_ip']}{Colors.NC}")
    print(f"W400 x86 Target:  {Colors.YELLOW}{profile['w400_x86_username']}@{profile['w400_x86_ip']} (via W400 BMC){Colors.NC}")
    if profile.get('th6_devices'):
        for i, th6 in enumerate(profile['th6_devices']):
            print(f"TH6-{i+1} Target: {Colors.YELLOW}{th6['username']}@{th6['ip']}{Colors.NC}")

    if log_dir:
        print(f"Logging to:   {Colors.YELLOW}{log_dir}{Colors.NC}")
    else:
        print(f"Logging:      {Colors.YELLOW}Disabled{Colors.NC}")
    input(f"{Colors.YELLOW}Press Enter to continue to the main menu...{Colors.NC}")

def main():
    """Main execution function."""
    rmc_client = None
    w400_client = None
    w400_x86_client = None
    th6_clients = []

    config = load_configuration()

    while True:
        action, profile_name = select_profile(config)

        if action is None: # User chose to exit
            break

        if action == "create":
            profile_data = create_new_profile()
            save_choice = input("Save this new profile? (y/n): ").lower()
            if save_choice == 'y':
                new_profile_name = input("Enter a name for this profile: ")
                config["profiles"][new_profile_name] = profile_data
                config["active_profile"] = new_profile_name
                save_configuration(config)
                print(f"{Colors.GREEN}Profile '{new_profile_name}' saved and set as active.{Colors.NC}")
        else: # Load existing profile
            profile_data = config["profiles"][profile_name]
            if config["active_profile"] != profile_name:
                config["active_profile"] = profile_name
                save_configuration(config)
                print(f"{Colors.GREEN}Profile '{profile_name}' is now active.{Colors.NC}")

        log_dir = get_log_dir(config)
        display_profile(profile_data, log_dir)

        rmc_client = RemoteClient(profile_data['rmc_ip'], profile_data['username'], profile_data.get('password'), log_dir)
        w400_client = RemoteClient(profile_data['w400_ip'], profile_data['username'], profile_data.get('password'), log_dir)
        w400_x86_client = None # Reset
        th6_clients = [] # Reset

        # Establish the proxy connection for the x86 client
        if w400_client.connect():
            w400_x86_client = RemoteClient(profile_data['w400_x86_ip'], profile_data['w400_x86_username'], profile_data.get('w400_x86_password'), log_dir)
            if not w400_x86_client.connect_via_proxy(w400_client.client):
                w400_x86_client = None # Connection failed, disable x86 tests
        
        # Create clients for TH6 devices
        for th6_data in profile_data.get('th6_devices', []):
            th6_client = RemoteClient(th6_data['ip'], th6_data['username'], th6_data.get('password'), log_dir)
            if th6_client.connect():
                th6_clients.append(th6_client)
            else:
                print(f"{Colors.RED}Failed to connect to TH6 device {th6_data['ip']}. Skipping.{Colors.NC}")

        diag = Diagnostics(rmc_client, w400_client, w400_x86_client, th6_clients)
        menu = Menu(diag, profile_data['rmc_ip'], profile_data['w400_ip'], profile_data['username'], profile_data['w400_x86_ip'], profile_data['w400_x86_username'], th6_clients)
        
        # Create log directory if specified
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
                print(f"{Colors.BLUE}Logging output to directory: {log_dir}{Colors.NC}")
            except OSError as e:
                print(f"{Colors.RED}Error creating log directory '{log_dir}': {e}{Colors.NC}")
                log_dir = None # Disable logging if directory cannot be created
        
        menu_action = menu.main_menu()

        # Close connections before looping or exiting
        rmc_client.close()
        w400_client.close()
        if w400_x86_client:
            w400_x86_client.close()
        for th6_client in th6_clients:
            th6_client.close()
        
        # The main_menu now returns "exit" or "change_target"
        if menu_action == "exit":
            break
        # If action is "change_target", the loop will naturally restart

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user. Exiting.{Colors.NC}")
        sys.exit(0)

    print(f"{Colors.GREEN}Exiting. Goodbye!{Colors.NC}")