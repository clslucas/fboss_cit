# dhcptool.py
import argparse
import logging
import re
import sys
import ipaddress
from datetime import datetime
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
    def __init__(self, lease_file='/var/lib/dhcp/dhcpd.leases', lease_file_v6='/var/lib/dhcp/dhcpd6.leases', dhcp_service_name='isc-dhcp-server'):
        self.lease_file = lease_file
        self.lease_file_v6 = lease_file_v6
        self.dhcp_service_name = dhcp_service_name
        self.logger = logging.getLogger(__name__)
        self.leases = self._parse_leases()
        self.leases_v6 = self._parse_leases_v6()

    def _parse_leases(self):
        """Parses the dhcpd.leases file and returns a list of lease dicts."""
        leases = {}
        try:
            with open(self.lease_file, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            self.logger.warning("Lease file not found at %s.", self.lease_file)
            return {}
        except PermissionError:
            self.logger.error("Permission denied to read lease file at %s. Try running with sudo.", self.lease_file)
            return {}

        # A simplified regex to find lease blocks
        lease_blocks = re.findall(r'lease\s+([\d\.]+)\s+\{([^}]+)\}', content, re.DOTALL)
        
        for ip, block in lease_blocks:
            mac_match = re.search(r'hardware ethernet ([\w:]+);', block)
            hostname_match = re.search(r'client-hostname "([^"]+)";', block)
            ends_match = re.search(r'ends \d+ (.*?);', block)
            
            # The most reliable way to check for an active lease is the binding state.
            binding_state_match = re.search(r'binding state (\w+);', block)
            if not binding_state_match or binding_state_match.group(1) != 'active':
                continue

            if mac_match:
                mac = mac_match.group(1)
                lease_end = None
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

                leases[ip] = {
                    'ip': ip,
                    'mac': mac,
                    'hostname': hostname_match.group(1) if hostname_match else None,
                    'ends': lease_end,
                    'model': model,
                    'serial': serial,
                    'vendor_hostname': vendor_hostname
                }
        return leases

    def _parse_leases_v6(self):
        """Parses the dhcpd6.leases file and returns a list of lease dicts."""
        leases = {}
        try:
            with open(self.lease_file_v6, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            # This is not a warning because the file may not exist if IPv6 is not used.
            self.logger.info("IPv6 lease file not found at %s. Skipping IPv6 lease parsing.", self.lease_file_v6)
            return {}
        except PermissionError:
            self.logger.error("Permission denied to read IPv6 lease file at %s. Try running with sudo.", self.lease_file_v6)
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
                    'vendor_hostname': None
                }
        return leases

    def get_lease_by_hostname(self, hostname):
        """Finds an active lease by its hostname."""
        for lease in self.leases.values():
            if lease.get('hostname') == hostname:
                return lease
        return None

    def get_lease_by_ip(self, ip):
        """Finds an active lease by its IP address."""
        return self.leases.get(ip)

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
    if not dhcp.leases:
        print("No active leases found.")
        return
    
    # Print header
    print(f"  {'Hostname':<25} {'IP Address':<15} {'MAC Address':<17}   {'Model':<12} {'Serial Number':<18} {'Expires'}")
    print(f"  {'-'*25} {'-'*15} {'-'*17}   {'-'*12} {'-'*18} {'-'*19}")

    # --- Sorting Logic ---
    leases_list = list(dhcp.leases.values())

    # --- Filtering Logic ---
    if args.filter_terms:
        filtered_leases = []
        for lease in leases_list:
            matches_all = True
            for term in args.filter_terms:
                processed_term = term if args.case_sensitive else term.lower()

                # Get raw values from lease
                lease_ip = lease.get('ip') or ""
                lease_mac = lease.get('mac') or ""
                lease_model = lease.get('model') or ""
                lease_serial = lease.get('serial') or ""
                
                # Construct composite hostname
                client_hostname = lease.get('hostname')
                vendor_hostname = lease.get('vendor_hostname')
                if client_hostname:
                    hostname = f"{client_hostname} ({vendor_hostname})" if vendor_hostname and client_hostname != vendor_hostname else client_hostname
                else:
                    hostname = vendor_hostname or ""

                # Prepare values for comparison
                check_values = [lease_ip, lease_mac]
                check_values.extend([val if args.case_sensitive else val.lower() for val in [hostname, lease_model, lease_serial]])

                # If the current term is not found in any value, this lease is not a match
                if not any(processed_term in value for value in check_values):
                    matches_all = False
                    break # Move to the next lease
            
            if matches_all:
                filtered_leases.append(lease)

        leases_list = filtered_leases
        print(f"--- Showing {len(leases_list)} lease(s) matching: {args.filter_terms} ---")
    # --- End Filtering Logic ---

    sort_key = args.sort_by

    # Define a key function for sorting based on the chosen column
    if sort_key == 'ip':
        # Use ipaddress module for correct IP sorting
        key_func = lambda lease: ipaddress.ip_address(lease.get('ip', '0.0.0.0'))
    elif sort_key == 'expires':
        # Use datetime.min for leases without an expiration to sort them first
        key_func = lambda lease: lease.get('ends') or datetime.min
    elif sort_key == 'hostname':
        # Sort by the final displayed hostname for consistency
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

    for lease in sorted_leases:
        client_hostname = lease.get('hostname')
        vendor_hostname = lease.get('vendor_hostname')

        # Create an improved composite hostname string
        if client_hostname:
            if vendor_hostname and client_hostname != vendor_hostname:
                hostname = f"{client_hostname} ({vendor_hostname})"
            else:
                hostname = client_hostname
        else: # No client_hostname provided
            hostname = vendor_hostname or "<no-hostname>"

        expires_str = lease['ends'].strftime('%Y-%m-%d %H:%M:%S') if lease.get('ends') else "N/A"
        model = lease.get('model') or "N/A"
        serial = lease.get('serial') or "N/A"

        print(f"  {hostname:<25} {lease['ip']:<15} {lease['mac']:<17}   {model:<12} {serial:<18} {expires_str}")
    
    if dhcp.leases_v6:
        print("\n--- Active Dynamic Leases (IPv6) ---")
        # Print header
        print(f"  {'IP Address':<40} {'MAC Address':<17}   {'Expires'}")
        print(f"  {'-'*40} {'-'*17}   {'-'*19}")

        sorted_leases_v6 = sorted(dhcp.leases_v6.values(), key=lambda l: ipaddress.ip_address(l.get('ip', '::')))
        for lease in sorted_leases_v6:
            expires_str = lease['ends'].strftime('%Y-%m-%d %H:%M:%S') if lease.get('ends') else "N/A"
            mac = lease.get('mac') or "N/A (not DUID-LLT)"
            print(f"  {lease['ip']:<40} {mac:<17}   {expires_str}")

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

    for lease in dhcp.leases.values():
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

    # Also search in IPv6 leases
    for lease in dhcp.leases_v6.values():
        lease_ip = lease.get('ip') or ""
        lease_mac = (lease.get('mac') or "").lower()

        if (term in lease_ip or
            term in lease_mac):
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
    num_leases = len(dhcp.leases)
    status = dhcp.get_dhcp_service_status()

    print(f"  Active Dynamic Leases:   {num_leases}")
    print(f"  Service Status ({dhcp.dhcp_service_name}): {status}")

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

    subparsers = parser.add_subparsers(dest='command', required=True, help='Available commands')

    # --- List command ---
    parser_list = subparsers.add_parser('list', help='List active leases.')
    parser_list.add_argument('filter_terms', nargs='*', help='Optional: Filter list by one or more search terms (IP, MAC, hostname, etc.).')
    parser_list.add_argument('--sort-by', choices=['hostname', 'ip', 'mac', 'model', 'serial', 'expires'], default='hostname', help='Column to sort the list by.')
    parser_list.add_argument('--case-sensitive', action='store_true', help='Perform a case-sensitive filter.')
    parser_list.add_argument('--reverse', action='store_true', help='Sort in descending order.')
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

    args = parser.parse_args()
    
    # Initialize DhcpAdmin and call the appropriate handler function
    dhcp = DhcpAdmin(lease_file=args.lease_file, lease_file_v6=args.lease_file_v6)
    args.func(args, dhcp)

    logging.info("--- Process Complete ---")

if __name__ == "__main__":
    main()