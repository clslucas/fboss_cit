#!/usr/bin/env python3

import getpass
import os
from functools import wraps
import sys
from datetime import datetime, timezone
import argparse
import time
import logging
import concurrent.futures # Added for parallel processing
from logging.handlers import RotatingFileHandler
import smtplib
from email.mime.text import MIMEText
import json # Added for loading external configuration
from remote_client import RemoteClient
import subprocess
import re 
from utils import Colors, get_visible_length

# --- Configuration ---
BUS_DEFAULT = 10
ADDR_DEFAULT = 0x23
MAX_WORKERS = 10 # For parallel execution on multiple clients

CONFIG_FILE = "config.json"


def test_wrapper(title):
    """A decorator to wrap test functions with a consistent header and footer."""
    def decorator(func):
        # A simple stream-like object to capture output and detect failures.
        class FailureCapturingStream:
            def __init__(self, original_stream):
                self._original_stream = original_stream
                self.has_failed = False
                self.buffer = []

            def write(self, text):
                # Check for the failure string before writing
                if f"{Colors.RED}[ FAIL ]{Colors.NC}" in text:
                    self.has_failed = True
                self.buffer.append(text)
                self._original_stream.write(text)

            def flush(self):
                self._original_stream.flush()

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            original_stdout = sys.stdout
            failure_stream = FailureCapturingStream(original_stdout)
            sys.stdout = failure_stream

            start_time = datetime.now()
            print(f"\n{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
            print(f"{Colors.YELLOW}  START: {title} ({start_time.strftime('%Y-%m-%d %H:%M:%S')}){Colors.NC}")
            print(f"{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
            
            try:
                func(self, *args, **kwargs)
            finally:
                sys.stdout = original_stdout # Always restore stdout
            
            end_time = datetime.now()
            duration = end_time - start_time
            print(f"\n{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
            
            # --- Log result to summary file ---
            summary_status = "PASS" if not failure_stream.has_failed else "FAIL"
            # self.log_dir is available because the decorator is applied to methods of Diagnostics class
            summary_log_path = os.path.join(self.log_dir, "test_summary.log") if self.log_dir else None
            
            if summary_log_path:
                try:
                    with open(summary_log_path, 'a') as f:
                        f.write(f"{end_time.strftime('%Y-%m-%d %H:%M:%S')} | {title:<50} | Duration: {duration} | Status: {summary_status}\n")
                except IOError as e:
                    print(f"{Colors.RED}Error writing to summary log '{summary_log_path}': {e}{Colors.NC}", file=sys.stderr)

            print(f"{Colors.YELLOW}  END: {title} ({end_time.strftime('%Y-%m-%d %H:%M:%S')}) - Duration: {duration}{Colors.NC}")
            print(f"{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
            return not failure_stream.has_failed
        return wrapper
    return decorator

def get_local_arp_table(debug_mode=False):
    """
    Executes the 'arp -n' command locally and parses its output into a
    dictionary mapping MAC addresses to IP addresses.

    Returns:
        dict: A dictionary where keys are MAC addresses (str) and values are
              IP addresses (str). Returns an empty dict if 'arp' command fails.
    """
    arp_table = {}
    if debug_mode:
        print("Fetching local ARP table to resolve MAC addresses...")
    try:
        # Execute the arp command and capture its output
        result = subprocess.run(
            ['arp', '-n'], capture_output=True, text=True, check=False, encoding='utf-8'
        )
        if result.returncode != 0:
            print(f"{Colors.YELLOW}Warning: 'arp -n' command failed. Cannot resolve MACs to IPs.{Colors.NC}", file=sys.stderr)
            return arp_table

        # Iterate over each line in the command's output, skipping the header
        for line in result.stdout.splitlines()[1:]:
            parts = re.split(r'\s+', line.strip())
            if len(parts) >= 3:
                ip_address, mac_address = parts[0], parts[2]
                if re.match(r'([0-9a-f]{2}(?::[0-9a-f]{2}){5})', mac_address, re.IGNORECASE):
                    arp_table[mac_address.lower()] = ip_address
    except FileNotFoundError:
        print(f"{Colors.RED}Error: 'arp' command not found. Cannot resolve MAC addresses.{Colors.NC}", file=sys.stderr)

    return arp_table

def increment_mac(mac_string):
    """
    Increments a MAC address by one.
    Args:
        mac_string (str): The MAC address in 'XX:XX:XX:XX:XX:XX' format.
    Returns:
        str: The incremented MAC address in the same format, or None if input is invalid.
    """
    # 1. Validate the MAC address format. It should be 6 groups of 2 hex digits.
    if not isinstance(mac_string, str) or not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_string):
        return None

    try:
        # 2. Remove delimiters and convert from hex to an integer
        mac_int = int(mac_string.replace(':', ''), 16)

        # 3. Increment the integer value
        mac_int += 1

        # 4. Handle the overflow case (e.g., ff:ff:ff:ff:ff:ff -> 00:00:00:00:00:00)
        # A 48-bit MAC address cannot exceed 0xffffffffffff.
        if mac_int > 0xffffffffffff:
            mac_int = 0 # Wrap around to 0

        # 5. Convert back to a 12-character zero-padded hex string
        inc_mac_hex = format(mac_int, '012x')

        # 6. Re-insert the colons to format it as a MAC address
        return ':'.join(inc_mac_hex[i:i+2] for i in range(0, 12, 2))
    except (ValueError, TypeError):
        return None

# --- DHCP Lease Parsing Functions (Adapted from dhcptool.py) ---

def _parse_lease_time(time_str):
    """Helper to parse common lease time formats."""
    for fmt in ('%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(time_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None

def _parse_dhcp_leases(file_path):
    """
    Parses a dhcpd.leases file and returns a dictionary of all active leases.
    """
    try:
        with open(file_path, 'r') as f:
            content = f.read()
    except (FileNotFoundError, PermissionError) as e:
        print(f"{Colors.YELLOW}Warning: Could not read DHCP lease file at '{file_path}': {e}{Colors.NC}", file=sys.stderr)
        return {}

    leases_db = {}
    current_lease = None

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        tokens = line.split()
        key = tokens[0].lower()

        if key == 'lease':
            current_lease = {'ip': tokens[1]}
        elif key == '}' and current_lease:
            if current_lease.get('ip'):
                leases_db.setdefault(current_lease['ip'], []).append(current_lease.copy())
            current_lease = None
        elif current_lease:
            value_str = line[line.find(tokens[0]) + len(tokens[0]):].strip().rstrip(';').strip()
            if key in ['starts', 'ends']:
                time_val_str = ' '.join(value_str.split()[1:])
                current_lease[key] = _parse_lease_time(time_val_str)
            elif key == 'hardware':
                current_lease['mac'] = value_str.split()[1]
            elif key == 'set' and value_str.startswith('vendor-class-identifier ='):
                vendor_string = value_str.split('=', 1)[1].strip().strip('"')
                for part in vendor_string.split(':'):
                    if part.startswith('serial='):
                        current_lease['serial'] = part.split('=', 1)[1]
            elif key == 'binding' and len(tokens) > 1 and tokens[1] == 'state':
                current_lease['binding_state'] = tokens[2].strip(';')

    active_leases = {}
    now_utc = datetime.now(timezone.utc)
    for ip, lease_history in leases_db.items():
        valid_records = [rec for rec in lease_history if rec.get('starts')]
        if not valid_records: continue
        latest_lease = max(valid_records, key=lambda x: x['starts'])
        binding_state = latest_lease.get('binding_state', 'active')
        starts_utc, ends_utc = latest_lease.get('starts'), latest_lease.get('ends')
        is_active = (binding_state == 'active') and (starts_utc and ends_utc and starts_utc <= now_utc < ends_utc)
        if is_active:
            active_leases[ip] = latest_lease

    return active_leases

# Default structure for a new profile. Used when creating a new config file.
default_profile_data = {
    "rmc_ip": "192.168.1.1",
    "w400_ip": "192.168.1.2",
    "username": "root",
    "password": "",
    "w400_x86_ip": "192.168.100.1",
    "w400_serial": "W400_SERIAL_EXAMPLE",
    "w400_x86_username": "root",
    "w400_x86_password": "",
    "th6_devices": [
        {
            "serial": "TH6_SERIAL_EXAMPLE",
            "ip": "192.168.2.10",
            "x86_username": "root",
            "x86_password": "",
            "bmc_ip": "192.168.1.10",
            "bmc_username": "root",
            "bmc_password": ""
        }
    ]
}

def load_configuration():
    """Loads configuration from config.json, creating it with defaults if it doesn't exist."""
    default_config_structure = {
        "active_profile": "default",
        "profiles": {
            "default": default_profile_data
        },
        "dhcp_lease_files": [
            "/var/lib/dhcp/dhcpd.leases",
            "/var/lib/dhcpd/dhcpd.leases"
        ],
        "default_log_dir": "logs",
        "email_settings": {
            "smtp_server": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "your_email@example.com",
            "smtp_password": "your_app_password",
            "sender_email": "your_email@example.com",
            "receiver_emails": ["recipient1@example.com", "recipient2@example.com"]
        },
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
                    "rmc_ip": config.get("default_rmc_ip"),
                    "w400_ip": config.get("default_w400_ip"),
                    "username": config.get("default_username"),
                    "password": config.get("configured_password"),
                    "w400_serial": config.get("w400_serial"),
                    "w400_x86_ip": config.get("w400_x86_ip"),
                    "w400_x86_username": config.get("w400_x86_username"),
                    "w400_x86_password": config.get("w400_x86_password"),
                    # Migrate TH6 devices if they existed in some other form, or use default
                    "th6_devices": config.get("th6_devices")
                }
                # Ensure all keys are present in the migrated profile
                for key, value in default_profile_data.items():
                    migrated_profile.setdefault(key, value)
                config = {
                    "active_profile": "default",
                    "profiles": {"default": migrated_profile},
                    "dhcp_lease_files": default_config_structure["dhcp_lease_files"],
                    "default_log_dir": config.get("default_log_dir", "logs"),
                    "email_settings": config.get("email_settings", default_config_structure["email_settings"])
                }
                save_configuration(config)
                print(f"{Colors.GREEN}Migration complete. Configuration saved.{Colors.NC}")

            config_updated = False
            # --- Migration logic for dhcp_lease_file -> dhcp_lease_files ---
            if "dhcp_lease_file" in config and "dhcp_lease_files" not in config:
                print(f"{Colors.YELLOW}Migrating 'dhcp_lease_file' to 'dhcp_lease_files' in config...{Colors.NC}")
                config["dhcp_lease_files"] = default_config_structure["dhcp_lease_files"]
                # Preserve the user's old setting if they changed it from the very old default
                if config["dhcp_lease_file"] not in config["dhcp_lease_files"]:
                    config["dhcp_lease_files"].insert(0, config["dhcp_lease_file"])
                del config["dhcp_lease_file"]
                config_updated = True

            for key, default_value in default_config_structure.items():
                if key not in config:
                    print(f"{Colors.YELLOW}Warning: Missing top-level key '{key}' in config.json. Adding from defaults.{Colors.NC}")
                    config[key] = default_value
                    config_updated = True

            if config_updated:
                save_configuration(config)

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

    # Regex constants for check_th6_power_summary
    LTC4287_HSC_REGEX = re.compile(r'LTC4287_HSC-.*-11\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+([\d.]+)')
    POWER_SUMMARY_LINE_REGEX = re.compile(r'(\w+)\s*:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)')
    OM_TEMP_REGEX = re.compile(r"^\s*(E\d+)\s+(YES|NO)\s+([\d.]+)\s+'C\s+(N/A|[\d.]+)\s+(YES|NO)")
    PORT_DSP_TEMP_REGEX = re.compile(r"^\s*(E\d+)\s+.*?[\d.]+\s+'C\s+([\d.]+)\s+'C\s+.*$")
    
    # Map of RMC status register bits to their expected values and names.
    # Moved here from run_rmc_status_check for better readability.
    RMC_STATUS_MAP = {
        "0x00 7": "wRPU_READY_PLD_R 1",
        "0x00 6": "wRPU_READY_SPARE_PLD_R 1",
        "0x00 5": "wRPU_2_READY_PLD_R 1",
        "0x00 4": "wRPU_2_READY_SPARE_PLD_R 1",
        "0x00 3": "IT_STOP_PUMP 0",
        "0x00 2": "IT_STOP_PUMP_SPARE 0",
        "0x00 1": "IT_STOP_PUMP_2 0",
        "0x00 0": "IT_STOP_PUMP_SPARE_2 0",
        "0x01 7": "wP24V_SM_INA230_ALERT_N_R 1",
        "0x01 6": "wP24V_AUX_INA230_ALERT_N_R 1",
        "0x01 5": "wP48V_HSC_ALERT_N 1",
        "0x01 4": "wSMB_TMC75_TEMP_ALERT_N_R 1",
        "0x01 3": "wPWRGD_P52V_HSC_PWROK_R 1",
        "0x01 2": "wPWRGD_P24V_AUX_R 1",
        "0x01 1": "wPWRGD_P12V_AUX_R 1",
        "0x01 0": "wPWRGD_P12V_SCM_R 1",
        "0x02 7": "wPWRGD_P5V_AUX_R 1",
        "0x02 6": "wPWRGD_P3V3_AUX_R 1",
        "0x02 5": "wPWRGD_P1V5_AUX_R 1",
        "0x02 4": "wPWRGD_P1V05_AUX_R 1",
        "0x02 3": "wPWRGD_P24V_SMPWROK 1",
        "0x02 2": "wPWRGD_COMPUTE_BLADE_BUF_R[0] 0",
        "0x02 1": "wPWRGD_COMPUTE_BLADE_BUF_R[1] 0",
        "0x02 0": "wPWRGD_COMPUTE_BLADE_BUF_R[2] 0",
        "0x03 7": "wPWRGD_COMPUTE_BLADE_BUF_R[3] 0",
        "0x03 6": "wPWRGD_COMPUTE_BLADE_BUF_R[4] 0",
        "0x03 5": "wPWRGD_COMPUTE_BLADE_BUF_R[6] 0",
        "0x03 4": "wPWRGD_COMPUTE_BLADE_BUF_R[6] 0",
        "0x03 3": "wPWRGD_COMPUTE_BLADE_BUF_R[7] 0",
        "0x03 2": "wPWRGD_COMPUTE_BLADE_BUF_R[8] 0",
        "0x03 1": "wPWRGD_COMPUTE_BLADE_BUF_R[9] 0",
        "0x03 0": "wPWRGD_COMPUTE_BLADE_BUF_R[10] 0",
        "0x04 7": "wPWRGD_COMPUTE_BLADE_BUF_R[11] 0",
        "0x04 6": "wPWRGD_COMPUTE_BLADE_BUF_R[12] 0",
        "0x04 5": "wPWRGD_COMPUTE_BLADE_BUF_R[13] 0",
        "0x04 4": "wPWRGD_COMPUTE_BLADE_BUF_R[14] 0",
        "0x04 3": "wPWRGD_COMPUTE_BLADE_BUF_R[15] 0",
        "0x04 2": "wPWRGD_COMPUTE_BLADE_BUF_R[16] 0",
        "0x04 1": "wPWRGD_COMPUTE_BLADE_BUF_R[17] 0",
        "0x04 0": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[0] 0",
        "0x05 7": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[1] 0",
        "0x05 6": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[2] 0",
        "0x05 5": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[3] 0",
        "0x05 4": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[4] 0",
        "0x05 3": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[5] 0",
        "0x05 2": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[6] 0",
        "0x05 1": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[7] 0",
        "0x05 0": "wPWRGD_NVS_BLADE_PWROK_L_BUF_R[8] 0",
        "0x13 3": "wIT_GEAR_RPU_LINK_PRSNT_N_R 0",
        "0x13 2": "wIT_GEAR_RPU_LINK_PRSNT_SPARE_N_R 1",
        "0x13 1": "wIT_GEAR_RPU_2_LINK_PRSNT_N_R 0",
        "0x13 0": "wIT_GEAR_RPU_2_LINK_PRSNT_SPARE_N_R 1",
        "0x16 0": "wPWRGD_BLADE_PWROK_SINGLE_B_UF_R 1"
    }

    def __init__(self, rmc_client, w400_client, w400_x86_client=None, th6_clients=None, th6_bmc_clients=None, debug=False, log_dir=None, config=None):
        self.rmc = rmc_client
        self.w400 = w400_client
        self.w400_x86 = w400_x86_client
        self.th6_clients = th6_clients if th6_clients is not None else []
        self.th6_bmc_clients = th6_bmc_clients if th6_bmc_clients is not None else []
        self.debug = debug
        self.log_dir = log_dir # Store the log directory for use by decorators
        self.config = config if config is not None else {}
 
    def _debug_print(self, message):
        if self.debug:
            print(f"{Colors.CYAN}DEBUG: {message}{Colors.NC}")
 
    def _run_commands_on_clients_parallel(self, clients, command_template, title_prefix=""):
        """
        Executes a command on multiple RemoteClient instances in parallel.
        Prints output as it comes and aggregates success status.
        Returns True if all commands succeed (exit code 0), False otherwise.
        """
        if not clients:
            return True  # No clients to run on, consider it a success

        all_commands_successful = True
        futures = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i, client in enumerate(clients):
                display_name = f"{title_prefix}{i+1} ({client.hostname})" if title_prefix else client.hostname
                self._debug_print(f"Submitting command for {display_name}: {command_template}")
 
                # Print header before submitting the task, so it appears in order of submission
                print(f"\n{Colors.CYAN}--- {display_name} ---{Colors.NC}")
                # RemoteClient.run_command already prints output if print_output=True
                future = executor.submit(client.run_command, command_template, True)
                futures[future] = display_name

            for future in concurrent.futures.as_completed(futures):
                display_name = futures[future]
                try:
                    output, exit_code = future.result()
                    if exit_code != 0:
                        all_commands_successful = False
                        # RemoteClient.run_command already prints failure message
                except Exception as exc:
                    all_commands_successful = False
                    print(f"{Colors.RED}Error executing command on {display_name}: {exc}{Colors.NC}", file=sys.stderr) # pylint: disable=line-too-long
        return all_commands_successful

    def _run_commands_and_get_output_parallel(self, clients, command_template):
        """
        Executes a command on multiple RemoteClient instances in parallel and returns
        a dictionary of {client_hostname: (output_string, exit_code)}.
        """
        results = {}
        futures = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for client in clients:
                future = executor.submit(client.run_command, command_template, False) # Don't print output directly
                futures[future] = client.hostname

            for future in concurrent.futures.as_completed(futures):
                hostname = futures[future]
                try:
                    output, exit_code = future.result()
                    results[hostname] = (output, exit_code)
                except Exception as exc:
                    print(f"{Colors.RED}Error executing command on {hostname}: {exc}{Colors.NC}", file=sys.stderr) # pylint: disable=line-too-long
                    results[hostname] = ("", -1)
        return results

    # --- RMC Specific Functions ---
    @test_wrapper("Running RMC Status Check")
    def run_rmc_status_check(self, bus=BUS_DEFAULT, addr=ADDR_DEFAULT):
        """
        Performs an RMC status check by reading I2C registers and comparing
        bit values against an expected map. This is a Python implementation
        of the original rmc_status_check.sh script.
        """

        overall_success = True

        # 1. Read data from the I2C device
        cmd = f"i2cdump -y {bus} {addr:#x}"
        i2c_output, exit_code = self.rmc.run_command(cmd, print_output=False)
        if exit_code != 0:
            print(f"{Colors.RED}[ FAIL ] Error reading from I2C device bus {bus} at address {addr:#x}.{Colors.NC}")
            if i2c_output:
                print(f"Details: {i2c_output}")
            return False

        # 2. Parse the i2cdump output into a dictionary of bytes
        bytes_map = {}
        for line in i2c_output.splitlines():
            match = re.match(r'^([0-9a-f]{2}):\s+((?:[0-9a-f]{2}\s?)+)', line, re.IGNORECASE)
            if match:
                base_addr = int(match.group(1), 16)
                values = match.group(2).split()
                for i, val_str in enumerate(values):
                    offset = base_addr + i
                    bytes_map[offset] = int(val_str, 16)

        # 3. Iterate through the map, check bits, and print status
        for reg_offset in range(256):
            for bit_pos in range(8):
                key = f"0x{reg_offset:02x} {bit_pos}"
                if key in self.RMC_STATUS_MAP:
                    map_entry = self.RMC_STATUS_MAP[key].split()
                    name, expected_val_str = map_entry[0], map_entry[1]
                    expected_val = int(expected_val_str)

                    byte_val = bytes_map.get(reg_offset)

                    if byte_val is None:
                        status_str = f"{Colors.YELLOW}[  ??  ]{Colors.NC}"
                        actual_val = "?" # pylint: disable=unused-variable
                    else:
                        actual_val = (byte_val >> bit_pos) & 1
                        if actual_val == expected_val:
                            status_str = f"{Colors.GREEN}[  OK  ]{Colors.NC}"
                        else:
                            status_str = f"{Colors.RED}[ FAIL ]{Colors.NC}"
                            overall_success = False

                    print(f"{status_str} {name:<35s} = {actual_val} (expected {expected_val})")
        return overall_success

    @test_wrapper("Checking AALC LC GPIO Cable Detect (RMC)")
    def check_aal_gpio_cable(self):
        output, exit_code = self.rmc.run_command(f"i2cget -y {BUS_DEFAULT} 0x{ADDR_DEFAULT:x} 0x13")
        if exit_code != 0 or not output.strip():
            print(f"{Colors.RED}[ FAIL ] Could not read AALC GPIO status from i2c.{Colors.NC}")
            return False
        overall_success = True
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
                if not is_present:
                    overall_success = False
                    print(f"{Colors.RED}[ FAIL ]{Colors.NC} {name}: {status_text}")
                else:
                    print(f"{Colors.GREEN}[  OK  ]{Colors.NC} {name}: {status_text}")
        except (ValueError, IndexError):
            print(f"{Colors.RED}[ FAIL ] Failed to parse the hexadecimal output: '{output.strip()}'{Colors.NC}")
            overall_success = False
        return overall_success

    @test_wrapper("Checking AALC RPU Ready Status (RMC)")
    def check_aal_rpu_ready(self):
        output, exit_code = self.rmc.run_command(f"i2cget -y {BUS_DEFAULT} 0x{ADDR_DEFAULT:x} 0x00")
        if exit_code != 0 or not output.strip():
            print(f"{Colors.RED}[ FAIL ] Could not read AALC RPU status from i2c.{Colors.NC}")
            return False
        overall_success = True
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
                if status != 1:
                    overall_success = False
                    print(f"{Colors.RED}[ FAIL ]{Colors.NC} {name}: {status_text}")
                else:
                    print(f"{Colors.GREEN}[  OK  ]{Colors.NC} {name}: {status_text}")
        except (ValueError, IndexError):
            print(f"{Colors.RED}[ FAIL ] Failed to parse the hexadecimal output: '{output.strip()}'{Colors.NC}")
            overall_success = False
        return overall_success

    @test_wrapper("Checking RMC Software & Firmware Versions")
    def check_rmc_version(self):
        output, exit_code = self.rmc.run_command("mfg-tool version-display", print_output=False)
        if exit_code != 0:
            print(f"{Colors.RED}[ FAIL ] Failed to get version information.{Colors.NC}")
            print(output) # Print the error output
            return False

        try:
            # Find the start of the JSON object, as there might be debug text before it.
            json_start_index = output.find('{')
            if json_start_index == -1:
                print(f"{Colors.RED}[ FAIL ] Could not find JSON data in the command output.{Colors.NC}")
                print(output)
                return False

            json_str = output[json_start_index:]
            version_data = json.loads(json_str)

            table_data = []
            if 'bmc' in version_data:
                table_data.append(("BMC", version_data['bmc']))
            if 'chassis' in version_data and isinstance(version_data['chassis'], dict):
                for component, version in version_data['chassis'].items():
                    table_data.append((component, version))

            if not table_data:
                print(f"{Colors.YELLOW}No version information was parsed from the output.{Colors.NC}")
                print(output)
                return True # Command succeeded, but no data to show, not a failure.

            # --- Print formatted table ---
            comp_width = max([len(row[0]) for row in table_data] + [len("Component")])
            ver_width = max([len(str(row[1])) for row in table_data] + [len("Version")])
            
            print(f"+-{'-' * comp_width}-+-{'-' * ver_width}-+")
            print(f"| {'Component':<{comp_width}} | {'Version':<{ver_width}} |")
            print(f"+-{'-' * comp_width}-+-{'-' * ver_width}-+")
            for component, version in table_data:
                print(f"| {component:<{comp_width}} | {str(version):<{ver_width}} |")
            print(f"+-{'-' * comp_width}-+-{'-' * ver_width}-+")
            return True
        except (json.JSONDecodeError, ValueError) as e:
            print(f"{Colors.RED}[ FAIL ] Failed to parse JSON from command output: {e}{Colors.NC}")
            print(f"Raw output:\n{output}")
            return False

    @test_wrapper("Checking TH6 LC Cable Detect (RMC)")
    def check_th6_lc_cable(self):
        statuses = {}
        overall_success = True
        # Register 0x10 for Trays 1-7
        output_10, code_10 = self.rmc.run_command("i2cget -f -y 10 0x23 0x10")
        if code_10 == 0 and output_10.strip():
            try:
                val = int(output_10.strip(), 16)
                # Bits 6 down to 0 for Trays 1-7
                for i in range(7):
                    statuses[f"Tray {i+1}"] = ((val >> (6 - i)) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}[ FAIL ] Failed to parse register 0x10 output: '{output_10.strip()}'{Colors.NC}")
                overall_success = False
        else:
            print(f"{Colors.RED}[ FAIL ] Failed to read register 0x10 for Trays 1-7.{Colors.NC}")
            overall_success = False

        # Register 0x11 for Trays 8-10
        output_11, code_11 = self.rmc.run_command("i2cget -f -y 10 0x23 0x11")
        if code_11 == 0 and output_11.strip():
            try:
                val = int(output_11.strip(), 16)
                statuses["Tray 8"] = ((val >> 7) & 1) == 0
                statuses["Tray 9"] = ((val >> 6) & 1) == 0
                statuses["Tray 10"] = ((val >> 5) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}[ FAIL ] Failed to parse register 0x11 output: '{output_11.strip()}'{Colors.NC}")
                overall_success = False
        else:
            print(f"{Colors.RED}[ FAIL ] Failed to read register 0x11 for Trays 8-10.{Colors.NC}")
            overall_success = False

        # Register 0x12 for Trays 11-12
        output_12, code_12 = self.rmc.run_command("i2cget -f -y 10 0x23 0x12")
        if code_12 == 0 and output_12.strip():
            try:
                val = int(output_12.strip(), 16)
                statuses["Tray 11"] = ((val >> 4) & 1) == 0
                statuses["Tray 12"] = ((val >> 3) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}[ FAIL ] Failed to parse register 0x12 output: '{output_12.strip()}'{Colors.NC}")
                overall_success = False
        else:
            print(f"{Colors.RED}[ FAIL ] Failed to read register 0x12 for Trays 11-12.{Colors.NC}")
            overall_success = False

        print("\n--- Parsed Tray Presence Status (Low active = PRESENT) ---")
        for i in range(1, 13):
            name = f"Tray {i}"
            is_present = statuses.get(name, False) # Default to NOT PRESENT if key is missing
            if not is_present:
                overall_success = False
                print(f"{Colors.RED}[ FAIL ]{Colors.NC} {name}: NOT PRESENT")
            else:
                print(f"{Colors.GREEN}[  OK  ]{Colors.NC} {name}: PRESENT")
        return overall_success

    @test_wrapper("Checking Drip Pan Leak Sensor Presence (RMC)")
    def check_drip_pan_leak_sensor(self):
        statuses = {}
        overall_success = True
        # Register 0x14 for sensors 0, 1
        output_14, code_14 = self.rmc.run_command("i2cget -y 10 0x23 0x14")
        if code_14 == 0 and output_14.strip():
            try:
                val = int(output_14.strip(), 16)
                statuses["Leak Sensor 0"] = ((val >> 1) & 1) == 0
                statuses["Leak Sensor 1"] = (val & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}[ FAIL ] Failed to parse register 0x14 output: '{output_14.strip()}'{Colors.NC}")
                overall_success = False
        else:
            print(f"{Colors.RED}[ FAIL ] Failed to read register 0x14 for Leak Sensors 0-1.{Colors.NC}")
            overall_success = False

        # Register 0x15 for sensor 2
        output_15, code_15 = self.rmc.run_command("i2cget -y 10 0x23 0x15")
        if code_15 == 0 and output_15.strip():
            try:
                val = int(output_15.strip(), 16)
                statuses["Leak Sensor 2"] = ((val >> 7) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}[ FAIL ] Failed to parse register 0x15 output: '{output_15.strip()}'{Colors.NC}")
                overall_success = False
        else:
            print(f"{Colors.RED}[ FAIL ] Failed to read register 0x15 for Leak Sensor 2.{Colors.NC}")
            overall_success = False

        # Register 0x16 for sensors 3, 4
        output_16, code_16 = self.rmc.run_command("i2cget -y 10 0x23 0x16")
        if code_16 == 0 and output_16.strip():
            try:
                val = int(output_16.strip(), 16)
                statuses["Leak Sensor 3"] = ((val >> 6) & 1) == 0
                statuses["Leak Sensor 4"] = ((val >> 5) & 1) == 0
            except (ValueError, IndexError):
                print(f"{Colors.RED}[ FAIL ] Failed to parse register 0x16 output: '{output_16.strip()}'{Colors.NC}")
                overall_success = False
        else:
            print(f"{Colors.RED}[ FAIL ] Failed to read register 0x16 for Leak Sensors 3-4.{Colors.NC}")
            overall_success = False

        print("\n--- Parsed Leak Sensor Presence Status (Low active = PRESENT) ---")
        for i in range(5):
            name = f"Leak Sensor {i}"
            is_present = statuses.get(name, False)
            if not is_present:
                overall_success = False
                print(f"{Colors.RED}[ FAIL ]{Colors.NC} {name}: NOT PRESENT")
            else:
                print(f"{Colors.GREEN}[  OK  ]{Colors.NC} {name}: PRESENT")
        return overall_success

    @test_wrapper("Checking RMC FRU Information")
    def check_rmc_fru_info(self):
        output, exit_code = self.rmc.run_command("mfg-tool inventory")
        return exit_code == 0

    @test_wrapper("Checking RMC Sensor Status")
    def check_rmc_sensor_status(self):
        output, exit_code = self.rmc.run_command("mfg-tool sensor-display")
        return exit_code == 0

    @test_wrapper("Checking RMC Boot Slot")
    def check_rmc_boot_slot(self):
        output, exit_code = self.rmc.run_command("cat /run/media/slot")
        if exit_code != 0 or not output.strip():
            print(f"{Colors.RED}[ FAIL ] Could not read RMC boot slot status.{Colors.NC}")
            return False
        overall_success = True
        try:
            slot_str = output.strip()
            print("\n--- Parsed Boot Slot Status ---")
            if slot_str == "0":
                print(f"Boot Slot: {Colors.GREEN}0 (Primary){Colors.NC}")
            elif slot_str == "1":
                print(f"Boot Slot: {Colors.GREEN}1 (Alternate){Colors.NC}")
            elif slot_str == "N/A": # If slot is not set, it's not a failure
                print(f"Boot Slot: {Colors.YELLOW}N/A (Not set){Colors.NC}")
            else:
                print(f"{Colors.RED}[ FAIL ] Unknown Boot Slot: {slot_str}{Colors.NC}")
                overall_success = False
        except Exception:
            print(f"{Colors.RED}[ FAIL ] Failed to parse boot slot output: '{output.strip()}'{Colors.NC}")
            overall_success = False
        return overall_success


    def _check_and_display_in_table(self, device_map, grep_pattern, headers, expected_values=None):
        """
        A generic helper to run rackmoncli checks on multiple devices and display results in a table.
        """
        results = []
        overall_success = True
        for device_type, addrs in device_map.items():
            for i, addr in enumerate(addrs):
                slot_name = f"{device_type} {i + 1}"
                self._debug_print(f"Querying {slot_name} (Address {addr})...")
                command = f"rackmoncli data --dev-addr {addr} --latest | grep -iE '{grep_pattern}'"
                output, exit_code = self.w400.run_command(command, print_output=False)

                if exit_code == 0 and output.strip():
                    for line in output.strip().splitlines():
                        try:
                            prop, val = line.split(":", 1)
                            results.append({'device': slot_name, 'addr': addr, 'property': prop.strip(), 'value': val.strip()})
                        except ValueError:
                            results.append({'device': slot_name, 'addr': addr, 'property': "Parse Error", 'value': line.strip()})
                else:
                    overall_success = False
                    print(f"{Colors.RED}[ FAIL ]{Colors.NC} No response from {slot_name} (Address {addr})")
                    results.append({'device': slot_name, 'addr': addr, 'property': f'{Colors.RED}No Response{Colors.NC}', 'value': 'N/A'})

        # Print table
        print(f"| {headers[0]:<18} | {headers[1]:<10} | {headers[2]:<30} | {headers[3]:<15} |")
        print("+" + "-"*20 + "+" + "-"*12 + "+" + "-"*32 + "+" + "-"*17 + "+")
        for res in results:
            print(f"| {res['device']:<18} | {res['addr']:<10} | {res['property']:<30} | {res['value']:<15} |")
        print("+" + "-"*20 + "+" + "-"*12 + "+" + "-"*32 + "+" + "-"*17 + "+")
        return overall_success

    # --- W400 Specific Functions ---
    @test_wrapper("Checking Shelf I-Share Cable Status (W400)")
    def check_shelf_ishare_cable(self):
        device_map = {"PSU PMM": [32, 33], "BBU PMM": [16, 17]}
        headers = ["Device", "Address", "Property", "Value"]
        return self._check_and_display_in_table(device_map, "ISHARE_Cable_Connected", headers)

    @test_wrapper("Checking Power Source Detect (W400)")
    def check_power_source(self):
        output, exit_code = self.w400.run_command("rackmoncli list")
        return exit_code == 0

    @test_wrapper("Checking Power AC Loss Cable Detect (W400)")
    def check_power_ac_loss(self):
        device_map = {
            "BBU": list(range(48, 54)),
            "BBU Spare": list(range(58, 64))
        }
        headers = ["Device", "Address", "Property", "Value"]
        self._check_and_display_in_table(device_map, "AC_Loss_", headers)

    @test_wrapper("Checking Power Shelf Version (W400)")
    def check_power_shelf_version(self):
        device_map = {"BBU PMM": [16, 17], "PSU PMM": [32, 33]}
        headers = ["Device", "Address", "Property", "Value"]
        self._check_and_display_in_table(device_map, "PMM_FW_Revision", headers)

    @test_wrapper("Checking PSU and BBU Versions (W400)")
    def check_psu_bbu_versions(self):
        """
        Checks and displays firmware versions for all PSUs and BBUs in a compact table.
        """
        device_map = {
            "BBU": list(range(48, 54)), "BBU Spare": list(range(58, 64)),
            "PSU": list(range(144, 150)), "PSU Spare": list(range(154, 160))
        }
        overall_success = True
        results = []

        for device_type, addrs in device_map.items():
            for i, addr in enumerate(addrs):
                slot_name = f"{device_type} {i+1}"
                self._debug_print(f"Querying {slot_name} (Address {addr}) for FW versions...")
                command = f"rackmoncli data --dev-addr {addr} --latest | grep -i 'FW_Revision'"
                output, exit_code = self.w400.run_command(command, print_output=False)

                # Initialize with N/A
                res = {'device': slot_name, 'addr': addr, 'main_fw': 'N/A', 'secondary_fw': 'N/A'}

                if exit_code == 0 and output.strip():
                    for line in output.strip().splitlines():
                        try:
                            prop, val = [x.strip() for x in line.split(":", 1)]
                            if 'Battery_Pack_FW_Revision' in prop:
                                res['secondary_fw'] = val
                            elif 'PSU_FBL_FW_Revision' in prop:
                                res['secondary_fw'] = val
                            elif 'FW_Revision' in prop: # Generic/main FW
                                res['main_fw'] = val
                        except ValueError:
                            overall_success = False
                            print(f"{Colors.RED}[ FAIL ]{Colors.NC} Could not parse version from line: {line}")
                            continue
                else:
                    print(f"{Colors.RED}[ FAIL ]{Colors.NC} Could not retrieve version for {slot_name} (Address {addr}).")
                    overall_success = False
                results.append(res)

        # Print table
        print(f"| {'Device':<18} | {'Address':<10} | {'Main FW':<20} | {'Secondary/FBL FW':<20} |")
        print("+" + "-"*20 + "+" + "-"*12 + "+" + "-"*22 + "+" + "-"*22 + "+")
        for res in results:
            print(f"| {res['device']:<18} | {res['addr']:<10} | {res['main_fw']:<20} | {res['secondary_fw']:<20} |")
        print("+" + "-"*20 + "+" + "-"*12 + "+" + "-"*22 + "+" + "-"*22 + "+")
        return overall_success

    @test_wrapper("Checking Power FRU Info (W400)")
    def check_power_fru_info(self):
        addrs = [16, 17, 32, 33] + list(range(144, 150)) + list(range(154, 160))
        for addr in addrs:
            print(f"{Colors.YELLOW}Checking dev-addr {addr}:{Colors.NC}")
            self.w400.run_command(f"rackmoncli data --dev-addr {addr} --latest")

    @test_wrapper("Checking Wedge400 FRU Information")
    def check_w400_fru_info(self):
        self.w400.run_command("weutil; seutil; bsm-eutil; psu-util psu2 --get_eeprom_info")

    @test_wrapper("Checking AALC Leakage Sensor Status (W400)")
    def check_aalc_leakage_sensor_status(self):
        print(f"{Colors.YELLOW}Checking dev-addr 12 for AALC Leakage sensor status:{Colors.NC}")
        output, exit_code = self.w400.run_command("/usr/local/bin/rackmoncli read 12 0x9202")
        if exit_code != 0 or not output.strip():
            print(f"{Colors.RED}Could not read AALC Leakage Sensor status.{Colors.NC}")
            return False
        overall_success = True
        try:
            value = int(output.strip(), 16)
            # Bit descriptions based on the provided mapping
            descriptions = [
                "ITRack chassis0 Leakage", "ITRack chassis1 Leakage",
                "ITRack chassis2 Leakage", "ITRack chassis3 Leakage",
                "RPU Internal Leakage Abnormal", "RPU External Leakage Abnormal",
                "RPU Opt Leakage 1 Abnormal", "RPU Opt Leakage 2 Abnormal",
                "HEX Internal Leakage (GPO)", "HEX External Leakage (GPO)",
                "HEX Internal Leakage(Relay)", "HEX External Leakage(Relay)",
                "HEX Rack Pan Leakage Error", "HEX Rack Floor Leakage Error"
            ]

            print("\n--- Parsed Leakage Sensor Status (1 = Abnormal) ---")
            for i in range(len(descriptions)):
                # Check if the i-th bit is set
                is_abnormal = (value >> i) & 1
                
                description = descriptions[i]
                if is_abnormal:
                    overall_success = False
                    status_text = "Abnormal"
                    print(f"{Colors.RED}[ FAIL ]{Colors.NC} {description:<35}: {status_text}")
                else:
                    status_text = "Normal"
                    print(f"{Colors.GREEN}[  OK  ]{Colors.NC} {description:<35}: {status_text}")

        except (ValueError, IndexError):
            print(f"{Colors.RED}[ FAIL ] Failed to parse the hexadecimal output: '{output.strip()}'{Colors.NC}")
            overall_success = False
        return overall_success

    @test_wrapper("Checking ALLC Sensor Status (W400)")
    def check_aalc_sensor_status(self):
        print(f"{Colors.YELLOW}Checking dev-addr 12 for ALLC sensor status:{Colors.NC}")
        cmd = "rackmoncli data --dev-addr 12 | grep -E 'TACH_RPM|temp|Hum_Pct_RH|HSC_P48V|Alarm'"
        output, exit_code = self.w400.run_command(cmd)
        return exit_code == 0

    # --- W400 x86 Specific Functions ---
    @test_wrapper("Checking x86 CPU and Memory Info (W400 x86)")
    def check_x86_resources(self):
        output, exit_code = self.w400_x86.run_command("lscpu | grep 'Model name'; free -h")
        return exit_code == 0 # pylint: disable=line-too-long

    @test_wrapper("Checking Wedge400 x86 SW/FW Versions")
    def check_w400_x86_versions(self):
        cmd = """
            echo "--- Common Versions ---"; (cd /usr/local/cls_diag/rack/ && ./cls_version); (cd /usr/local/cls_diag/bin && ./cel-version-test --show); echo "--- SSD Version ---"; (cd /usr/local/cls_diag/bin/ && ./cel-nvme-test -i | grep 'Version'); echo "--- SDK Version ---"; (cd /usr/local/cls_diag/SDK/ && cat Version);
        """
        output, exit_code = self.w400_x86.run_command(cmd)
        return exit_code == 0 # pylint: disable=line-too-long

    @test_wrapper("Checking Wedge400 Optical Module Information")
    def check_w400_optic_module_info(self):
        if not self.w400_x86:
            print(f"{Colors.RED}W400 x86 client is not connected. Cannot run this test.{Colors.NC}")
            return

        base_cmd = "cd /usr/local/cls_diag/bin/; ./cel-qsfp-test"
        reset_on_cmd = f"{base_cmd} -p0 --reset=off"
        status_cmd = f"{base_cmd} -s"
        monitor_cmd = f"{base_cmd} -i"
        reset_off_cmd = f"{base_cmd} -p0 --reset=on"
        overall_success = True
        try:
            if self.debug: print(f"{Colors.YELLOW}Opening OM...{Colors.NC}")
            output, exit_code = self.w400_x86.run_command(reset_on_cmd)
            if exit_code != 0: overall_success = False
            if self.debug: print(f"\n{Colors.YELLOW}Reading OM status...{Colors.NC}")
            output, exit_code = self.w400_x86.run_command(status_cmd)
            if exit_code != 0: overall_success = False
            if self.debug: print(f"\n{Colors.YELLOW}Reading OM info...{Colors.NC}")
            output, exit_code = self.w400_x86.run_command(monitor_cmd)
            if exit_code != 0: overall_success = False
        finally:
            if self.debug: print(f"\n{Colors.YELLOW}Cleaning up: Turning port reset off...{Colors.NC}")
            output, exit_code = self.w400_x86.run_command(reset_off_cmd)
            if exit_code != 0: overall_success = False
        return overall_success

    @test_wrapper("Checking Wedge400 Sensor Status (W400 x86)")
    def check_w400_sensor_status(self):
        output, exit_code = self.w400_x86.run_command("cd /mnt/data1/BMC_Diag/bin && ./cel-sensor-test -s")
        return exit_code == 0 # pylint: disable=line-too-long

    # --- TH6 Specific Functions (Direct SSH) ---
    @test_wrapper("Checking TH6 Version")
    def check_th6_version(self):
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True
        command = 'python3 -c "from unidiag2.modules.version.version_icecube import show_version_inner; show_version_inner()"'
        return self._run_commands_on_clients_parallel(self.th6_clients, command, "Checking Version on TH6-")

    @test_wrapper("Checking TH6 Disk Usage")
    def check_th6_disk_usage(self):
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True
        return self._run_commands_on_clients_parallel(self.th6_clients, "df -h", "Checking Disk Usage on TH6-")

    @test_wrapper("Checking TH6 1.6T Optical Module Version)")
    def check_th6_optical_module_version(self):
        # This is an RMC command, so it's not parallelized across TH6 clients.
        # It's a single command on the RMC.
        output, exit_code = self.rmc.run_command("unidiag_cli osfp prbs get 3")
        return exit_code == 0 # pylint: disable=line-too-long

    @test_wrapper("Checking TH6 Transceiver Status")
    def check_th6_transceiver_status(self):
        """
        Checks Present, Low Power, and Reset status for all transceivers on each TH6 blade
        and displays the results in a table.
        """
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True

        command = "for f in /sys/bus/auxiliary/devices/fboss_iob_pci.xcvr_ctrl.*/xcvr_*; do echo \"$f:$(cat $f)\"; done"
        all_results = self._run_commands_and_get_output_parallel(self.th6_clients, command)
        
        overall_test_success = True
        for i, th6_client in enumerate(self.th6_clients, 1):
            hostname = th6_client.hostname
            output, exit_code = all_results.get(hostname, ("", -1))
            print(f"\n{Colors.CYAN}--- Transceiver Status on TH6-{i} ({hostname}) ---{Colors.NC}")
            port_data = {}
            if exit_code == 0 and output.strip():
                for line in output.strip().splitlines():
                    try:
                        path, value = line.split(':', 1)
                        parts = path.strip().split('_')
                        port_num = int(parts[-1])
                        attr_type = parts[-2]

                        if port_num not in port_data:
                            port_data[port_num] = {'present': 'N/A', 'low_power': 'N/A', 'reset': 'N/A'}
                        
                        port_data[port_num][attr_type] = value.strip() # pylint: disable=unused-variable
                    except ValueError:
                        continue
            else:
                print(f"{Colors.RED}[ FAIL ] Could not retrieve transceiver status for this device.{Colors.NC}")
                overall_test_success = False
                continue
            
            # Print table for this client
            print(f"| {'Port':<6} | {'Present':<18} | {'Power Mode':<18} | {'Reset State':<18} |")
            print("+" + "-"*8 + "+" + "-"*20 + "+" + "-"*20 + "+" + "-"*20 + "+")
            
            has_failure = False
            for port in sorted(port_data.keys()):
                data = port_data[port]
                
                # Active low: 0 means present
                present_val = data['present']
                present_str = f"{Colors.GREEN}Present{Colors.NC}" if present_val == '0x0' else f"{Colors.RED}Not Present{Colors.NC}"
                present_padding = 18 - get_visible_length(present_str)
                if present_val != '0x0':
                    has_failure = True

                # 1 means low power
                lp_val = data['low_power']
                lp_str = f"{Colors.YELLOW}Low Power{Colors.NC}" if lp_val == '0x1' else f"{Colors.GREEN}High Power{Colors.NC}"
                lp_padding = 18 - get_visible_length(lp_str)

                # 1 means reset is asserted
                reset_val = data['reset']
                reset_str = f"{Colors.YELLOW}Reset Asserted{Colors.NC}" if reset_val == '0x1' else f"{Colors.GREEN}Released{Colors.NC}"
                reset_padding = 18 - get_visible_length(reset_str)

                print(f"| {port:<6} | {present_str}{' ' * present_padding} | "
                      f"{lp_str}{' ' * lp_padding} | "
                      f"{reset_str}{' ' * reset_padding} |")

            print("+" + "-"*8 + "+" + "-"*20 + "+" + "-"*20 + "+" + "-"*20 + "+")
            if has_failure:
                print(f"{Colors.RED}[ FAIL ] One or more ports are not present.{Colors.NC}")
                overall_test_success = False

        return overall_test_success

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
            else: # pylint: disable=unused-variable
                print(f"{Colors.RED}Invalid choice. Please enter 'reset' or 'release'.{Colors.NC}")

        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True
        command = f"for f in /sys/bus/auxiliary/devices/fboss_iob_pci.xcvr_ctrl.*/xcvr_reset_*; do echo {value} > \"$f\" && echo \"Set $f to {value}\"; done"
        return self._run_commands_on_clients_parallel(self.th6_clients, command, f"Setting Reset Mode to '{mode_choice}' on TH6-")

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
            else: # pylint: disable=unused-variable
                print(f"{Colors.RED}Invalid choice. Please enter 'low' or 'high ' power.{Colors.NC}")

        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True
        command = f"for f in /sys/bus/auxiliary/devices/fboss_iob_pci.xcvr_ctrl.*/xcvr_low_power_*; do echo {value} > \"$f\" && echo \"Set $f to {value}\"; done"
        return self._run_commands_on_clients_parallel(self.th6_clients, command, f"Setting Low Power Mode to '{mode_choice}' on TH6-")

    @test_wrapper("Checking PSU Power Consumption (W400)")
    def check_psu_power_consumption(self):
        """
        Checks and displays the input and output power for each PSU in a table format.
        """
        psu_map = {
            "PSU Shelf 1": list(range(144, 150)), # 0x90-0x95
            "PSU Shelf 2": list(range(154, 160))  # 0x9A-0x9F
        }
        power_data = []
        total_input = 0.0
        overall_success = True # pylint: disable=unused-variable
        total_output = 0.0

        for shelf_name, addrs in psu_map.items():
            for i, addr in enumerate(addrs):
                slot_name = f"PSU {i+1}"
                psu_info = {'shelf': shelf_name, 'slot': slot_name, 'addr': addr, 'input': None, 'output': None}
                self._debug_print(f"Querying {shelf_name} {slot_name} (Address {addr}) for Input Power...")
                # Get Input Power
                input_cmd = f"rackmoncli reload --dev-addr {addr}; rackmoncli data --dev-addr {addr} | grep -w 'PSU_Input_Power'"
                input_output, input_exit_code = self.w400.run_command(input_cmd, print_output=False)
                if input_exit_code == 0 and input_output.strip():
                    try:
                        for line in input_output.strip().splitlines():
                            # Regex to match "PSU_Input_Power<...>: 123.45" or "PSU_Input_Power : 123.45"
                            match = re.search(r'PSU_Input_Power.*:\s*([\d.]+)', line)
                            if match:
                                value_str = match.group(1)
                                value = float(value_str)
                                psu_info['input'] = value
                                total_input += value
                                break
                    except (ValueError, IndexError) as e:
                        self._debug_print(f"Error parsing input power for {slot_name}: {e}") # pylint: disable=line-too-long
                        overall_success = False # pylint: disable=unused-variable
                else:
                    print(f"{Colors.RED}[ FAIL ]{Colors.NC} Could not read Input Power for {shelf_name} {slot_name} (Addr {addr})")
                    overall_success = False

                self._debug_print(f"Querying {shelf_name} {slot_name} (Address {addr}) for Output Power...")
                # Get Output Power
                output_cmd = f"rackmoncli reload --dev-addr {addr}; rackmoncli data --dev-addr {addr} | grep -w 'PSU_Output_Power'"
                output_output, output_exit_code = self.w400.run_command(output_cmd, print_output=False)
                if output_exit_code == 0 and output_output.strip():
                    try:
                        for line in output_output.strip().splitlines():
                            # Regex to match "PSU_Output_Power<...>: 123.45" or "PSU_Output_Power : 123.45"
                            match = re.search(r'PSU_Output_Power.*:\s*([\d.]+)', line)
                            if match:
                                value_str = match.group(1)
                                value = float(value_str)
                                psu_info['output'] = value
                                total_output += value
                                break
                    except (ValueError, IndexError) as e:
                        self._debug_print(f"Error parsing output power for {slot_name}: {e}") # pylint: disable=line-too-long
                        overall_success = False # pylint: disable=unused-variable
                else:
                    print(f"{Colors.RED}[ FAIL ]{Colors.NC} Could not read Output Power for {shelf_name} {slot_name} (Addr {addr})")
                    overall_success = False

                power_data.append(psu_info)

        # Print the results in a table
        print("\n" + "-"*80)
        print(f"| {'Shelf':<14} | {'Slot':<8} | {'Address':<12} | {'Input Power (W)':>18} | {'Output Power (W)':>19} |")
        print("+" + "-"*16 + "+" + "-"*10 + "+" + "-"*14 + "+" + "-"*20 + "+" + "-"*21 + "+")
        for psu in power_data:
            addr_str = f"{psu['addr']} ({psu['addr']:#04x})"
            input_val_str = f"{psu['input']:.3f}" if psu['input'] is not None else "N/A"
            output_val_str = f"{psu['output']:.3f}" if psu['output'] is not None else "N/A"
            
            # Add color and handle padding for non-printable characters
            colored_input = f"{Colors.YELLOW}{input_val_str}{Colors.NC}".rjust(18 + len(Colors.YELLOW) + len(Colors.NC))
            colored_output = f"{Colors.GREEN}{output_val_str}{Colors.NC}".rjust(19 + len(Colors.GREEN) + len(Colors.NC))
            print(f"| {psu['shelf']:<14} | {psu['slot']:<8} | {addr_str:<12} | {colored_input} | {colored_output} |")
        print("+" + "-"*16 + "+" + "-"*10 + "+" + "-"*14 + "+" + "-"*20 + "+" + "-"*21 + "+")
        colored_total_input = f"{Colors.YELLOW}{total_input:.3f}{Colors.NC}".rjust(18 + len(Colors.YELLOW) + len(Colors.NC))
        colored_total_output = f"{Colors.GREEN}{total_output:.3f}{Colors.NC}".rjust(19 + len(Colors.GREEN) + len(Colors.NC))
        print(f"| {'Totals':<40} | {colored_total_input} | {colored_total_output} |")
        print("+" + "-"*42 + "+" + "-"*20 + "+" + "-"*21 + "+")
        return overall_success

    @test_wrapper("Checking Total PSU Input Power (W400)")
    def check_psu_input_power(self):
        command = "rackmoncli reload --dev-addr {addr}; rackmoncli data --dev-addr {addr} | grep -w PSU_Input_Power" # pylint: disable=unused-variable
        output, exit_code = self.w400.run_command(command, print_output=True) # Print output for this one

    @test_wrapper("Checking TH6 Fan PWM Values")
    def check_fan_pwm_values(self):
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True
        # The awk command's single quotes need to be escaped for the outer shell wrapper.
        # ' -> '\''
        command = "for f in /sys/class/hwmon/hwmon*/pwm[1-4]; do val=$(cat \"$f\"); percent=$(awk -v v=\"$val\" 'BEGIN { printf \"%.0f\", (v / 64) * 100 }'); echo \"$f: $val ($percent%)\"; done".replace("'", "'\\''")
        return self._run_commands_on_clients_parallel(
            self.th6_clients, command, "Checking Fan PWM on TH6-"
        )

    @test_wrapper("Set TH6 Fan PWM Value")
    def set_fan_pwm_value(self):
        # Get PWM channel from user
        while True:
            channel_choice = input("Enter PWM channel to set (1-4, or 'all'): ").lower()
            if channel_choice == 'all' or (channel_choice.isdigit() and 1 <= int(channel_choice) <= 4):
                break
            else:
                print(f"{Colors.RED}Invalid input. Please enter a number from 1-4 or 'all'.{Colors.NC}") # pylint: disable=line-too-long

        # Get PWM value from user
        while True:
            try:
                pwm_value = int(input("Enter PWM value to set (0-64): "))
                if 0 <= pwm_value <= 64:
                    break
                else: # pylint: disable=unused-variable
                    print(f"{Colors.RED}Invalid value. Please enter a number between 0 and 64.{Colors.NC}")
            except ValueError: # pylint: disable=unused-variable
                print(f"{Colors.RED}Invalid input. Please enter a number.{Colors.NC}")

        target_glob = "pwm[1-4]" if channel_choice == 'all' else f"pwm{channel_choice}"
        command = f"for f in /sys/class/hwmon/hwmon*/{target_glob}; do echo {pwm_value} > \"$f\" && echo \"Set $f to {pwm_value}\"; done"

        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True
        return self._run_commands_on_clients_parallel(
            self.th6_clients, command, f"Setting Fan PWM to '{pwm_value}' on TH6-"
        )

    @test_wrapper("Checking TH6 Fan Speed (RPM)")
    def check_fan_speed_rpm(self):
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True
        command = "for f in /sys/class/hwmon/hwmon*/fan*_input; do echo -n \"$f: \"; cat \"$f\"; done"
        return self._run_commands_on_clients_parallel(
            self.th6_clients, command, "Checking Fan RPM on TH6-"
        )

    @test_wrapper("Checking TH6 BMC Versions")
    def check_th6_bmc_versions(self):
        if not self.th6_bmc_clients:
            print(f"{Colors.YELLOW}No TH6 BMCs configured or connected.{Colors.NC}")
            return True
        command = "cat /etc/os-release; cat /etc/issue"
        return self._run_commands_on_clients_parallel(
            self.th6_bmc_clients, command, "Checking Versions on TH6 BMC-"
        )
 
    @test_wrapper("Checking TH6 OM DSP Temperature")
    def check_th6_om_dsp_temperature(self):
        """
        Reads the DSP temperature on each TH6 blade using unidiag and displays it in a matrix.
        """
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True

        # Use the unified helper to get parsed data
        all_parsed_data = self._get_and_parse_th6_om_temps()

        overall_test_success = True
        for i, th6_client in enumerate(self.th6_clients, 1):
            hostname = th6_client.hostname
            device_name = f"TH6-{i} ({hostname})"
            parsed_data = all_parsed_data.get(hostname)

            if parsed_data and parsed_data.get("success"):
                dsp_temps = {item['port']: item['dsp_temp_val'] for item in parsed_data['data'] if item.get('dsp_temp_val') is not None}
                e65_temp = parsed_data.get('e65_temp', 'N/A')
                self._print_th6_om_dsp_temperature_table(device_name, dsp_temps, e65_temp)
                if not dsp_temps:
                    print(f"{Colors.RED}[ FAIL ] No DSP temperature data could be parsed for {device_name}.{Colors.NC}")
                    overall_test_success = False
            else:
                print(f"\n{Colors.RED}[ FAIL ] Failed to get temperature data for {device_name}.{Colors.NC}")
                overall_test_success = False

        return overall_test_success

    def _build_dsp_temp_matrix(self, dsp_temps):
        """
        Organizes the flat DSP temperature data into a 2D matrix for display.
        Returns a list of lists (rows) representing the temperature matrix.
        """
        # The first row defines the starting port for each column.
        column_starts = [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61]
        matrix = []
        # There are 4 rows in the physical layout.
        for row_index in range(4):
            row_data = []
            for col_start_port in column_starts:
                # Calculate the port number for the current cell.
                port_num = col_start_port + row_index
                port_key = f"E{port_num}"
                temp_val = dsp_temps.get(port_key, "N/A")
                row_data.append(temp_val)
            matrix.append(row_data)
        return matrix

    def _format_and_print_matrix(self, matrix, row_labels, col_labels, value_width=7):
        """
        A generic helper to print a 2D matrix with row and column labels.
        """
        label_width = max(len(label) for label in row_labels) + 2

        # Print header row
        header_str = f"{'':<{label_width}}" + " ".join([f"{h:>{value_width}}" for h in col_labels])
        print(header_str)

        # Print separator
        separator_length = label_width + (value_width + 1) * len(col_labels)
        print("-" * separator_length)

        # Print data rows
        for i, row in enumerate(matrix):
            row_label = row_labels[i]
            # Format each value in the row.
            formatted_values = [
                f"{val:>{value_width}.2f}" if isinstance(val, float) else f"{str(val):>{value_width}}"
                for val in row
            ]
            print(f"{row_label:<{label_width}}" + " ".join(formatted_values))

        print("-" * separator_length)

    def _print_th6_om_dsp_temperature_table(self, device_name, dsp_temps, e65_temp):
        """Refactored: Prints the formatted temperature table for a single TH6 device."""
        print(f"\n{Colors.CYAN}--- OM DSP Temperature on {device_name} ---{Colors.NC}")

        if not dsp_temps:
            print(f"{Colors.YELLOW}No DSP temperature data found or parsed.{Colors.NC}")
            return

        print(f"\n{Colors.BLUE}DSP Temperature Matrix (°C):{Colors.NC}")
        
        # 1. Organize the data into a matrix structure.
        temp_matrix = self._build_dsp_temp_matrix(dsp_temps)
        
        # 2. Define labels and print the matrix.
        col_labels = [f"E{p}" for p in [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61]]
        row_labels = [f"Row {i+1}" for i in range(4)]
        self._format_and_print_matrix(temp_matrix, row_labels, col_labels)

        # Print E65 separately
        e65_str = f"{e65_temp:.2f}" if isinstance(e65_temp, float) else e65_temp
        print(f"E65 Temperature: {Colors.YELLOW}{e65_str}{Colors.NC} °C")

    def _print_th6_om_temperature_table(self, device_name, om_temps):
        """Prints the formatted OM temperature table for a single TH6 device."""
        print(f"\n{Colors.CYAN}--- OM Temperature on {device_name} ---{Colors.NC}")

        if not om_temps:
            print(f"{Colors.YELLOW}No OM temperature data found or parsed.{Colors.NC}")
            return

        print(f"\n{Colors.BLUE}OM Temperature Matrix (°C):{Colors.NC}")

        # 1. Organize the data into a matrix structure.
        temp_matrix = self._build_dsp_temp_matrix(om_temps)

        # 2. Define labels and print the matrix.
        col_labels = [f"E{p}" for p in [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61]]
        row_labels = [f"Row {i+1}" for i in range(4)]
        self._format_and_print_matrix(temp_matrix, row_labels, col_labels)

    @test_wrapper("Checking TH6 OM Temperature")
    def check_th6_om_temperature(self):
        """
        Reads the OM temperature summary on each TH6 blade and displays it in a table.
        """
        all_parsed_data = self._get_and_parse_th6_om_temps()

        overall_test_success = True
        for i, th6_client in enumerate(self.th6_clients, 1):
            hostname = th6_client.hostname
            device_name = f"TH6-{i} ({hostname})"
            parsed_data = all_parsed_data.get(hostname)

            if parsed_data and parsed_data.get("success"):
                om_temps = {item['port']: float(item['temp']) for item in parsed_data['data'] if item.get('temp')}
                self._print_th6_om_temperature_table(device_name, om_temps)
                if not om_temps: # If parsing failed to find any data
                    print(f"{Colors.RED}[ FAIL ] No OM temperature data could be parsed for {device_name}.{Colors.NC}")
                    overall_test_success = False
            else:
                print(f"\n{Colors.RED}[ FAIL ] Failed to get temperature data for {device_name}.{Colors.NC}")
                overall_test_success = False

        return overall_test_success

    def _get_and_parse_th6_om_temps(self):
        """
        A unified helper to run the temperature command on all TH6 clients once
        and parse the output into a structured dictionary.
        """
        command = 'python3 -c "from unidiag2.modules.osfp.osfp_icecube import show_OSFP_QSFP_temperature; show_OSFP_QSFP_temperature()"'
        all_raw_results = self._run_commands_and_get_output_parallel(self.th6_clients, command)
        
        all_parsed_data = {}
        for hostname, (output, exit_code) in all_raw_results.items():
            parsed_items = []
            e65_temp_val = "N/A"
            success = False

            if exit_code == 0 and output.strip():
                success = True
                for line in output.strip().splitlines():
                    # Try parsing the summary line format first
                    summary_match = self.OM_TEMP_REGEX.match(line)
                    if summary_match:
                        dsp_temp_val = None
                        try:
                            if summary_match.group(4) != 'N/A':
                                dsp_temp_val = float(summary_match.group(4))
                        except ValueError:
                            pass  # Keep it as None

                        parsed_items.append({
                            "port": summary_match.group(1),
                            "present": summary_match.group(2),
                            "temp": summary_match.group(3),
                            "dsp_temp": summary_match.group(4), # The string version for display
                            "dsp_temp_val": dsp_temp_val,      # The float version for matrix
                            "lpmode": summary_match.group(5)
                        })
 
                    # Also parse for the E65 temperature
                    e65_match = self.PORT_DSP_TEMP_REGEX.match(line)
                    if e65_match and e65_match.group(1) == "E65":
                        try:
                            e65_temp_val = float(e65_match.group(2))
                        except ValueError:
                            pass  # Keep as "N/A"

            all_parsed_data[hostname] = {
                "success": success,
                "data": parsed_items,
                "e65_temp": e65_temp_val,
                "output": output # Keep raw output for debugging
            }
        return all_parsed_data

    @test_wrapper("Checking TH6 Fan Status")
    def check_th6_fan_status(self):
        """Checks and displays Fan PWM values and RPM for each TH6 blade in a table.
        This function runs commands in parallel and aggregates the results.
        """
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True

        # Combine commands to run them in a single SSH session per host
        pwm_command = "for f in /sys/class/hwmon/hwmon*/pwm[1-4]; do val=$(cat \"$f\"); percent=$(awk -v v=\"$val\" 'BEGIN { printf \"%.0f\", (v / 64) * 100 }'); echo \"PWM_DATA:$f: $val ($percent%)\"; done".replace("'", "'\\''")
        rpm_command = "for f in /sys/class/hwmon/hwmon*/fan*_input; do echo -n \"RPM_DATA:$f: \"; cat \"$f\"; done"
        combined_command = f"{pwm_command}; {rpm_command}"

        all_results = self._run_commands_and_get_output_parallel(self.th6_clients, combined_command)

        # --- Data Parsing ---
        parsed_data = {}
        for i, client in enumerate(self.th6_clients, 1):
            hostname = client.hostname
            device_name = f"TH6-{i}"
            output, exit_code = all_results.get(hostname, ("", -1))
            
            fan_data = {} # {fan_id: {'pwm_raw': ..., 'pwm_percent': ..., 'rpm': ...}}
            if exit_code == 0 and output:
                for line in output.strip().splitlines():
                    if line.startswith("PWM_DATA:"):
                        match = re.search(r'pwm(\d+):\s+(\d+)\s+\((\d+)%\)', line)
                        if match:
                            pwm_id, pwm_raw, pwm_percent = match.groups()
                            fan_id1 = (int(pwm_id) - 1) * 2 + 1
                            fan_id2 = (int(pwm_id) - 1) * 2 + 2
                            fan_data.setdefault(fan_id1, {}).update({'pwm_raw': pwm_raw, 'pwm_percent': f"{pwm_percent}%"})
                            fan_data.setdefault(fan_id2, {}).update({'pwm_raw': pwm_raw, 'pwm_percent': f"{pwm_percent}%"})
                    elif line.startswith("RPM_DATA:"):
                        match = re.search(r'fan(\d+)_input:\s+(\d+)', line)
                        if match:
                            fan_id, rpm_val = match.groups()
                            fan_data.setdefault(int(fan_id), {}).update({'rpm': rpm_val})
            parsed_data[device_name] = fan_data

        # --- Table Rendering ---
        sorted_device_names = sorted(parsed_data.keys(), key=lambda name: int(name.split('-')[1]))

        # Determine all unique fan IDs across all devices
        all_fan_ids = sorted(list(set(fan_id for data in parsed_data.values() for fan_id in data.keys()))) # lgtm [py/comprehension-to-generator]
        if not all_fan_ids:
            print(f"{Colors.YELLOW}No fan data could be retrieved from any TH6 device.{Colors.NC}")
            return False

        overall_success = True

        # --- New: Split devices into chunks for multiple tables ---
        num_devices = len(sorted_device_names)
        # Calculate chunk size to aim for 3 tables, with a minimum of 1 device per table.
        devices_per_table = (num_devices + 2) // 3 if num_devices > 0 else 1
        device_chunks = [sorted_device_names[i:i + devices_per_table] for i in range(0, num_devices, devices_per_table)]

        for chunk_index, device_chunk in enumerate(device_chunks):
            if not device_chunk: continue

            if chunk_index > 0:
                print("\n") # Add space between tables

            # Print Header for the current chunk
            header = f"| {'Fan ID':<8} |"
            for device_name in device_chunk:
                header += f" {device_name + ' (RPM/PWM%)':^18} |"
            print(header)

            # Print Separator for the current chunk
            separator = "+" + "-"*10 + "+"
            for _ in device_chunk:
                separator += "-"*20 + "+"
            print(separator)

            # Print Data Rows for the current chunk
            for fan_id in all_fan_ids:
                row_str = f"| {fan_id:<8} |"
                for device_name in device_chunk:
                    fan_info = parsed_data[device_name].get(fan_id, {})
                    rpm = fan_info.get('rpm', 'N/A')
                    pwm = fan_info.get('pwm_percent', 'N/A')

                    # Determine status and color
                    is_fail = False
                    if rpm == 'N/A' or pwm == 'N/A':
                        is_fail = True
                    else:
                        try:
                            if int(rpm) <= 0:
                                is_fail = True
                        except ValueError:
                            is_fail = True # Not a valid number

                    if is_fail:
                        color = Colors.RED
                        overall_success = False
                    else:
                        color = Colors.GREEN

                    cell_content = f"{rpm} / {pwm}"

                    # Manually calculate padding to handle ANSI color codes correctly
                    visible_len = len(cell_content)
                    total_padding = 18 - visible_len
                    left_pad = total_padding // 2
                    right_pad = total_padding - left_pad
                    padded_cell = f"{' ' * left_pad}{color}{cell_content}{Colors.NC}{' ' * right_pad}"

                    row_str += f" {padded_cell} |"
                print(row_str)

            print(separator)

        if not overall_success:
            print(f"\n{Colors.RED}[ FAIL ] One or more fans reported an invalid status (RPM <= 0 or data N/A).{Colors.NC}")

        return overall_success

    def _parse_th6_power_output(self, output, device_name):
        """
        Parses the output of 'sensors_p.py' for a single TH6 device.
        Returns a dictionary with the extracted power data.
        """
        power_data = {
            'device': device_name,
            'ltc4287_pin': 'N/A', 'ltc4287_pout': 'N/A',
            'th6_pin': 'N/A', 'th6_pout': 'N/A',
            'om_pin': 'N/A', 'om_pout': 'N/A',
            'netlake_pin': 'N/A', 'netlake_pout': 'N/A',
            'fan_pin': 'N/A', 'fan_pout': 'N/A',
            'status': f"{Colors.RED}[FAIL]{Colors.NC}"
        }
        ltc_found = False
        summary_found = False
        fan_power_total = 0.0

        ltc4287_match = self.LTC4287_HSC_REGEX.search(output)
        if ltc4287_match:
            power_data['ltc4287_pin'] = float(ltc4287_match.group(1))
            power_data['ltc4287_pout'] = float(ltc4287_match.group(2))
            ltc_found = True
        else:
            self._debug_print(f"LTC4287_HSC not found for {device_name}.")

        for line in output.strip().splitlines():
            # New logic to parse and sum individual fan power from the "FAN HSC" section
            if "MCB_FAN" in line and "INA238" in line:
                try:
                    # The POWER1(W) is the 4th value on the line
                    fan_power_total += float(line.split()[3])
                except (ValueError, IndexError):
                    self._debug_print(f"Could not parse fan power from line: {line}")

            summary_match = self.POWER_SUMMARY_LINE_REGEX.search(line)
            if summary_match:
                category = summary_match.group(1).lower()
                pin = float(summary_match.group(2))
                pout = float(summary_match.group(3))
                if f'{category}_pin' in power_data:
                    power_data[f'{category}_pin'] = pin
                    power_data[f'{category}_pout'] = pout
                    # Special handling for 'om' as it might be missing
                    if category == 'om':
                        if pin == 0.0: power_data['om_pin'] = 0.0
                        if pout == 0.0: power_data['om_pout'] = 0.0

                    summary_found = True

        # If we successfully summed up fan power, update the data.
        # We use the same value for PIN and POUT for fans in this context.
        if fan_power_total > 0:
            power_data['fan_pin'] = fan_power_total
            power_data['fan_pout'] = fan_power_total

        if ltc_found and summary_found:
            power_data['status'] = f"{Colors.GREEN}[OK]{Colors.NC}"
        elif ltc_found or summary_found:
            power_data['status'] = f"{Colors.YELLOW}[PARTIAL]{Colors.NC}"

        return power_data

    def _print_pin_power_table(self, results):
        """Prints the PIN (Power Input) data in a formatted table."""
        DEVICE_COL_WIDTH, VALUE_COL_WIDTH, STATUS_COL_WIDTH = 7, 9, 12

        print(f"\n{Colors.BLUE}--- TH6 Power Input (PIN) ---{Colors.NC}")
        header_cols = ['Device', 'LTC4287', 'TH6', 'OM', 'NETLAKE', 'FAN', 'Status']
        print(f"| {header_cols[0]:<{DEVICE_COL_WIDTH}} | {header_cols[1]:^{VALUE_COL_WIDTH}} | {header_cols[2]:^{VALUE_COL_WIDTH}} | {header_cols[3]:^{VALUE_COL_WIDTH}} | {header_cols[4]:^{VALUE_COL_WIDTH}} | {header_cols[5]:^{VALUE_COL_WIDTH}} | {header_cols[6]:<{STATUS_COL_WIDTH}} |")

        DEVICE_SEP, VALUE_SEP, STATUS_SEP = "-" * (DEVICE_COL_WIDTH + 2), "-" * (VALUE_COL_WIDTH + 2), "-" * (STATUS_COL_WIDTH + 2)
        print("+" + DEVICE_SEP + (VALUE_SEP + "+") * 5 + STATUS_SEP + "+")

        total_power_summary = {key: 0.0 for key in ['ltc4287_pin', 'th6_pin', 'om_pin', 'netlake_pin', 'fan_pin']}
        def format_power_value(val):
            return f"{val:.3f}" if isinstance(val, float) else str(val)

        for data in results:
            for key in total_power_summary.keys():
                if isinstance(data.get(key), float):
                    total_power_summary[key] += data[key]

            status_display_len = get_visible_length(data['status'])
            padded_status = f"{data['status']}{' ' * (STATUS_COL_WIDTH - status_display_len)}"

            row_values = [format_power_value(data.get(key)) for key in total_power_summary.keys()]
            row_str = " | ".join([f"{v:>{VALUE_COL_WIDTH}}" for v in row_values])
            print(f"| {data['device']:<{DEVICE_COL_WIDTH}} | {row_str} | {padded_status} |")

        print("+" + DEVICE_SEP + (VALUE_SEP + "+") * 5 + STATUS_SEP + "+")

        total_label_str = f"{Colors.BLUE}TOTALS{Colors.NC}"
        total_label_padded = f"{total_label_str}{' ' * (DEVICE_COL_WIDTH - get_visible_length(total_label_str))}"

        total_power_fields = [f"{Colors.GREEN}{format_power_value(total_power_summary[key]):>{VALUE_COL_WIDTH}}{Colors.NC}" for key in total_power_summary.keys()]

        total_output_power = total_power_summary.get('ltc4287_pin', 0) + total_power_summary.get('fan_pin', 0) + 10.0
        total_output_power_str = f"{Colors.YELLOW}{total_output_power:.3f}{Colors.NC}"
        output_power_padding = STATUS_COL_WIDTH - get_visible_length(total_output_power_str)
        total_status_field = f"{total_output_power_str}{' ' * output_power_padding}"

        print(f"| {total_label_padded} | {' | '.join(total_power_fields)} | {total_status_field} |")
        print("+" + DEVICE_SEP + (VALUE_SEP + "+") * 5 + STATUS_SEP + "+")

    def _print_pout_power_table(self, results):
        """Prints the POUT (Power Output) data in a formatted table."""
        DEVICE_COL_WIDTH, VALUE_COL_WIDTH = 7, 9

        print(f"\n{Colors.BLUE}--- TH6 Power Output (POUT) ---{Colors.NC}")
        header_cols = ['Device', 'LTC4287', 'TH6', 'OM', 'NETLAKE', 'FAN']
        print(f"| {header_cols[0]:<{DEVICE_COL_WIDTH}} | {header_cols[1]:^{VALUE_COL_WIDTH}} | {header_cols[2]:^{VALUE_COL_WIDTH}} | {header_cols[3]:^{VALUE_COL_WIDTH}} | {header_cols[4]:^{VALUE_COL_WIDTH}} | {header_cols[5]:^{VALUE_COL_WIDTH}} |")

        DEVICE_SEP, VALUE_SEP = "-" * (DEVICE_COL_WIDTH + 2), "-" * (VALUE_COL_WIDTH + 2)
        print("+" + DEVICE_SEP + (VALUE_SEP + "+") * 5)

        total_power_summary = {key: 0.0 for key in ['ltc4287_pout', 'th6_pout', 'om_pout', 'netlake_pout', 'fan_pout']}
        def format_power_value(val):
            return f"{val:.3f}" if isinstance(val, float) else str(val)

        for data in results:
            for key in total_power_summary.keys():
                if isinstance(data.get(key), float):
                    total_power_summary[key] += data[key]

            row_values = [format_power_value(data.get(key)) for key in total_power_summary.keys()]
            row_str = " | ".join([f"{v:>{VALUE_COL_WIDTH}}" for v in row_values])
            print(f"| {data['device']:<{DEVICE_COL_WIDTH}} | {row_str} |")

        print("+" + DEVICE_SEP + (VALUE_SEP + "+") * 5)

        total_label_str = f"{Colors.BLUE}TOTALS{Colors.NC}"
        total_label_padded = f"{total_label_str}{' ' * (DEVICE_COL_WIDTH - get_visible_length(total_label_str))}"

        total_power_fields = [f"{Colors.GREEN}{format_power_value(total_power_summary[key]):>{VALUE_COL_WIDTH}}{Colors.NC}" for key in total_power_summary.keys()]

        print(f"| {total_label_padded} | {' | '.join(total_power_fields)} |")
        print("+" + DEVICE_SEP + (VALUE_SEP + "+") * 5)

    def _print_power_table_grand_total_row(self, results):
        """Prints the final grand total power consumption row, styled for the POUT table."""
        DEVICE_COL_WIDTH, VALUE_COL_WIDTH = 7, 9

        th6_total_power = sum(
            (data.get('ltc4287_pout', 0) or 0) +
            (data.get('th6_pout', 0) or 0) +
            (data.get('om_pout', 0) or 0) +
            (data.get('netlake_pout', 0) or 0) +
            (data.get('fan_pout', 0) or 0)
            for data in results
        )
        total_power_str = f"{Colors.CYAN}TH6 TOTAL POWER (POUT): {th6_total_power:.3f} W{Colors.NC}"

        # Calculate width based on the POUT table (Device + 5 value columns)
        total_table_width = DEVICE_COL_WIDTH + 2 + (VALUE_COL_WIDTH + 3) * 5

        # Center the text within the table's width, accounting for ANSI color codes
        visible_len = get_visible_length(total_power_str)
        total_padding = total_table_width - visible_len
        left_pad = total_padding // 2
        right_pad = total_padding - left_pad
        centered_total_str = f"{' ' * left_pad}{total_power_str}{' ' * right_pad}"

        print(f"|{centered_total_str}|")
        print("+" + "-" * total_table_width + "+")

    # --- Refactored TH6 Power Summary Helper Functions ---

    def _get_th6_power_data_parallel(self):
        """
        Runs 'sensors_p.py' on all TH6 clients in parallel and parses the output.
        Returns a list of parsed data dictionaries and the overall success status.
        """
        command = "sensors_p.py"
        all_results = self._run_commands_and_get_output_parallel(self.th6_clients, command)

        parsed_results = []
        overall_test_success = True

        # Sort clients by hostname to ensure consistent ordering in the final table
        sorted_clients = sorted(self.th6_clients, key=lambda c: c.hostname)

        for i, th6_client in enumerate(sorted_clients, 1):
            hostname = th6_client.hostname
            output, exit_code = all_results.get(hostname, ("", -1))
            device_name = f"TH6-{i}"

            if exit_code == 0 and output.strip():
                power_data = self._parse_th6_power_output(output, device_name)
                if f"{Colors.RED}[FAIL]" in power_data['status']:
                    overall_test_success = False
            else:
                self._debug_print(f"Failed to run sensors_p.py on {hostname} or output was empty.")
                power_data = self._parse_th6_power_output("", device_name) # Create a failed entry
                overall_test_success = False

            parsed_results.append(power_data)
        
        return parsed_results, overall_test_success

    def _parse_th6_power_output(self, output, device_name):
        """
        Parses the output of 'sensors_p.py' for a single TH6 device.
        Delegates parsing to smaller helper functions.
        """
        power_data = {
            'device': device_name,
            'ltc4287_pin': 'N/A', 'ltc4287_pout': 'N/A',
            'th6_pin': 'N/A', 'th6_pout': 'N/A',
            'om_pin': 'N/A', 'om_pout': 'N/A',
            'netlake_pin': 'N/A', 'netlake_pout': 'N/A',
            'fan_pin': 'N/A', 'fan_pout': 'N/A',
            'status': f"{Colors.RED}FAIL{Colors.NC}"
        }
        
        ltc_found = self._parse_ltc4287_power(output, power_data)
        summary_found = self._parse_summary_power(output, power_data)
        self._parse_and_sum_fan_power(output, power_data)

        if ltc_found and summary_found:
            power_data['status'] = f"{Colors.GREEN}OK{Colors.NC}"
        elif ltc_found or summary_found:
            power_data['status'] = f"{Colors.YELLOW}PARTIAL{Colors.NC}"

        return power_data

    def _parse_ltc4287_power(self, output, power_data):
        """Parses the LTC4287 HSC power from the sensor output."""
        ltc4287_match = self.LTC4287_HSC_REGEX.search(output)
        if ltc4287_match:
            power_data['ltc4287_pin'] = float(ltc4287_match.group(1))
            power_data['ltc4287_pout'] = float(ltc4287_match.group(2))
            return True
        self._debug_print(f"LTC4287_HSC not found for {power_data['device']}.")
        return False

    def _parse_and_sum_fan_power(self, output, power_data):
        """Parses and sums the individual fan power values."""
        fan_power_total = 0.0
        for line in output.strip().splitlines():
            if "MCB_FAN" in line and "INA238" in line:
                try:
                    fan_power_total += float(line.split()[3])
                except (ValueError, IndexError):
                    self._debug_print(f"Could not parse fan power from line: {line}")
        
        if fan_power_total > 0:
            power_data['fan_pin'] = fan_power_total
            power_data['fan_pout'] = fan_power_total

    def _parse_summary_power(self, output, power_data):
        """Parses the main power summary table from the sensor output."""
        summary_found = False
        for line in output.strip().splitlines():
            summary_match = self.POWER_SUMMARY_LINE_REGEX.search(line)
            if summary_match:
                category = summary_match.group(1).lower()
                pin = float(summary_match.group(2))
                pout = float(summary_match.group(3))
                if f'{category}_pin' in power_data:
                    power_data[f'{category}_pin'] = pin
                    power_data[f'{category}_pout'] = pout
                    if category == 'om' and pin == 0.0 and pout == 0.0:
                        power_data['om_pin'] = 0.0
                        power_data['om_pout'] = 0.0
                    summary_found = True
        return summary_found

    def run_all_w400_tests(self):
        print(f"\n{Colors.BLUE}======================================={Colors.NC}") # pylint: disable=unused-variable
        print(f"{Colors.BLUE}   Running All W400 Diagnostic Tests   {Colors.NC}")
        print(f"{Colors.BLUE}======================================={Colors.NC}")
        self.check_power_source()
        self.check_shelf_ishare_cable() # Updated to new combined function
        self.check_power_ac_loss()
        self.check_power_shelf_version()
        self.check_psu_bbu_versions()
        self.check_power_fru_info()
        self.check_aalc_sensor_status()
        self.check_w400_fru_info()
        self.check_aalc_leakage_sensor_status()
        self.check_w400_sensor_status()
        print(f"\n{Colors.GREEN}All W400 tests complete.{Colors.NC}")

    @test_wrapper("Checking TH6 Power Summary")
    def check_th6_power_summary(self):
        """
        Runs 'sensors_p.py' on each TH6 blade, extracts power data,
        and displays the results in a tabular format.
        """
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return True

        parsed_results, overall_test_success = self._get_th6_power_data_parallel()

        if parsed_results:
            # Print the power data in two separate, narrower tables for readability.
            self._print_pin_power_table(parsed_results)
            print("\n") # Add a newline for spacing
            self._print_pout_power_table(parsed_results)
            self._print_power_table_grand_total_row(parsed_results)

        return overall_test_success

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
        print(f"\n{Colors.BLUE}======================================={Colors.NC}") # pylint: disable=unused-variable
        print(f"{Colors.BLUE}    Running All TH6 Diagnostic Tests   {Colors.NC}")
        print(f"{Colors.BLUE}======================================={Colors.NC}")
        if not self.th6_clients:
            print(f"{Colors.YELLOW}No TH6 devices configured or connected.{Colors.NC}")
            return
        # These tests run in parallel on all TH6 clients
        self.check_th6_version()
        self.check_th6_disk_usage()
        self.check_th6_transceiver_status()
        self.check_th6_fan_status()
        self.check_th6_om_dsp_temperature()
        self.check_th6_om_temperature()
        self.check_th6_power_summary()
        # This is an RMC command, but is grouped with TH6 tests
        self.check_th6_optical_module_version()
        print(f"\n{Colors.GREEN}All TH6 tests complete.{Colors.NC}")

    def run_all_w400_x86_tests(self):
        print(f"\n{Colors.BLUE}======================================={Colors.NC}") # pylint: disable=unused-variable
        print(f"{Colors.BLUE}  Running All W400 x86 Diagnostic Tests  {Colors.NC}")
        print(f"{Colors.BLUE}======================================={Colors.NC}")
        self.check_x86_resources()
        self.check_w400_x86_versions()
        print(f"\n{Colors.GREEN}All W400 x86 tests complete.{Colors.NC}")

class Menu:
    """Handles the user-facing menu system."""

    def __init__(self, diag, rmc_ip, w400_ip, user, w400_x86_ip=None, w400_x86_user=None, th6_clients=None, th6_bmc_clients=None):
        self.diag = diag
        self.rmc_ip = rmc_ip
        self.w400_ip = w400_ip
        self.user = user
        self.w400_x86_ip = w400_x86_ip
        self.w400_x86_user = w400_x86_user
        self.th6_clients = th6_clients if th6_clients is not None else []
        self.th6_bmc_clients = th6_bmc_clients if th6_bmc_clients is not None else []

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
            ("Check Shelf I-Share Cable Status", self.diag.check_shelf_ishare_cable),
            ("Check Power AC Loss Cable Detect", self.diag.check_power_ac_loss),
            ("Check Power Shelf Version", self.diag.check_power_shelf_version),
            ("Check PSU and BBU Versions", self.diag.check_psu_bbu_versions),
            ("Check Power FRU Info", self.diag.check_power_fru_info),
            ("Check ALLC Sensor Status", self.diag.check_aalc_sensor_status),
            ("Check W400 FRU Information", self.diag.check_w400_fru_info),
            ("Check AALC Leakage Sensor Status", self.diag.check_aalc_leakage_sensor_status),            
            ("Check PSU Power Consumption", self.diag.check_psu_power_consumption),
        ]
        self.w400_x86_menu_items = [
            ("Check CPU and Memory Info", self.diag.check_x86_resources),
            ("Check W400 x86 SW/FW Versions", self.diag.check_w400_x86_versions),
            ("Check Optical Module Information", self.diag.check_w400_optic_module_info),
        ]
        self.th6_menu_items = [
            ("Check TH6 Version", self.diag.check_th6_version),
            ("Check Disk Usage", self.diag.check_th6_disk_usage),
            ("Check Transceiver Status (Present, Power, Reset)", self.diag.check_th6_transceiver_status),
            ("Set Transceivers Reset Mode", self.diag.set_th6_xcvr_reset_mode),
            ("Set Transceivers Low Power Mode", self.diag.set_th6_xcvr_low_power_mode),
            ("Check 1.6T Optical Module Version", self.diag.check_th6_optical_module_version),
            ("Check Fan Status (PWM & RPM)", self.diag.check_th6_fan_status),
            ("Check TH6 OM DSP Temperature", self.diag.check_th6_om_dsp_temperature),
            ("Check OM Temperature", self.diag.check_th6_om_temperature), # New function
            ("Set Fan PWM Value", self.diag.set_fan_pwm_value),
            ("Check TH6 Power Summary", self.diag.check_th6_power_summary),
        ]
        self.th6_bmc_menu_items = [
            ("Check TH6 BMC Versions", self.diag.check_th6_bmc_versions),
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

    def th6_bmc_menu(self):
        if not self.th6_bmc_clients:
            print(f"{Colors.YELLOW}No TH6 BMCs configured or connected.{Colors.NC}")
            input(f"\n{Colors.YELLOW}Press Enter to continue...{Colors.NC}")
            return

        self._show_menu("TH6 BMC Diagnostics Menu", self.th6_bmc_menu_items)

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

        # Dynamically add TH6 BMCs to the selection
        if self.diag.th6_bmc_clients:
            for i, th6_bmc_client in enumerate(self.diag.th6_bmc_clients, 1):
                key = f"b{i}"
                targets[key] = (th6_bmc_client, f"TH6-{i} BMC ({th6_bmc_client.hostname})")
                print(f"  ({key}) TH6-{i} BMC ({th6_bmc_client.hostname})")
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
            main_menu_items.append(("TH6 X86 Diagnostics (Individual Tests)", self.th6_menu))
        # Add a single entry for all TH6 BMCs
        if self.diag.th6_bmc_clients:
            main_menu_items.append(("TH6 BMC Diagnostics (Individual Tests)", self.th6_bmc_menu))

        main_menu_items.append(("Run Custom Command", self._run_custom_command))
        main_menu_items.append(("Upload and Execute Script", self._upload_and_run_script))

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
            if self.diag.th6_bmc_clients:
                th6_bmc_ips = ", ".join([c.hostname for c in self.diag.th6_bmc_clients])
                print(f"  TH6 BMC Targets: {Colors.YELLOW}{th6_bmc_ips}{Colors.NC}")
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
    for i in range(1, 13):
        th6_ip = input(f"Enter IP for TH6-{i} (leave blank to stop adding): ").strip()
        if not th6_ip: break
        
        th6_data = {}
        th6_data['ip'] = th6_ip
        th6_data['bmc_ip'] = input(f"Enter BMC IP for TH6-{i}: ").strip()
        # The following are now profile-level, but we keep the structure for potential overrides.
        # In the new model, these would likely be blank and inherit from the profile.
        profile['th6_devices'].append(th6_data)
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
            print(f"{Colors.RED}Profile '{choice}' not found.{Colors.NC}")

def get_log_dir(config):
    """Gets logging preference from the user."""
    # This function could be extended to ask about debug mode as well.
    return input(f"Enter a directory to save command logs (default: {config.get('default_log_dir', 'logs')}): ") or config.get('default_log_dir', 'logs')

def display_profile(profile, log_dir):
    """Displays the details of the currently active profile."""
    print(f"{Colors.GREEN}Configuration set.{Colors.NC}")
    print(f"RMC Target:   {Colors.YELLOW}{profile['username']}@{profile['rmc_ip']}{Colors.NC}")
    print(f"W400 BMC Target:  {Colors.YELLOW}{profile['username']}@{profile['w400_ip']}{Colors.NC}")
    print(f"W400 x86 Target:  {Colors.YELLOW}{profile['w400_x86_username']}@{profile['w400_x86_ip']} (via W400 BMC){Colors.NC}")
    if profile.get('th6_devices'):
        for i, th6 in enumerate(profile.get('th6_devices', [])):
            ip = th6.get('ip')
            mac = th6.get('mac')
            serial = th6.get('serial')

            x86_identifier = "N/A"
            bmc_identifier = "N/A"

            if ip:
                # If an IP is specified, it's assumed to be for the x86. BMC connection isn't possible without a MAC.
                x86_identifier = ip
                bmc_identifier = th6.get('bmc_ip', "N/A (IP specified)")
            elif mac:
                # If a MAC is specified, derive the x86 MAC from the BMC MAC.
                bmc_identifier = mac
                x86_identifier = increment_mac(mac) or f"invalid({mac})"
            elif serial:
                # If only serial is specified, we show that. The IP will be resolved later.
                bmc_identifier = f"SN:{serial}"
                x86_identifier = f"via {bmc_identifier}"

            # Get common TH6 credentials from the profile, not the individual device entry
            x86_user = profile.get('th6_x86_username', 'root')
            bmc_user = profile.get('th6_bmc_username', 'root')
            print(f"TH6-{i+1} Target: x86={Colors.YELLOW}{x86_user}@{x86_identifier}{Colors.NC}, BMC={Colors.YELLOW}{bmc_user}@{bmc_identifier}{Colors.NC}")
    if log_dir:
        print(f"Logging to:   {Colors.YELLOW}{log_dir}{Colors.NC}")
    else:
        print(f"Logging:      {Colors.YELLOW}Disabled{Colors.NC}")

def _connect_client_worker(client, is_proxy=False, proxy_client=None, debug=False, config=None):
    """
    Worker function to connect a single client. Designed to be run in a thread pool.
    Returns the client if successful, None otherwise.
    """
    if not client or not client.hostname:
        if debug:
            print("DEBUG: Skipping connection for a client with no hostname.")
        return None

    if debug:
        print(f"Attempting to connect to {client.hostname}...")

    if is_proxy:
        if proxy_client and proxy_client.get_transport() and proxy_client.get_transport().is_active():
            if client.connect_via_proxy(proxy_client):
                if debug: print(f"DEBUG: Successfully connected to {client.hostname} via proxy.")
                return client
            else:
                if debug: print(f"DEBUG: Failed to connect to {client.hostname} via proxy.")
                return None
        else:
            if debug: print(f"DEBUG: Proxy client for {client.hostname} is not connected. Skipping.")
            return None
    else:
        if client.connect():
            if debug: print(f"DEBUG: Successfully connected to {client.hostname}.")
            return client
        else:
            if debug: print(f"DEBUG: Failed to connect to {client.hostname}. Some tests may fail.")
            return None

def _get_th6_ips(th6_data, local_arp_table, leases_by_mac, leases_by_serial, debug_mode=False):
    """Helper to resolve TH6 IPs from DHCP leases or ARP table."""
    # Prioritize direct IP from config
    x86_ip = th6_data.get('ip')
    bmc_ip = th6_data.get('bmc_ip')
    mac = th6_data.get('mac')
    serial = th6_data.get('serial')

    # 1. Try to resolve via DHCP using Serial Number
    if not bmc_ip and serial and leases_by_serial:
        bmc_lease = leases_by_serial.get(serial)
        if bmc_lease:
            bmc_ip = bmc_lease.get('ip')
            bmc_mac = bmc_lease.get('mac')
            if debug_mode: print(f"DEBUG: Found BMC for SN {serial} via DHCP: IP={bmc_ip}, MAC={bmc_mac}")
            if not x86_ip and bmc_mac:
                x86_mac_to_find = increment_mac(bmc_mac)
                if x86_mac_to_find:
                    x86_lease = leases_by_mac.get(x86_mac_to_find.lower())
                    if x86_lease:
                        x86_ip = x86_lease.get('ip')
                        if debug_mode: print(f"DEBUG: Found x86 for SN {serial} via DHCP: IP={x86_ip}, MAC={x86_mac_to_find}")

    # Fallback to ARP lookup if IPs are not specified
    if not bmc_ip and mac:
        bmc_ip = local_arp_table.get(mac.lower())
    if not x86_ip and mac:
        x86_mac = increment_mac(mac)
        if x86_mac:
            x86_ip = local_arp_table.get(x86_mac.lower())

    return x86_ip, bmc_ip

def _initialize_and_connect_clients(profile_data, log_dir, config, debug_mode=False):
    """
    Initializes and connects all remote clients based on the provided profile data.

    Args:
        profile_data (dict): Dictionary containing connection details for RMC, W400, and TH6 devices.
        log_dir (str): Directory for logging client command outputs.
        config (dict): The full application configuration object.
        debug_mode (bool): Whether to enable debug mode for verbose output.

    Returns:
        tuple: (rmc_client, w400_client, w400_x86_client, th6_clients, th6_bmc_clients)
               Connected RemoteClient instances, or None if connection fails.
    """    
    print(f"\n{Colors.BLUE}Attempting to resolve IPs and connect to all devices in parallel...{Colors.NC}")
    
    # --- New: DHCP IP Resolution Step ---
    leases = {}
    leases_by_mac = {}
    leases_by_serial = {}
    lease_file_paths = config.get("dhcp_lease_files", []) # Get list from config

    for path in lease_file_paths:
        if not path: continue
        # _parse_dhcp_leases will print a warning on failure
        leases = _parse_dhcp_leases(path)
        if leases: # If parsing was successful and returned data
            print(f"{Colors.BLUE}DHCP lease file parsed from '{path}'. Attempting to resolve IPs by SN...{Colors.NC}")
            break # Exit loop after first success

    if leases:
        for ip, lease_data in leases.items():
            if lease_data.get('mac'): leases_by_mac[lease_data['mac'].lower()] = lease_data
            if lease_data.get('serial'): leases_by_serial[lease_data['serial']] = lease_data
    else:
        # Only print warning if no lease file was ever found/parsed
        print(f"{Colors.YELLOW}Warning: Could not find or parse a valid DHCP lease file from configured locations. IP resolution by SN may fail.{Colors.NC}")

    # Resolve W400 IP if needed
    if not profile_data.get('w400_ip') and profile_data.get('w400_serial'):
        w400_serial = profile_data['w400_serial']
        w400_lease = leases_by_serial.get(w400_serial)
        if w400_lease:
            profile_data['w400_ip'] = w400_lease.get('ip')
            if debug_mode: print(f"DEBUG: Resolved W400 IP for SN {w400_serial} to {profile_data['w400_ip']}")

    # Initialize all client objects first
    rmc_client_obj = RemoteClient(profile_data['rmc_ip'], profile_data['username'], profile_data.get('password'), log_dir=log_dir, debug=debug_mode)
    w400_client_obj = RemoteClient(profile_data['w400_ip'], profile_data['username'], profile_data.get('password'), log_dir=log_dir, debug=debug_mode)
    w400_x86_client_obj = RemoteClient(profile_data['w400_x86_ip'], profile_data['w400_x86_username'], profile_data.get('w400_x86_password'), log_dir=log_dir, debug=debug_mode)

    local_arp_table = get_local_arp_table(debug_mode)
    th6_x86_client_objs = []
    th6_bmc_client_objs = []

    # Get common TH6 credentials from the profile
    th6_x86_user = profile_data.get('th6_x86_username', 'root')
    th6_x86_pass = profile_data.get('th6_x86_password')
    th6_bmc_user = profile_data.get('th6_bmc_username', 'root')
    th6_bmc_pass = profile_data.get('th6_bmc_password')

    for th6_data in profile_data.get('th6_devices', []):
        x86_ip, bmc_ip = _get_th6_ips(th6_data, local_arp_table, leases_by_mac, leases_by_serial, debug_mode)
        if x86_ip:
            th6_x86_client_objs.append(RemoteClient(x86_ip, th6_x86_user, th6_x86_pass, log_dir, debug=debug_mode))
        if bmc_ip:
            th6_bmc_client_objs.append(RemoteClient(bmc_ip, th6_bmc_user, th6_bmc_pass, log_dir, debug=debug_mode))

    # Use a thread pool to connect in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit primary connections
        future_rmc = executor.submit(_connect_client_worker, rmc_client_obj, debug=debug_mode, config=config)
        future_w400 = executor.submit(_connect_client_worker, w400_client_obj, debug=debug_mode, config=config)
        
        # Wait for W400 to connect before attempting proxy connection
        w400_client = future_w400.result()
        if w400_client:
            future_w400_x86 = executor.submit(_connect_client_worker, w400_x86_client_obj, is_proxy=True, proxy_client=w400_client.client, debug=debug_mode, config=config)
        else:
            future_w400_x86 = None

        # Submit all TH6 connections
        th6_x86_futures = [executor.submit(_connect_client_worker, c, debug=debug_mode, config=config) for c in th6_x86_client_objs]
        th6_bmc_futures = [executor.submit(_connect_client_worker, c, debug=debug_mode, config=config) for c in th6_bmc_client_objs]

        # Collect results
        rmc_client = future_rmc.result()
        w400_x86_client = future_w400_x86.result() if future_w400_x86 else None
        
        th6_clients = [f.result() for f in concurrent.futures.as_completed(th6_x86_futures) if f.result() is not None]
        th6_bmc_clients = [f.result() for f in concurrent.futures.as_completed(th6_bmc_futures) if f.result() is not None]

    print(f"{Colors.BLUE}Connection process finished.{Colors.NC}\n")
    return rmc_client, w400_client, w400_x86_client, sorted(th6_clients, key=lambda c: c.hostname), sorted(th6_bmc_clients, key=lambda c: c.hostname)

def run_interactive_mode():
    """Main execution loop for the interactive menu-driven tool."""
    rmc_client = None
    w400_client = None
    w400_x86_client = None # Initialize to None
    th6_clients = []
    th6_bmc_clients = []

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
        debug_mode_input = input("Enable debug mode for verbose output? (y/n, default: n): ").lower()
        debug_mode = debug_mode_input == 'y' or debug_mode_input == 'yes'
        display_profile(profile_data, log_dir)

        rmc_client, w400_client, w400_x86_client, th6_clients, th6_bmc_clients = \
            _initialize_and_connect_clients(profile_data, log_dir, config, debug_mode)

        diag = Diagnostics(rmc_client, w400_client, w400_x86_client, th6_clients, th6_bmc_clients, debug=debug_mode, config=config)
        menu = Menu(diag, profile_data.get('rmc_ip'), profile_data.get('w400_ip'), profile_data.get('username'), profile_data.get('w400_x86_ip'), profile_data.get('w400_x86_username'), th6_clients, th6_bmc_clients)
        
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
        if rmc_client: rmc_client.close()
        if w400_client: w400_client.close()
        if w400_x86_client:
            w400_x86_client.close()
        if th6_clients:
            for th6_client in th6_clients:
                th6_client.close()
        if th6_bmc_clients:
            for th6_bmc_client in th6_bmc_clients:
                th6_bmc_client.close()
        
        # The main_menu now returns "exit" or "change_target"
        if menu_action == "exit":
            break
        # If action is "change_target", the loop will naturally restart

def list_available_tests():
    """
    Lists all public diagnostic functions available in the Diagnostics class.
    """
    print(f"\n{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
    print(f"{Colors.YELLOW}  Available Diagnostic Functions (for --run-tests or --tests arguments):{Colors.NC}")
    print(f"{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")

    # Create a dummy Diagnostics instance to inspect its methods.
    # We pass None for clients as we only need the method names, not actual functionality.
    dummy_diag = Diagnostics(None, None, None, None, None, log_dir=None, config=None) # Pass config=None for dummy
    
    test_functions = []
    for name in dir(dummy_diag):
        # Filter out private methods, special methods, and internal helpers
        if not name.startswith('_') and callable(getattr(dummy_diag, name)):
            # Further filter out methods that are not actual tests but internal to the class
            # or are not meant to be called directly via --run-tests
            if name not in ['rmc', 'w400', 'w400_x86', 'th6_clients', 'th6_bmc_clients', 'debug', 'th6_power_sensor_results',
                            'LTC4287_HSC_REGEX', 'POWER_SUMMARY_LINE_REGEX', 'PORT_DSP_TEMP_REGEX']:
                test_functions.append(name)
    
    # Sort for consistent output
    test_functions.sort()

    for func_name in test_functions:
        print(f"  - {func_name}")

    print(f"{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}")
    print(f"{Colors.YELLOW}  Note: Some functions may require specific device connections to succeed.{Colors.NC}")
    print(f"{Colors.BLUE}-----------------------------------------------------------------------------{Colors.NC}\n")

def _execute_diagnostic_cycle(profile_name, tests_to_run, log_dir_override=None, debug_mode=False, config=None):
    """
    A helper function that encapsulates a single run of diagnostic tests.
    It loads config, connects clients, runs tests, and disconnects.
    This is the core logic shared by command mode and service mode.

    Returns:
        A tuple of (bool, list): (overall_success, list_of_failures)
    """
    overall_success = True
    failures = []

    # --- Configuration Loading ---
    if config is None:
        config = load_configuration()
    if not profile_name or profile_name not in config.get("profiles", {}):
        print(f"{Colors.RED}Error: Profile '{profile_name}' not found or not specified.{Colors.NC}", file=sys.stderr)
        return False, [f"Profile '{profile_name}' not found"]
    
    profile_data = config["profiles"][profile_name]
    print(f"Using profile: '{profile_name}'")

    log_dir = log_dir_override if log_dir_override else config.get("default_log_dir", "logs")
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # --- Client Connection ---
    rmc_client, w400_client, w400_x86_client, th6_clients, th6_bmc_clients = \
        _initialize_and_connect_clients(profile_data, log_dir, config, debug_mode=debug_mode)

    # --- Diagnostics Execution ---
    diag = Diagnostics(rmc_client, w400_client, w400_x86_client, th6_clients, th6_bmc_clients, debug=debug_mode, log_dir=log_dir, config=config)
    
    for test_name in tests_to_run:
        if hasattr(diag, test_name):
            try:
                # The @test_wrapper decorator handles the printing of headers and status
                success = getattr(diag, test_name)()
                if not success:
                    overall_success = False
                    failures.append(test_name)
            except Exception as test_exc:
                overall_success = False
                failures.append(f"{test_name} (exception)")
                print(f"Test '{test_name}' raised an exception: {test_exc}", file=sys.stderr)
        else:
            overall_success = False
            failures.append(f"{test_name} (not found)")
            print(f"\n{Colors.RED}Error: Test function '{test_name}' not found in Diagnostics class.{Colors.NC}\n", file=sys.stderr)

    # --- Client Disconnection ---
    if rmc_client: rmc_client.close()
    if w400_client: w400_client.close()
    if w400_x86_client: w400_x86_client.close()
    for client in th6_clients: client.close()
    for client in th6_bmc_clients: client.close()

    return overall_success, failures

def run_command_mode(args):
    """
    Runs the script in a non-interactive command mode, executing specified
    tests from the command line and then exiting.
    """
    overall_success = True
    failures = []
    print(f"Starting in command mode. Tests to run: {', '.join(args.run_tests)}")

    config = load_configuration()
    profile_name = args.profile or config.get("active_profile")
    overall_success, failures = _execute_diagnostic_cycle(profile_name, args.run_tests, args.log_dir, args.debug, config)

    if overall_success:
        print(f"\n{Colors.GREEN}Command mode execution finished. All tests passed.{Colors.NC}")
    else:
        print(f"\n{Colors.RED}Command mode execution finished with failures in: {', '.join(failures)}{Colors.NC}")
    return overall_success

"""A stream-like object that redirects writes to a logger instance."""
class StreamToLogger:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            # Log each line separately
            self.logger.log(self.level, line.rstrip())

    def flush(self):
        # The logger handles its own flushing
        pass

"""A wrapper class that scans for failures while writing to a stream."""
class FailureDetectingStream:
    def __init__(self, primary_stream, strip_color=False):
        self.primary_stream = primary_stream
        self.strip_color = strip_color
        self.failure_detected = False
        self.buffer = [] # To hold the output of the current cycle

    def write(self, text):
        # Check for failure strings before stripping color
        if f"{Colors.RED}FAIL" in text or "FAIL" in str(text).upper():
            self.failure_detected = True
        
        # Store the original text in the buffer
        self.buffer.append(str(text))

        # Strip color if requested before writing to the primary stream
        if self.strip_color:
            clean_text = re.sub(r'\x1b\[[0-9;]*m', '', str(text))
            self.primary_stream.write(clean_text)
        else:
            self.primary_stream.write(str(text))

    def flush(self):
        self.primary_stream.flush()

    def get_cycle_log(self):
        """Returns the buffered log for the current cycle."""
        return "".join(self.buffer)

    def reset_cycle(self):
        """Resets the failure flag and buffer for the next cycle."""
        self.failure_detected = False
        self.buffer = []

    def __getattr__(self, attr):
        return getattr(self.primary_stream, attr)

def run_service_mode(args):
    """A stream-like object that redirects writes to a logger instance."""
    """
    Runs the script in a non-interactive service mode, periodically executing
    specified tests and logging the output.
    """
    print(f"Starting in service mode. Interval: {args.interval}s. Tests: {', '.join(args.tests)}")
    
    # --- Configuration Loading ---
    config = load_configuration()
    profile_name = args.profile or config.get("active_profile")
    if not profile_name or profile_name not in config["profiles"]:
        print(f"{Colors.RED}Error: Profile '{profile_name}' not found or not specified.{Colors.NC}", file=sys.stderr)
        sys.exit(1)
    profile_data = config["profiles"][profile_name]

    # --- Logging Setup ---
    log_dir = args.log_dir if args.log_dir else config.get("default_log_dir", "logs")
    os.makedirs(log_dir, exist_ok=True) # Ensure the log directory exists
    log_filepath = os.path.join(log_dir, "service.log") # Use a fixed name for rotation
    print(f"Service mode started. Using profile '{profile_name}'. Logging to: {log_filepath}")

    # Set up the rotating file handler
    log_formatter = logging.Formatter('%(asctime)s - %(message)s')
    # Convert max size from MB to bytes
    max_bytes = args.log_max_size * 1024 * 1024
    rotating_handler = RotatingFileHandler(log_filepath, maxBytes=max_bytes, backupCount=args.log_backup_count)
    rotating_handler.setFormatter(log_formatter)

    # Get the root logger and add our handler
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(rotating_handler)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # Create the stream that will capture output and detect failures
    log_stream = StreamToLogger(root_logger, logging.INFO)
    failure_stream = FailureDetectingStream(log_stream, strip_color=args.strip_color)

    try:
        # Redirect stdout and stderr to the logger
        sys.stdout = failure_stream
        sys.stderr = failure_stream

        while True:
            print(f"\n--- Starting diagnostic cycle at {datetime.now().isoformat()} ---")
            
            success, failures = _execute_diagnostic_cycle(
                profile_name, args.tests, log_dir, args.debug, config
            )

            if not success and args.email_on_failure:
                # Use original stdout to print status about sending email
                print(f"Failures detected: {failures}. Preparing email report...", file=original_stdout)
                cycle_log_content = failure_stream.get_cycle_log()
                send_email_report(config.get("email_settings", {}), cycle_log_content)

            # Reset for the next cycle
            failure_stream.reset_cycle()

            print(f"--- Cycle finished. Waiting {args.interval} seconds... ---")
            print(f"Next run in {args.interval} seconds...", file=original_stdout)
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nService mode interrupted by user. Shutting down.", file=original_stdout)
    except Exception as e:
        print(f"\nAn unexpected error occurred in service mode: {e}", file=original_stdout)
    finally:
        # Restore original stdout and stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr

def send_email_report(email_config, log_content):
    """Sends an email report with the provided log content."""
    if not all(email_config.get(k) for k in ['smtp_server', 'smtp_port', 'smtp_user', 'smtp_password', 'sender_email', 'receiver_emails']):
        print(f"{Colors.RED}Email settings are incomplete in config.json. Cannot send report.{Colors.NC}", file=sys.stderr)
        return

    subject = f"Rack Diagnostics Failure Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    sender = email_config['sender_email']
    receivers = email_config['receiver_emails']

    msg = MIMEText(f"One or more diagnostic tests failed. Please review the attached log.\n\n{log_content}")
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ", ".join(receivers)

    try:
        print(f"Connecting to SMTP server {email_config['smtp_server']}...")
        with smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port']) as server:
            server.starttls()
            server.login(email_config['smtp_user'], email_config['smtp_password'])
            server.sendmail(sender, receivers, msg.as_string())
        print(f"{Colors.GREEN}Email report sent successfully to {', '.join(receivers)}.{Colors.NC}")
    except Exception as e:
        print(f"{Colors.RED}Failed to send email report: {e}{Colors.NC}", file=sys.stderr)

def main():
    """Main entry point. Parses arguments and runs in the appropriate mode."""
    parser = argparse.ArgumentParser(description="Rack Diagnostics Tool. Runs in interactive mode by default.")
    parser.add_argument("--service", action="store_true", help="Run in non-interactive service mode to periodically execute tests.")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds for service mode execution (default: 300).")
    parser.add_argument("-cmd", "--run-tests", nargs='+', help="Run one or more specific test functions non-interactively and exit (e.g., check_th6_power_summary).")
    parser.add_argument("--tests", nargs='+', help="A space-separated list of test functions to run in service mode (e.g., check_th6_power_summary check_th6_om_temperature).")
    parser.add_argument("--profile", type=str, help="Specify a profile to use for non-interactive modes.")
    parser.add_argument("--log-dir", type=str, help="Override the default log directory for service mode.")
    parser.add_argument("--log-max-size", type=int, default=10, help="Maximum log file size in MB before rotation (default: 10).")
    parser.add_argument("--log-backup-count", type=int, default=5, help="Number of old log files to keep (default: 5).")
    parser.add_argument("--strip-color", action="store_true", help="Strip ANSI color codes from service mode log files.")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode for verbose connection messages in command mode.")
    parser.add_argument("--email-on-failure", action="store_true", help="Send an email report if any test fails in service mode.")
    parser.add_argument("--list-tests", action="store_true", help="List all available diagnostic functions and exit.")
    
    args = parser.parse_args()

    if args.service:
        if not args.tests:
            parser.error("--tests are required when using --service mode.")
        run_service_mode(args)
    elif args.run_tests:
        success = run_command_mode(args)
        if not success:
            # The script will exit with a non-zero status code
            sys.exit(1)
    elif args.list_tests:
        list_available_tests()
        sys.exit(0)
    else:
        run_interactive_mode()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user. Exiting.{Colors.NC}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}An unexpected error occurred: {e}{Colors.NC}", file=sys.stderr)
        sys.exit(1)