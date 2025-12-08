#!/usr/bin/env python3
# dhcptool.py
import argparse
import logging
import re
import sys
import ipaddress
import os
from datetime import datetime
import json
import subprocess

try:
    from scapy.all import BOOTP, DHCP, IP, UDP, Ether, RandMAC, RandInt, srp1
except ImportError:
    print("Warning: 'scapy' library not found. The 'test-server' command will not be available. Please run 'pip install scapy'.")
    # Define a dummy class to prevent further errors if scapy is missing
    class BOOTP: pass


class DhcpAdmin:
    """
    A Python class to manage ISC-DHCPd leases and static hosts.
    """
    def __init__(self, lease_file='/var/lib/dhcp/dhcpd.leases', lease_file_v6='/var/lib/dhcp/dhcpd6.leases', dhcp_service_name='isc-dhcp-server', config_file='/etc/dhcp/dhcpd.conf', config_file_v6='/etc/dhcp/dhcpd6.conf'):
        self.lease_file = lease_file
        self.lease_file_v6 = lease_file_v6
        # Add config file paths to the class
        self.config_file = config_file
        self.config_file_v6 = config_file_v6
        self.dhcp_service_name = dhcp_service_name
        self.logger = logging.getLogger(__name__)
        self.leases_ipv4 = self._parse_ipv4_leases()
        self.leases_ipv6 = self._parse_ipv6_leases()
        self.duplicate_macs = self._find_duplicate_macs()

    def _read_lease_file(self, file_path):
        """Reads a lease file and returns its content, handling common errors."""
        try:
            with open(file_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            self.logger.info("Lease file not found at %s. This may be normal if the protocol is not in use.", file_path)
            return None
        except PermissionError:
            self.logger.error("Permission denied to read lease file at %s. Try running with sudo.", file_path)
            return None

    def _parse_ipv4_leases(self):
        """Parses the dhcpd.leases file and returns a dictionary of active IPv4 leases."""
        leases = {}
        content = self._read_lease_file(self.lease_file)
        if not content:
            return {}

        # A simplified regex to find lease blocks
        lease_blocks = re.findall(r'lease\s+([\d\.]+)\s+\{([^}]+)\}', content, re.DOTALL)
        
        for ip, block in lease_blocks:
            # The most reliable way to check for an active lease is the binding state.
            binding_state_match = re.search(r'binding state (\w+);', block)
            if not binding_state_match or binding_state_match.group(1) != 'active':
                continue

            mac_match = re.search(r'hardware ethernet ([\w:]+);', block)
            if mac_match:
                mac = mac_match.group(1)
                lease_end = None
                ends_match = re.search(r'ends \d+ (.*?);', block)
                if ends_match:
                    end_time_str = ends_match.group(1)
                    # Try parsing multiple common date formats from dhcpd.leases
                    for fmt in ('%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                        try:
                            lease_end = datetime.strptime(end_time_str, fmt)
                            break
                        except ValueError:
                            continue

                # --- New: Parse vendor-class-identifier ---
                vendor_class_match = re.search(r'set vendor-class-identifier = "([^"]+)";', block)
                model = None
                serial = None
                vendor_hostname = None
                if vendor_class_match:
                    vendor_string = vendor_class_match.group(1)
                    # Example: "OpenBMC:model=ICECUBE:serial=F603225300020"
                    parts = vendor_string.split(':')
                    if parts:
                        vendor_hostname = parts[0]
                    for part in parts:
                        if part.startswith('model='):
                            model = part.split('=', 1)[1]
                        elif part.startswith('serial='):
                            serial = part.split('=', 1)[1]

                hostname_match = re.search(r'client-hostname "([^"]+)";', block)
                leases[ip] = {
                    'ip': ip,
                    'mac': mac,
                    'hostname': hostname_match.group(1) if hostname_match else None,
                    'ends': lease_end,
                    'model': model,
                    'serial': serial,
                    'vendor_hostname': vendor_hostname,
                    'version': 4
                }
        return leases

    def _parse_ipv6_leases(self):
        """Parses the dhcpd6.leases file and returns a dictionary of active IPv6 leases."""
        leases = {}
        content = self._read_lease_file(self.lease_file_v6)
        if not content:
            return {}

        # Regex to find ia-na blocks, which contain address assignments
        ia_na_blocks = re.findall(r'ia-na\s+.*?\{([^}]+)\}', content, re.DOTALL)

        for block in ia_na_blocks:
            # Find all address blocks within the ia-na block
            iaaddr_blocks = re.findall(r'iaaddr\s+([0-9a-fA-F:]+)\s+\{([^}]+)\}', block, re.DOTALL)

            for ip, addr_block in iaaddr_blocks:
                binding_state_match = re.search(r'binding state (\w+);', addr_block)
                if not binding_state_match or binding_state_match.group(1) != 'active':
                    continue

                # Extract MAC from DUID-LLT if available
                mac = None
                duid_match = re.search(r'option dhcp6.client-id\s+((?:[0-9a-fA-F]{2}:)+[0-9a-fA-F]{2});', block)
                if duid_match:
                    duid = duid_match.group(1).split(':')
                    # DUID-LLT (Link-Layer address plus Time) type is 1
                    # It is stored as 00:01 in the file for type 1.
                    if len(duid) > 8 and duid[0] == '00' and duid[1] == '01':
                        # The last 6 bytes of a DUID-LLT are the MAC address
                        mac = ':'.join(duid[-6:])

                ends_match = re.search(r'ends (\d+);', addr_block)
                lease_end = None
                if ends_match:
                    try:
                        # Lease time is stored as a Unix timestamp
                        lease_end = datetime.fromtimestamp(int(ends_match.group(1)))
                    except (ValueError, TypeError):
                        pass

                leases[ip] = {
                    'ip': ip,
                    'mac': mac,
                    'hostname': None, # Hostname is not typically in dhcpd6.leases
                    'ends': lease_end,
                    'model': None,
                    'serial': None,
                    'vendor_hostname': None,
                    'version': 6
                }
        return leases

    def get_all_leases(self):
        """Returns a unified list of all active IPv4 and IPv6 leases."""
        all_leases = list(self.leases_ipv4.values())
        all_leases.extend(list(self.leases_ipv6.values()))
        return all_leases

    def _find_duplicate_macs(self):
        """
        Finds MAC addresses that have been assigned multiple IP addresses across all leases.
        This is executed once during initialization.
        Returns a dictionary of MACs mapped to their list of IPs if duplicates are found.
        """
        mac_to_ips = {}
        for lease in self.get_all_leases():
            mac = lease.get('mac')
            ip = lease.get('ip')
            if mac and ip:
                mac_to_ips.setdefault(mac, []).append(ip)

        return {mac: ips for mac, ips in mac_to_ips.items() if len(ips) > 1}

    def get_lease_by_hostname(self, hostname):
        """Finds an active lease by its hostname."""
        for lease in self.leases_ipv4.values():
            if lease.get('hostname') == hostname:
                return lease
        return None

    def get_lease_by_ip(self, ip):
        """Finds an active lease by its IP address."""
        return self.leases_ipv4.get(ip) or self.leases_ipv6.get(ip)

    def reload_dhcp_service(self):
        """Reloads the DHCP service to apply changes."""
        self.logger.info("Reloading %s...", self.dhcp_service_name)
        try:
            # Use 'systemctl reload' for modern systems
            subprocess.run(['systemctl', 'reload', self.dhcp_service_name], check=True)
            self.logger.info("DHCP service reloaded successfully.")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.logger.error("Failed to reload DHCP service: %s", e)
            self.logger.warning("Please reload it manually (e.g., 'sudo systemctl reload %s').", self.dhcp_service_name)

    def get_dhcp_service_status(self):
        """Checks the status of the DHCP service using systemctl."""
        self.logger.info("Checking status of %s...", self.dhcp_service_name)
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', self.dhcp_service_name],
                capture_output=True, text=True, check=False
            )
            status = result.stdout.strip()
            self.logger.info("Service status is '%s'.", status)
            return status
        except FileNotFoundError:
            self.logger.error("`systemctl` command not found. Cannot check service status.")
            return "unknown"

    def _control_dhcp_service(self, action):
        """Internal helper to start, stop, or restart the DHCP service."""
        self.logger.info("%s %s...", action.capitalize(), self.dhcp_service_name)
        try:
            subprocess.run(['systemctl', action, self.dhcp_service_name], check=True)
            self.logger.info("DHCP service %s successfully.", action)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.logger.error("Failed to %s DHCP service: %s", action, e)
            return False

    def start_dhcp_service(self): return self._control_dhcp_service('start')
    def stop_dhcp_service(self): return self._control_dhcp_service('stop')
    def restart_dhcp_service(self): return self._control_dhcp_service('restart')

    def check_config(self):
        self.logger.info("Validating DHCP server configuration...")
        try:
            result = subprocess.run(['dhcpd', '-t'], check=False, capture_output=True, text=True)
            output = result.stderr.strip() or result.stdout.strip()
            self.logger.info("dhcpd -t output:\n%s", output)
            return "Configuration file syntax is correct." in output
        except FileNotFoundError:
            self.logger.error("`dhcpd` command not found. Is the ISC DHCP server package installed?")
            return False

    def test_dhcp_responsiveness(self, timeout=5):
        """
        Sends a DHCP DISCOVER packet and waits for an OFFER to test server responsiveness.
        Requires scapy and root privileges.
        """
        if 'BOOTP' not in globals() or not hasattr(BOOTP, 'fields_desc'): # A reliable check for real scapy class
            self.logger.error("Scapy is not installed. Cannot perform DHCP responsiveness test.")
            return None, "Scapy not installed"

        self.logger.info(f"Sending DHCP DISCOVER and waiting for an OFFER (timeout: {timeout}s)...")
        
        # Craft DHCP DISCOVER packet
        dhcp_discover = (
            Ether(dst="ff:ff:ff:ff:ff:ff") /
            IP(src="0.0.0.0", dst="255.255.255.255") /
            UDP(sport=68, dport=67) /
            BOOTP(chaddr=RandMAC(), xid=RandInt()) /
            DHCP(options=[("message-type", "discover"), "end"])
        )

        # Send packet and wait for a single response
        dhcp_offer = srp1(dhcp_discover, timeout=timeout, verbose=0)

        if dhcp_offer and dhcp_offer.haslayer(DHCP) and dhcp_offer[DHCP].options[0][1] == 2: # 2 = offer
            server_ip = dhcp_offer[IP].src
            return True, server_ip
        return False, None

    def get_dhcp_log(self, lines=20):
        """Retrieves recent log entries for the DHCP service from journalctl."""
        self.logger.info("Fetching last %d log entries for %s...", lines, self.dhcp_service_name)
        try:
            # journalctl -u <service> -n <lines> --no-pager
            result = subprocess.run(
                ['journalctl', '-u', self.dhcp_service_name, '-n', str(lines), '--no-pager'],
                capture_output=True, text=True, check=True
            )
            return result.stdout
        except FileNotFoundError:
            self.logger.error("`journalctl` command not found. This feature is only available on systems with systemd.")
            return None
        except subprocess.CalledProcessError as e:
            self.logger.error("Failed to fetch logs for %s.", self.dhcp_service_name)
            self.logger.error("Error: %s", e.stderr)
            return None


def setup_logging():
    """Configures the logging for the script."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def handle_list(args, dhcp):
    """Handler for the 'list' sub-command."""
    print("--- Active Dynamic Leases ---")
    all_leases = dhcp.get_all_leases()
    if not all_leases:
        print("No active leases found.")
        # Add a helpful diagnostic check if no leases are found.
        status = dhcp.get_dhcp_service_status()
        if status != 'active':
            logging.warning("The DHCP service '%s' is not active (current state: %s).", dhcp.dhcp_service_name, status)
            logging.info("You can try starting it with: 'sudo dhcptool.py service start'")
        else:
            # If the service is running but there are no leases, provide next steps.
            logging.info("The DHCP service is running but has no active leases.")
            logging.info("You can check the server logs with: 'sudo dhcptool.py log'")
            logging.info("Or test server responsiveness with: 'sudo dhcptool.py test-server'")
        return
    
    # Unified header for both IPv4 and IPv6
    print(f"  {'Hostname':<25} {'IP Address':<40} {'MAC Address':<17}   {'Model':<12} {'Serial Number':<18} {'Expires'}")
    print(f"  {'-'*25} {'-'*40} {'-'*17}   {'-'*12} {'-'*18} {'-'*19}")

    leases_list = all_leases

    # --- New: Filter for duplicates only ---
    if args.duplicates_only:
        if not dhcp.duplicate_macs:
            print("No duplicate MAC addresses found.")
            return
        
        leases_list = [lease for lease in leases_list if lease.get('mac') in dhcp.duplicate_macs]
        print(f"--- Showing {len(leases_list)} lease(s) for {len(dhcp.duplicate_macs)} duplicate MAC address(es) ---")

    # Filter the list of leases based on the provided filter terms.
    if args.filter_terms:
        filtered_leases = []
        for lease in all_leases:
            matches_all = True
            for term in args.filter_terms:
                processed_term = term if args.case_sensitive else term.lower()

                # Get raw values from lease
                lease_ip = lease.get('ip') or ""
                lease_mac = lease.get('mac') or ""
                lease_model = lease.get('model') or ""
                lease_serial = lease.get('serial') or ""
                lease_serial = lease.get('serial') or ""
                
                # Construct composite hostname
                client_hostname = lease.get('hostname')
                vendor_hostname = lease.get('vendor_hostname')
                if client_hostname:
                    hostname = f"{client_hostname} ({vendor_hostname})" if vendor_hostname and client_hostname != vendor_hostname else client_hostname
                else:
                    hostname = vendor_hostname or ""

                # Prepare values for comparison
                check_values = [lease_ip, lease_mac, lease_serial]
                check_values.extend([val if args.case_sensitive else val.lower() for val in [hostname, lease_model, lease_serial]])

                # If the current term is not found in any value, this lease is not a match
                if not any(processed_term in value for value in check_values):
                    matches_all = False
                    break # Move to the next lease
            # If all terms matched for this lease, add it to the filtered list.
            if matches_all:
                filtered_leases.append(lease)

        leases_list = filtered_leases
        print(f"--- Showing {len(leases_list)} lease(s) matching: {args.filter_terms} ---")
    # --- End Filtering Logic ---

    # --- Sorting Logic ---
    sort_key = args.sort_by

    if sort_key == 'ip':
        # Use ipaddress module for correct IP sorting
        key_func = lambda lease: ipaddress.ip_address(lease.get('ip', '0.0.0.0'))
    elif sort_key == 'expires':
        # Use datetime.min for leases without an expiration to sort them first
        key_func = lambda lease: lease.get('ends') or datetime.min
    elif sort_key == 'hostname':
        # Sort by the final displayed hostname for consistency.
        def get_display_hostname(lease):
            client_hostname = lease.get('hostname')
            vendor_hostname = lease.get('vendor_hostname')
            if client_hostname:
                return f"{client_hostname} ({vendor_hostname})" if vendor_hostname and client_hostname != vendor_hostname else client_hostname
            else:
                return vendor_hostname or "<no-hostname>"
        key_func = lambda lease: get_display_hostname(lease).lower()
    else:
        # Default to case-insensitive string sorting for other columns
        key_func = lambda lease: (lease.get(sort_key) or "").lower()
    sorted_leases = sorted(leases_list, key=key_func, reverse=args.reverse)
    # --- End Sorting Logic ---

    # --- New: JSON output logic ---
    if args.output_json:
        serializable_leases = []
        for lease in sorted_leases:
            # Create a copy to avoid modifying the original list in memory
            lease_copy = lease.copy()
            if lease_copy.get('ends') and isinstance(lease_copy['ends'], datetime):
                lease_copy['ends'] = lease_copy['ends'].isoformat()
            serializable_leases.append(lease_copy)
        try:
            with open(args.output_json, 'w') as f:
                json.dump(serializable_leases, f, indent=2)
            logging.info(f"Successfully wrote {len(serializable_leases)} leases to {args.output_json}")
        except (IOError, PermissionError) as e:
            logging.error(f"Failed to write to JSON file {args.output_json}: {e}")
        return # Exit after writing to file

    # Print the sorted and filtered lease information.
    for lease in sorted_leases:
        if lease.get('version') == 4:
            client_hostname = lease.get('hostname')
            vendor_hostname = lease.get('vendor_hostname')
            if client_hostname:
                if vendor_hostname and client_hostname != vendor_hostname:
                    hostname = f"{client_hostname} ({vendor_hostname})"
                else:
                    hostname = client_hostname
            else:
                hostname = vendor_hostname or "<no-hostname>"
            model = lease.get('model') or "N/A"
            serial = lease.get('serial') or "N/A"
            mac = lease.get('mac') or "N/A"
        else: # IPv6
            hostname = "<no-hostname>"
            model = "N/A"
            serial = "N/A"
            mac = lease.get('mac') or "N/A (not DUID-LLT)"

        expires_str = lease.get('ends').strftime('%Y-%m-%d %H:%M:%S') if lease.get('ends') else "N/A"
        print(f"  {hostname:<25} {lease['ip']:<40} {mac:<17}   {model:<12} {serial:<18} {expires_str}")

    # --- New: Check for and warn about duplicate MACs ---
    if dhcp.duplicate_macs:
        print("\n" + "="*80)
        logging.warning("Duplicate MAC addresses found with multiple IPs!")
        print("--- WARNING: Duplicate MAC Addresses Detected ---")
        for mac, ips in dhcp.duplicate_macs.items():
            print(f"  MAC: {mac} has been assigned multiple IPs: {', '.join(ips)}")

def handle_service(args, dhcp):
    """Handler for service management sub-commands."""
    action = args.action
    if action == 'status':
        status = dhcp.get_dhcp_service_status()
        print(f"DHCP service '{dhcp.dhcp_service_name}' status: {status}")
    elif action == 'start':
        dhcp.start_dhcp_service()
    elif action == 'stop':
        dhcp.stop_dhcp_service()
    elif action == 'restart':
        dhcp.restart_dhcp_service()
    elif action == 'reload':
        dhcp.reload_dhcp_service()

def handle_check_config(args, dhcp):
    """Handler for the 'check-config' sub-command."""
    if not dhcp.check_config():
        logging.error("DHCP configuration check failed.")

def handle_log(args, dhcp):
    """Handler for the 'log' sub-command."""
    log_output = dhcp.get_dhcp_log(lines=args.lines)
    if log_output:
        print(f"\n--- Last {args.lines} Log Entries for {dhcp.dhcp_service_name} ---")
        print(log_output.strip())

def handle_find(args, dhcp):
    """Handler for the 'find' sub-command to show details for a single lease."""
    term = args.search_term.lower()
    found_leases = []

    for lease in dhcp.get_all_leases():
        # Prepare values for comparison (always case-insensitive for find)
        lease_ip = lease.get('ip') or ""
        lease_mac = lease.get('mac') or ""
        lease_model = (lease.get('model') or "").lower()
        lease_serial = (lease.get('serial') or "").lower()
        
        client_hostname = (lease.get('hostname') or "").lower()
        vendor_hostname = (lease.get('vendor_hostname') or "").lower()
        
        # Check multiple fields for the search term
        if (term in lease_ip or
            term in lease_mac or
            term in client_hostname or
            term in vendor_hostname or
            term in lease_model or
            term in lease_serial):
            found_leases.append(lease)

    if len(found_leases) == 0:
        logging.warning("No active lease found matching '%s'.", args.search_term)
    elif len(found_leases) == 1:
        lease = found_leases[0]
        print(f"--- Details for Lease: {lease.get('ip')} ---")
        
        # Construct the display hostname
        is_ipv6 = ':' in lease.get('ip', '')

        if not is_ipv6:
            client_hostname = lease.get('hostname')
            vendor_hostname = lease.get('vendor_hostname')
            if client_hostname:
                hostname = f"{client_hostname} ({vendor_hostname})" if vendor_hostname and client_hostname != vendor_hostname else client_hostname
            else:
                hostname = vendor_hostname or "<no-hostname>"

            print(f"  {'IP Address':<18}: {lease.get('ip', 'N/A')}")
            print(f"  {'Hostname':<18}: {hostname}")
            print(f"  {'MAC Address':<18}: {lease.get('mac', 'N/A')}")
            print(f"  {'Lease Expires':<18}: {lease.get('ends', 'N/A')}")
            print(f"  {'Device Model':<18}: {lease.get('model', 'N/A')}")
            print(f"  {'Serial Number':<18}: {lease.get('serial', 'N/A')}")
        else:
            # Display format for IPv6 leases
            print(f"  {'IP Address (v6)':<18}: {lease.get('ip', 'N/A')}")
            print(f"  {'MAC Address':<18}: {lease.get('mac') or 'N/A (not DUID-LLT)'}")
            print(f"  {'Lease Expires':<18}: {lease.get('ends', 'N/A')}")

    else:
        logging.warning("Multiple leases found matching '%s'. Please use a more specific term.", args.search_term)
        print("You can use the 'list' command to see all matches:")
        print(f"  python3 dhcptool.py list '{args.search_term}'")

def handle_summary(args, dhcp):
    """Handler for the 'summary' sub-command."""
    print("--- DHCP Server Summary ---")
    num_leases = len(dhcp.get_all_leases())
    status = dhcp.get_dhcp_service_status()

    print(f"  Active Dynamic Leases:   {num_leases}")
    print(f"  Service Status ({dhcp.dhcp_service_name}): {status}")

def handle_config_path(args, dhcp):
    """Handler for the 'config-path' sub-command."""
    print("--- DHCP Server Configuration Paths ---")
    print(f"  IPv4 Config File: {dhcp.config_file}")
    if os.path.exists(dhcp.config_file_v6):
        print(f"  IPv6 Config File: {dhcp.config_file_v6}")
    else:
        print(f"  IPv6 Config File: {dhcp.config_file_v6} (Not found)")

def main():
    """Main function to parse arguments and dispatch to handlers."""
    setup_logging()
    parser = argparse.ArgumentParser(description="A lightweight management tool for ISC-DHCP-Server.")
    parser.add_argument(
        '--lease-file',
        default='/var/lib/dhcp/dhcpd.leases',
        help='Path to the DHCP leases file (default: /var/lib/dhcp/dhcpd.leases)'
    )
    parser.add_argument(
        '--lease-file-v6',
        default='/var/lib/dhcp/dhcpd6.leases',
        help='Path to the DHCPv6 leases file (default: /var/lib/dhcp/dhcpd6.leases)'
    )
    parser.add_argument(
        '--config-file',
        default='/etc/dhcp/dhcpd.conf',
        help='Path to the DHCPv4 configuration file (default: /etc/dhcp/dhcpd.conf)'
    )
    parser.add_argument(
        '--config-file-v6',
        default='/etc/dhcp/dhcpd6.conf',
        help='Path to the DHCPv6 configuration file (default: /etc/dhcp/dhcpd6.conf)'
    )

    subparsers = parser.add_subparsers(dest='command', required=True, help='Available commands')

    # --- List command ---
    parser_list = subparsers.add_parser('list', help='List active leases.')
    parser_list.add_argument('filter_terms', nargs='*', help='Optional: Filter list by one or more search terms (IP, MAC, hostname, etc.).')
    parser_list.add_argument('--sort-by', choices=['hostname', 'ip', 'mac', 'model', 'serial', 'expires'], default='hostname', help='Column to sort the list by.')
    parser_list.add_argument('--case-sensitive', action='store_true', help='Perform a case-sensitive filter.')
    parser_list.add_argument('--reverse', action='store_true', help='Sort in descending order.')
    parser_list.add_argument('--duplicates-only', action='store_true', help='Only show leases for MAC addresses with multiple assigned IPs.')
    parser_list.add_argument('--output-json', metavar='FILE', help='Output the lease list to a JSON file instead of printing to the console.')
    parser_list.set_defaults(func=handle_list)

    # --- Service management commands ---
    parser_service = subparsers.add_parser('service', help='Manage the DHCP service (status, start, stop, etc.).')
    parser_service.add_argument('action', choices=['status', 'start', 'stop', 'restart', 'reload'], help='Service action to perform.')
    parser_service.set_defaults(func=handle_service)

    # --- Config check command ---
    parser_check = subparsers.add_parser('check-config', help='Validate the DHCP server configuration files.')
    parser_check.set_defaults(func=handle_check_config)

    # --- Summary command ---
    parser_summary = subparsers.add_parser('summary', help='Show a summary of active leases.')
    parser_summary.set_defaults(func=handle_summary)

    # --- Log command ---
    parser_log = subparsers.add_parser('log', help='Show recent DHCP server log entries from the system journal.')
    parser_log.add_argument('-n', '--lines', type=int, default=20, help='Number of recent log entries to show (default: 20).')
    parser_log.set_defaults(func=handle_log)

    # --- Find command ---
    parser_find = subparsers.add_parser('find', help='Find a specific lease and show its details.')
    parser_find.add_argument('search_term', help='The IP, MAC, hostname, or serial to find.')
    parser_find.set_defaults(func=handle_find)

    # --- Test Server command ---
    # Check if scapy was imported successfully before adding the command
    if 'BOOTP' in globals() and BOOTP.__module__ != 'dhcptool':
        parser_test = subparsers.add_parser('test-server', help="Test DHCP server responsiveness by sending a DISCOVER packet.")
        def handle_test_server(args, dhcp):
            """Handler for the 'test-server' command."""
            # The 'test-server' command requires root privileges to create raw sockets.
            if os.geteuid() != 0:
                logging.error("Permission denied. The 'test-server' command must be run with root privileges.")
                logging.error("Please try again using 'sudo dhcptool.py test-server'.")
                sys.exit(1)
            # Double-check that scapy is properly loaded before running
            if not hasattr(BOOTP, 'fields_desc'):
                logging.error("Cannot run test: 'scapy' library is not installed. Please run 'pip install scapy'.")
                return

            success, server_ip = dhcp.test_dhcp_responsiveness(timeout=args.timeout)
            if success:
                logging.info(f"Success! Received DHCP OFFER from server: {server_ip}")
            else:
                logging.error(f"No DHCP OFFER received within the {args.timeout}-second timeout.")
        parser_test.add_argument('--timeout', type=int, default=5, help="Seconds to wait for a response (default: 5).")
        parser_test.set_defaults(func=handle_test_server)

    # --- Config Path command ---
    parser_config_path = subparsers.add_parser('config-path', help='Show the paths to the DHCP configuration files.')
    parser_config_path.set_defaults(func=handle_config_path)

    args = parser.parse_args()
    
    # Initialize DhcpAdmin and call the appropriate handler function
    dhcp = DhcpAdmin(lease_file=args.lease_file, lease_file_v6=args.lease_file_v6, config_file=args.config_file, config_file_v6=args.config_file_v6)
    args.func(args, dhcp)

    logging.info("--- Process Complete ---")

if __name__ == "__main__":
    main()