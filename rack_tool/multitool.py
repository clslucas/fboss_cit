#!/usr/bin/env python3

import argparse
import getpass
import sys
import os
import concurrent.futures
import json
from contextlib import contextmanager
import time
import subprocess
import re
from datetime import datetime, timezone
import paramiko
import socket

# --- Default Configuration ---
CONFIG_FILE = "config.json"
MAX_WORKERS = 15
CONNECTION_RETRIES = 3 # Number of times to retry a connection
RETRY_DELAY_SECONDS = 1 # Delay between retries

class Colors:
    """A class to hold ANSI color codes for terminal output."""
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m' # No Color

def increment_mac(mac_string):
    """Increments a MAC address by one."""
    if not isinstance(mac_string, str) or not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_string):
        return None
    try:
        mac_int = int(mac_string.replace(':', ''), 16) + 1
        mac_int = 0 if mac_int > 0xffffffffffff else mac_int
        return ':'.join(f'{mac_int:012x}'[i:i+2] for i in range(0, 12, 2))
    except (ValueError, TypeError):
        return None

def _parse_lease_time(time_str):
    """Helper to parse common lease time formats."""
    for fmt in ('%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(time_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None

def _parse_dhcp_leases(file_path):
    """Parses a dhcpd.leases file and returns a dictionary of all active leases."""
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

def get_local_arp_table(debug=False):
    """
    Executes the 'arp -n' command locally and parses its output into a
    dictionary mapping MAC addresses to IP addresses.

    Returns:
        dict: A dictionary where keys are MAC addresses (str) and values are
              IP addresses (str). Returns an empty dict if 'arp' command fails.
    """
    arp_table = {}
    if debug:
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

def _resolve_th6_ips_from_config_and_leases(th6_data, local_arp_table, leases_by_mac, leases_by_serial, debug=False):
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
            if debug: print(f"DEBUG: Found BMC for SN {serial} via DHCP: IP={bmc_ip}, MAC={bmc_mac}")
            if not x86_ip and bmc_mac:
                x86_mac_to_find = increment_mac(bmc_mac)
                if x86_mac_to_find:
                    x86_lease = leases_by_mac.get(x86_mac_to_find.lower())
                    if x86_lease:
                        x86_ip = x86_lease.get('ip')
                        if debug: print(f"DEBUG: Found x86 for SN {serial} via DHCP: IP={x86_ip}, MAC={x86_mac_to_find}")

    # Fallback to ARP lookup if IPs are not specified
    if not bmc_ip and mac:
        bmc_ip = local_arp_table.get(mac.lower())
    if not x86_ip and mac:
        x86_mac = increment_mac(mac)
        if x86_mac:
            x86_ip = local_arp_table.get(x86_mac.lower())

    return x86_ip, bmc_ip

class ConnectionManager:
    """Manages SSH connection and retry logic for a single host."""
    def __init__(self, hostname, username, password, proxy_client=None):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.proxy_client = proxy_client

    @contextmanager
    def get_connection(self, debug=False):
        """
        A context manager to establish and clean up an SSH connection with retry logic.
        Yields a connected Paramiko client or raises an exception if connection fails.
        """
        client = None
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            last_exception = None
            for attempt in range(CONNECTION_RETRIES):
                try:
                    if self.proxy_client:
                        # Add a check to ensure the proxy client is active before proceeding.
                        if not self.proxy_client.get_transport() or not self.proxy_client.get_transport().is_active():
                            raise paramiko.SSHException("Proxy client is not connected.")

                        # Connect via a proxy (jump host)
                        proxy_transport = self.proxy_client.get_transport()
                        dest_addr = (self.hostname, 22)
                        local_addr = ('127.0.0.1', 0) # Ephemeral port
                        proxy_channel = proxy_transport.open_channel("direct-tcpip", dest_addr, local_addr)
                        client.connect(
                            hostname=self.hostname, username=self.username, password=self.password,
                            allow_agent=self.password is None, look_for_keys=self.password is None, sock=proxy_channel
                        )
                    else:
                        # Direct connection
                        client.connect(
                            hostname=self.hostname, username=self.username, password=self.password, timeout=10,
                            allow_agent=self.password is None, look_for_keys=self.password is None
                        )
                    yield client  # Connection successful, yield to the 'with' block
                    return      # Exit after successful operation
                except paramiko.AuthenticationException as e:
                    # Don't retry on authentication failure. It's not a transient error.
                    last_exception = e
                    break # Exit the retry loop immediately
                except (paramiko.SSHException, socket.error, TimeoutError) as e:
                    # Catch specific, common network-related errors that are worth retrying.
                    last_exception = e
                    if attempt < CONNECTION_RETRIES - 1:
                        if debug: print(f"{Colors.YELLOW}   DEBUG: Connection to '{self.hostname}' failed (attempt {attempt + 1}/{CONNECTION_RETRIES}). Retrying in {RETRY_DELAY_SECONDS}s... ({type(e).__name__}: {e}){Colors.NC}", file=sys.stderr)
                        time.sleep(RETRY_DELAY_SECONDS)
                    # The loop will continue to the next attempt.
            
            raise last_exception  # Re-raise the last exception after all retries fail
        finally:
            if client:
                client.close()

class RemoteOperation:
    """Encapsulates remote operations for a single host, using a ConnectionManager."""
    def __init__(self, conn_manager: ConnectionManager):
        self.conn_manager = conn_manager
        self.hostname = conn_manager.hostname

    def execute_command(self, command, use_sudo=False, log_dir=None, command_timeout=None, debug=False):
        """
        Connects to a remote host and executes a command.
        Returns: A dictionary containing the operation result.
        """
        log_file = None
        full_output = ""
 
        try:
            with self.conn_manager.get_connection(debug=debug) as client: # Handles connection errors
                if log_dir:
                    log_path = os.path.join(log_dir, f"{self.hostname}.log")
                    log_file = open(log_path, 'a') # Append to log for multiple commands in one run
                    log_file.write(f"--- Command: {command} ---\n")

                final_command = command
                if use_sudo:
                    # Use 'sudo -S' to read password from stdin.
                    # The -p '' flag prevents sudo from printing its default password prompt.
                    final_command = f"sudo -S -p '' {command}"

                # Wrap the command to source the profile, ensuring PATH is set correctly.
                # This makes commands like 'wedge_power.sh' work without the full path.
                # Using 'bash -c' is safer than 'bash -l -c' as it avoids sourcing login-specific
                # files that might contain interactive commands, which can cause hangs.
                escaped_command = final_command.replace("'", "'\\''")
                wrapped_command = f"bash -c 'export PATH=/opt/py39/bin:/usr/local/bin:$PATH; {escaped_command}'"
                stdin, stdout, stderr = client.exec_command(wrapped_command, timeout=command_timeout, get_pty=True) # get_pty is good for interactivity
                
                # If using sudo, write the password from the connection manager to stdin.
                if use_sudo and self.conn_manager.password:
                    stdin.write(self.conn_manager.password + '\n')
                    stdin.flush()
                stdin.close()
 
                # --- Real-time Streaming to prevent deadlocks ---
                # When get_pty=True, stderr is merged into stdout. Reading from the channel
                # directly in a non-blocking way is the most robust method.
                stdout_chunks = []
                channel = stdout.channel

                while not channel.exit_status_ready():
                    # Check for data on stdout before attempting to read
                    if channel.recv_ready():
                        stdout_chunks.append(channel.recv(4096))
                    else:
                        # Sleep briefly to prevent a high-CPU busy-wait loop.
                        time.sleep(0.1)

                # After the command finishes, read any remaining data from the buffer.
                while channel.recv_ready():
                    stdout_chunks.append(channel.recv(4096))

                # Now that all output has been read, we can safely get the exit status.
                exit_status = channel.recv_exit_status()

                # Decode all collected chunks at once.
                full_output = b"".join(stdout_chunks).decode('utf-8', errors='replace')
            
            return {
                "hostname": self.hostname,
                "success": exit_status == 0,
                "exit_code": exit_status,
                "stdout": full_output,
                "stderr": "", # Stderr is in stdout
            }

        except (paramiko.AuthenticationException, paramiko.SSHException, socket.error) as e:
            # These exceptions are raised by get_connection if it ultimately fails.
            return {"hostname": self.hostname, "success": False, "exit_code": -1, "stdout": "", "stderr": f"FAILURE (Connection): Could not connect to '{self.hostname}': {type(e).__name__}: {e}\n"}
        except Exception as e:
            # This catches other errors, likely during command execution itself.
            return {
                "hostname": self.hostname, "success": False, "exit_code": -1,
                "stdout": full_output, # Return any partial output captured
                "stderr": f"FAILURE (Execution): An unexpected error occurred on '{self.hostname}': {e}"
            }

    def _mkdir_p(self, sftp, remote_directory):
        """
        A helper function to emulate `mkdir -p` on a remote SFTP server.
        It creates a directory and all its parent directories if they don't exist.
        """
        if remote_directory == '/':
            # The root directory always exists.
            return
        if remote_directory == '':
            # An empty path is not a valid directory.
            return

        try:
            sftp.stat(remote_directory)
        except FileNotFoundError:
            # The directory does not exist, so we need to create it.
            # Recursively call to create the parent directory first.
            parent_dir = os.path.dirname(remote_directory.rstrip('/'))
            self._mkdir_p(sftp, parent_dir)
            sftp.mkdir(remote_directory)

    def _transfer_directory(self, sftp, local_path, remote_path):
        """
        Recursively uploads a local directory to a remote path.
        """
        # Create the base directory on the remote host
        remote_base_dir = os.path.join(remote_path, os.path.basename(local_path))
        self._mkdir_p(sftp, remote_base_dir)

        for dirpath, dirnames, filenames in os.walk(local_path):
            # Create remote directories
            for dirname in dirnames:
                local_dir = os.path.join(dirpath, dirname)
                remote_dir = os.path.join(remote_base_dir, os.path.relpath(local_dir, local_path))
                self._mkdir_p(sftp, remote_dir)

            # Upload files
            for filename in filenames:
                local_file = os.path.join(dirpath, filename)
                remote_file = os.path.join(remote_base_dir, os.path.relpath(local_file, local_path))
                sftp.put(local_file, remote_file)

    def transfer_file(self, local_path, remote_path, debug=False): # Now handles both files and directories
        """
        Connects to a remote host and transfers a file using SCP.
        Returns: A dictionary containing the operation result.
        """
        try:
            with self.conn_manager.get_connection(debug=debug) as client: # Handles connection errors
                with client.open_sftp() as sftp:
                    if os.path.isdir(local_path):
                        # It's a directory, use the recursive transfer logic.
                        self._transfer_directory(sftp, local_path, remote_path)
                        transfer_type = "Directory"
                    else:
                        # It's a single file, use the original logic.
                        remote_file_path = os.path.join(remote_path, os.path.basename(local_path))
                        self._mkdir_p(sftp, os.path.dirname(remote_file_path)) # Ensure destination dir exists
                        sftp.put(local_path, remote_file_path)
                        transfer_type = "File"

            return {
                "hostname": self.hostname, "success": True,
                "message": f"{transfer_type} '{os.path.basename(local_path)}' transferred to '{self.hostname}:{remote_path}'."
            }
        except (paramiko.AuthenticationException, paramiko.SSHException, socket.error) as e:
            return {"hostname": self.hostname, "success": False, "message": f"FAILURE (Connection): Could not connect to '{self.hostname}': {type(e).__name__}: {e}"}
        except paramiko.SFTPError as e:
            return {"hostname": self.hostname, "success": False, "message": f"FAILURE (SFTP): File transfer failed on '{self.hostname}': {e}"}
        except Exception as e:
            return {
                "hostname": self.hostname, "success": False, "message": f"FAILURE (Execution): An unexpected error occurred during transfer to '{self.hostname}': {e}"
            }
 
    def download_file(self, remote_path, local_dir, debug=False):
        """
        Connects to a remote host and downloads a file using SFTP.
        Returns: A dictionary containing the operation result.
        """
        try:
            with self.conn_manager.get_connection(debug=debug) as client:
                # Construct a unique local path to avoid overwriting files from different hosts
                local_filename = f"{self.hostname}_{os.path.basename(remote_path)}"
                local_file_path = os.path.join(local_dir, local_filename)

                with client.open_sftp() as sftp:
                    sftp.get(remote_path, local_file_path)
                       
            return {"hostname": self.hostname, "success": True, "message": f"File downloaded from '{self.hostname}' to '{local_file_path}'."}
        except (paramiko.AuthenticationException, paramiko.SSHException, socket.error) as e:
            return {"hostname": self.hostname, "success": False, "message": f"FAILURE (Connection): Could not connect to '{self.hostname}': {type(e).__name__}: {e}"}
        except paramiko.SFTPError as e:
            return {"hostname": self.hostname, "success": False, "message": f"FAILURE (SFTP): File download failed on '{self.hostname}': {e}"}
        except Exception as e:
            return {"hostname": self.hostname, "success": False, "message": f"FAILURE (Execution): An unexpected error occurred during download from '{self.hostname}': {e}"}

    def upload_and_execute(self, local_path, remote_dir, script_args, command_timeout=None, debug=False):
        """
        Uploads a script, makes it executable, and then runs it on the remote host.
        """
        full_output = ""
 
        try:
            with self.conn_manager.get_connection(debug=debug) as client: # Handles connection errors
                # --- Part 1: Upload the file ---
                with client.open_sftp() as sftp:
                    remote_script_name = os.path.basename(local_path) # e.g., "my_script.sh"
                    remote_script_path = f"{remote_dir.rstrip('/')}/{remote_script_name}" # e.g., "/tmp/my_script.sh"
                    sftp.put(local_path, remote_script_path)

                # --- Part 2: Execute the script ---
                command = f"chmod +x '{remote_script_path}' && '{remote_script_path}' {script_args}"
                # Wrap this command to ensure a consistent execution environment.
                # No interactive check is needed here as we are explicitly executing a script,
                # but we still need to handle potential special characters in the command string.
                escaped_command = command.replace("'", "'\\''")
                wrapped_command = f"bash -c '{escaped_command}'"
                stdin, stdout, stderr = client.exec_command(wrapped_command, timeout=command_timeout, get_pty=True)
                
                # Close stdin to signal that no input will be sent. This prevents hangs.
                stdin.close()

                # Use the same robust, non-blocking streaming logic as execute_command
                # to prevent deadlocks with scripts that produce large amounts of output.
                stdout_chunks = []
                channel = stdout.channel

                while not channel.exit_status_ready():
                    if channel.recv_ready():
                        stdout_chunks.append(channel.recv(4096))
                    else:
                        time.sleep(0.1)

                # Drain any remaining data
                while channel.recv_ready(): # lgtm [py/redundant-loop]
                    stdout_chunks.append(channel.recv(4096))

                # Now that reading is complete, get the exit status.
                exit_status = channel.recv_exit_status()
                full_output = b"".join(stdout_chunks).decode('utf-8', errors='replace')

            return {
                "hostname": self.hostname,
                "success": exit_status == 0,
                "exit_code": exit_status,
                "stdout": full_output,
                "stderr": "", # Stderr is in stdout
            }
        except (paramiko.AuthenticationException, paramiko.SSHException, socket.error) as e:
            return {"hostname": self.hostname, "success": False, "exit_code": -1, "stdout": "", "stderr": f"FAILURE (Connection): Could not connect to '{self.hostname}': {type(e).__name__}: {e}\n"}
        except paramiko.SFTPError as e:
            return {"hostname": self.hostname, "success": False, "exit_code": -1, "stdout": "", "stderr": f"FAILURE (SFTP): Script upload failed on '{self.hostname}': {e}"}
        except Exception as e:
            return {
                "hostname": self.hostname, "success": False, "exit_code": -1,
                "stdout": full_output, "stderr": f"FAILURE (Execution): An unexpected error occurred on '{self.hostname}': {e}"
            }

def _get_credentials_for_host(client_ip, args, device_map):
    """
    Determines the correct username and password for a given host IP.
    It prioritizes device-specific credentials from the config over general ones.

    Args:
        client_ip (str): The IP address of the target host.
        args: The parsed command-line arguments object.
        device_map (dict): A pre-processed map of IPs to device configurations.

    Returns:
        A tuple of (username, password).
    """
    # Start with the default user and password determined from args/prompts
    user = args.user
    password = args.auth_password
    active_profile = args.config_data.get('profiles', {}).get(args.config_data.get('active_profile'), {})

    # Check if the target is a known BMC to select the right credentials.
    if active_profile:
        is_bmc_target = False
        for device in args.device_map.values():
            if device.get('bmc_ip') == client_ip:
                is_bmc_target = True
                break
        
        if is_bmc_target:
            # Only override if --user wasn't specified
            if not args.user: user = active_profile.get('th6_bmc_username', user)
            if not args.prompt_password: password = active_profile.get('th6_bmc_password', password)
        else: # It's an x86 target
            if not args.user: user = active_profile.get('th6_x86_username', user)
            if not args.prompt_password: password = active_profile.get('th6_x86_password', password)
    return user, password

def _run_parallel_operations(args, operation_name, operation_args_tuple, result_formatter, proxy_client=None, config=None):
    """
    A generic helper to run remote operations in parallel using a thread pool.

    Args:
        args: The command-line arguments.
        operation_name (str): The name of the method to call on the RemoteOperation object.
        operation_args_tuple (tuple): A tuple of arguments to pass to the operation method.
        result_formatter (function): A function to call to print the result for each host.
        proxy_client (paramiko.SSHClient, optional): A connected client to use as a proxy.
        config (dict, optional): The loaded configuration for credential lookup.

    Returns:
        A tuple of (success_count, failure_count).
    """
    # For JSON output, we must collect all results first.
    # For standard output, we will print them as they complete.
    json_results = [] if args.json else None
    success_count = 0
    failure_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_client = {}
        for client_ip in args.clients:
            # Use the centralized function to get credentials
            user, password = _get_credentials_for_host(client_ip, args, args.device_map)
            
            conn_manager = ConnectionManager(client_ip, user, password, proxy_client=proxy_client)
            op = RemoteOperation(conn_manager)
            # Get the method from the RemoteOperation instance by name
            operation_func = getattr(op, operation_name)
            # Pass proxy_client to all operations; they will use it if needed.
            future = executor.submit(operation_func, *operation_args_tuple)
            future_to_client[future] = op.hostname

        completed_futures = concurrent.futures.as_completed(future_to_client)
        for future in completed_futures:
            try:
                result = future.result()
                if result.get('success'):
                    success_count += 1
                else:
                    failure_count += 1

                if args.json:
                    json_results.append(result)
                else:
                    # Print result as soon as it's ready for real-time feedback
                    result_formatter(args, result)

            except Exception as exc:
                client = future_to_client[future]
                failure_count += 1
                # Create a standard error result structure
                error_result = {
                    "hostname": client, "success": False, "exit_code": -1,
                    "stdout": "", "stderr": f"EXCEPTION: An error occurred while processing host '{client}': {exc}"
                }
                error_result["message"] = error_result["stderr"]
                if args.json:
                    json_results.append(error_result)
                else:
                    result_formatter(args, error_result)

    if args.json:
        print(json.dumps(json_results, indent=2))

    return success_count, failure_count

def _print_exec_style_result(args, res):
    """Formatter for results that include stdout/stderr (exec, upload-exec)."""
    print(f"-> Results for {Colors.YELLOW}{args.user}@{res['hostname']}{Colors.NC}:")
    if res.get('stdout'):
        print(res['stdout'], end="")
    if res.get('stderr'):
        print(f"{Colors.RED}{res['stderr']}{Colors.NC}", end="")
    
    print("----------------------------------------")
    if res.get('success'):
        print(f"{Colors.GREEN}   SUCCESS: Operation completed on '{res['hostname']}'.{Colors.NC}")
    else:
        # Only print a generic failure if a specific one isn't already in stderr
        if "FAILURE:" not in res.get('stderr', '') and "EXCEPTION:" not in res.get('stderr', ''):
            exit_code = res.get('exit_code', -1)
            print(f"{Colors.RED}   FAILURE: Operation failed on '{res['hostname']}' with exit code {exit_code}.{Colors.NC}")
    print("----------------------------------------")

def _print_transfer_style_result(args, res):
    """Formatter for simple success/failure messages (scp, download)."""
    print(f"-> Results for {Colors.YELLOW}{args.user}@{res['hostname']}{Colors.NC}:")
    print("----------------------------------------")
    color = Colors.GREEN if res.get('success') else Colors.RED
    status_text = "SUCCESS" if res['success'] else "FAILURE"
    # The 'message' key is populated by transfer_file, download_file, and the exception handler
    message = res.get('message', 'No message returned.')
    print(f"{color}   {status_text}: {message}{Colors.NC}")
    print("----------------------------------------")

def _run_pre_check(args, config):
    """
    Performs a parallel connection check on all target hosts.
    Returns a list of reachable host IPs.
    """
    if not args.json:
        print(f"{Colors.BLUE}Performing reachability pre-check on {len(args.clients)} host(s)...{Colors.NC}")
        print("=======================================")

    reachable_hosts = []
    unreachable_hosts = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_client = {}
        for client_ip in args.clients:
            user, password = _get_credentials_for_host(client_ip, args, args.device_map)
            conn_manager = ConnectionManager(client_ip, user, password)
            # Use a simple socket check for reachability, which is faster than a full SSH handshake.
            future = executor.submit(check_host_reachability, client_ip, 22)
            future_to_client[future] = client_ip

        for future in concurrent.futures.as_completed(future_to_client):
            hostname = future_to_client[future]
            try:
                result = future.result()
                if result['success']:
                    reachable_hosts.append(hostname)
                    if not args.json: print(f"{Colors.GREEN}[  OK  ]{Colors.NC} Host {hostname} is reachable.")
                else:
                    unreachable_hosts.append(hostname)
                    if not args.json: print(f"{Colors.RED}[ FAIL ]{Colors.NC} Host {hostname} is unreachable: {result['error']}")
            except Exception as exc:
                unreachable_hosts.append(hostname)
                if not args.json: print(f"{Colors.RED}[ FAIL ]{Colors.NC} Host {hostname} check failed with exception: {exc}")

    if not args.json:
        print("=======================================")
        print(f"Pre-check complete. Proceeding with {len(reachable_hosts)} reachable host(s).")
    return reachable_hosts

def check_host_reachability(hostname, port):
    """
    Checks if a host is reachable on a specific port using a socket connection.
    This is faster than a full SSH connection for pre-checks.
    """
    try:
        with socket.create_connection((hostname, port), timeout=5) as sock:
            return {"hostname": hostname, "success": True}
    except socket.timeout:
        return {"hostname": hostname, "success": False, "error": "Connection timed out"}
    except socket.error as e:
        return {"hostname": hostname, "success": False, "error": str(e)}
    except Exception as e:
        return {"hostname": hostname, "success": False, "error": f"An unexpected error occurred: {e}"}

def handle_exec(args):
    """Orchestrates remote command execution on x86 or BMC hosts."""
    target_type = "BMC" if args.bmc else "x86"
    if not args.json:
        print(f"{Colors.BLUE}Executing command on {target_type} targets: {Colors.YELLOW}{args.command}{Colors.NC}")
        if args.proxy:
            print(f"{Colors.BLUE}Using proxy: {Colors.YELLOW}{args.proxy}{Colors.NC}")
        print("=======================================")

    # Create log directory if specified
    log_dir = args.log_dir
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            if not args.json:
                print(f"{Colors.BLUE}Logging output to directory: {log_dir}{Colors.NC}")
        except OSError as e:
            print(f"{Colors.RED}Error creating log directory '{log_dir}': {e}{Colors.NC}", file=sys.stderr)
            log_dir = None

    op_args = (args.command, args.sudo, log_dir, args.timeout, args.debug)

    # If a proxy is specified, connect to it first.
    if args.proxy:
        proxy_conn_manager = ConnectionManager(args.proxy, args.user, args.auth_password)
        try:
            with proxy_conn_manager.get_connection(debug=args.debug) as proxy_client:
                return _run_parallel_operations(args, "execute_command", op_args, _print_exec_style_result, config=args.config_data, proxy_client=proxy_client)
        except Exception as e:
            print(f"{Colors.RED}Fatal Error: Could not connect to proxy host '{args.proxy}'. Aborting. ({e}){Colors.NC}", file=sys.stderr)
            for client_ip in args.clients:
                _print_exec_style_result(args, {"hostname": client_ip, "success": False, "stderr": f"FAILURE: Proxy host '{args.proxy}' connection failed."})
            return 0, len(args.clients)
    else:
        # No proxy, run directly.
        return _run_parallel_operations(args, "execute_command", op_args, _print_exec_style_result, config=args.config_data, proxy_client=None)


def handle_scp(args):
    """Orchestrates remote file transfer."""
    if not os.path.exists(args.local_file):
        print(f"{Colors.RED}Error: Local path '{args.local_file}' not found.{Colors.NC}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"{Colors.BLUE}Starting file transfer of '{args.local_file}' to {len(args.clients)} host(s)...{Colors.NC}")
        print("=======================================")

    op_args = (args.local_file, args.remote_path, args.debug)
    return _run_parallel_operations(args, "transfer_file", op_args, _print_transfer_style_result)

def handle_download(args):
    """Orchestrates remote file download."""
    try:
        os.makedirs(args.local_dir, exist_ok=True)
    except OSError as e:
        print(f"{Colors.RED}Error creating local directory '{args.local_dir}': {e}{Colors.NC}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"{Colors.BLUE}Starting download of '{args.remote_file}' from {len(args.clients)} host(s) to '{args.local_dir}'...{Colors.NC}")
        print("=======================================")

    op_args = (args.remote_file, args.local_dir, args.debug)
    return _run_parallel_operations(args, "download_file", op_args, _print_transfer_style_result)

def handle_upload_exec(args):
    """Orchestrates script upload and execution."""
    if not os.path.isfile(args.local_file):
        print(f"{Colors.RED}Error: Local file '{args.local_file}' not found.{Colors.NC}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"{Colors.BLUE}Uploading and executing '{os.path.basename(args.local_file)}' on {len(args.clients)} host(s)...{Colors.NC}")
        print("=======================================")

    op_args = (args.local_file, args.remote_path, args.script_args, args.timeout, args.debug)
    return _run_parallel_operations(args, "upload_and_execute", op_args, _print_exec_style_result)

def handle_interactive(args): # New multi-host implementation
    """Orchestrates a multi-host interactive shell session."""
    import select
    import tty
    import termios

    print(f"{Colors.BLUE}Starting interactive session on {len(args.clients)} host(s)...{Colors.NC}")
    print(f"{Colors.YELLOW}--- Type 'exit' or press Ctrl+D to close all sessions. ---{Colors.NC}")

    connections = []
    try:
        # --- Establish all connections first ---
        for client_ip in args.clients:
            user, password = _get_credentials_for_host(client_ip, args, args.device_map)
            conn_manager = ConnectionManager(client_ip, user, password)
            try:
                # We need to manage the client lifecycle manually here, so we don't use the context manager
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(hostname=client_ip, username=user, password=password, timeout=10)
                channel = client.invoke_shell()
                channel.settimeout(0.0)
                connections.append({'client': client, 'channel': channel, 'hostname': client_ip})
                # Add a state to track if we need to print a hostname prefix for this channel's output.
                connections[-1]['at_start_of_line'] = True

                print(f"{Colors.GREEN}[CONNECT]{Colors.NC} Successfully opened shell on {client_ip}")
            except Exception as e:
                print(f"{Colors.RED}[ FAIL  ]{Colors.NC} Could not open shell on {client_ip}: {e}")

        if not connections:
            print(f"{Colors.RED}No active connections. Exiting.{Colors.NC}")
            return 0, len(args.clients)

        # --- Set up terminal for raw input ---
        original_tty_settings = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())

        # --- Main I/O Loop ---
        while connections:
            # Monitor stdin and all active channels for readability
            readable_channels = [conn['channel'] for conn in connections]
            read_ready, _, _ = select.select([sys.stdin] + readable_channels, [], [])

            # --- Handle remote output ---
            for channel in readable_channels:
                if channel in read_ready:
                    try:
                        out = channel.recv(1024)
                        if not out: # Channel has been closed by the remote end
                            # Find the connection to remove it
                            conn_to_remove = next((c for c in connections if c['channel'] == channel), None)
                            if conn_to_remove: # lgtm [py/trivial-conditional]
                                # Ensure the cursor is at the start of a new line before printing the disconnect message.
                                if not conn_to_remove.get('at_start_of_line', True):
                                    sys.stdout.write('\r\n')
                                sys.stdout.write(f"{Colors.YELLOW}[DISCONNECTED]{Colors.NC} Shell closed on {conn_to_remove['hostname']}\r\n")
                                sys.stdout.flush()
                                conn_to_remove['client'].close() # lgtm [py/closing-outer-resource]
                                connections.remove(conn_to_remove) # lgtm [py/iterating-over-collection-and-removing]
                            continue

                        # Find the connection object to access its state
                        conn = next((c for c in connections if c['channel'] == channel), None)
                        if not conn: continue

                        # --- Smarter Output Prefixing ---
                        # Instead of prefixing every line, we only prefix when we know we are at the start of a new line.
                        # This prevents breaking the layout of full-screen interactive applications like 'vi' or 'top'.
                        output_str = out.decode('utf-8', 'replace')
                        if conn.get('at_start_of_line', True):
                            sys.stdout.write(f"{Colors.CYAN}[{conn['hostname']}]{Colors.NC} ")
                        sys.stdout.write(output_str)
                        # Update the state: we are at the start of a new line only if the output ended with a newline.
                        conn['at_start_of_line'] = output_str.endswith('\n')
                        sys.stdout.flush()

                    except socket.timeout:
                        pass # This is expected with non-blocking channels

            # --- Handle local keyboard input ---
            if sys.stdin in read_ready:
                char = sys.stdin.read(1)
                if not char: # EOF (Ctrl+D)
                    break
                
                # Broadcast the input to all active channels
                for conn in connections:
                    conn['channel'].send(char)

        return len(args.clients) - len(connections), len(connections)

    except KeyboardInterrupt:
        print(f"\r\n{Colors.YELLOW}--- Interrupted by user. Closing all sessions. ---{Colors.NC}\r\n")
        return len(args.clients) - len(connections), len(connections)
    finally:
        # --- Cleanup ---
        if 'original_tty_settings' in locals():
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, original_tty_settings)
        
        for conn in connections:
            conn['client'].close()
        
        print(f"{Colors.GREEN}--- All interactive sessions closed. ---{Colors.NC}")

def load_and_extract_config(config_path, debug=False):
    """
    Loads configuration from the rack_diagnostics.py-style config.json file.
    It extracts client lists (x86, bmc) and credentials from the active profile,
    resolving IPs from serial numbers if necessary.
    """
    processed_config = {
        'th6_x86_hosts': [],
        'th6_bmc_hosts': [],
        'profiles': {},
        'active_profile': None,
    }
    if not os.path.exists(config_path):
        if config_path != CONFIG_FILE:
            print(f"{Colors.RED}Error: Configuration file '{config_path}' not found.{Colors.NC}", file=sys.stderr)
            sys.exit(1)
        return processed_config

    try:
        with open(config_path, 'r') as f:
            content = re.sub(r"//.*", "", f.read())
            content = re.sub(r",\s*([}\]])", r"\1", content)
            full_config = json.loads(content)

        active_profile_name = full_config.get("active_profile")
        profile_data = full_config.get("profiles", {}).get(active_profile_name)
        
        processed_config['profiles'] = full_config.get('profiles', {})
        processed_config['active_profile'] = active_profile_name

        if not profile_data:
            print(f"{Colors.YELLOW}Warning: Active profile '{active_profile_name}' not found in config.{Colors.NC}", file=sys.stderr)
            return processed_config

        # --- DHCP Lease Parsing for SN resolution ---
        # Iterate over dhcp_lease_files and use the first one that successfully parses
        leases_by_mac = {}
        leases_by_serial = {}
        lease_file_paths = full_config.get("dhcp_lease_files", []) # Get list from config

        for path in lease_file_paths:
            if not path: continue
            leases = _parse_dhcp_leases(path)
            if leases: # If parsing was successful and returned data
                if debug: print(f"{Colors.YELLOW}   DEBUG: DHCP lease file parsed from '{path}'. Attempting to resolve IPs by SN...{Colors.NC}")
                for ip, lease_data in leases.items(): # Populate maps from this successful parse
                    if lease_data.get('mac'): leases_by_mac[lease_data['mac'].lower()] = lease_data
                    if lease_data.get('serial'): leases_by_serial[lease_data['serial']] = lease_data
                break # Exit loop after first successful parse
        
        # --- IP Resolution ---
        local_arp_table = get_local_arp_table(debug)
        th6_devices = profile_data.get("th6_devices", [])
        for device in th6_devices:
            x86_ip, bmc_ip = _resolve_th6_ips_from_config_and_leases(device, local_arp_table, leases_by_mac, leases_by_serial, debug)
            if x86_ip: processed_config['th6_x86_hosts'].append(x86_ip)
            if bmc_ip: processed_config['th6_bmc_hosts'].append(bmc_ip)

        # Extract credentials from the profile level.
        processed_config['default_x86_username'] = profile_data.get('th6_x86_username')
        processed_config['default_x86_password'] = profile_data.get('th6_x86_password')
        processed_config['default_bmc_username'] = profile_data.get('th6_bmc_username')
        processed_config['default_bmc_password'] = profile_data.get('th6_bmc_password')

        return processed_config
    except (json.JSONDecodeError, IOError) as e:
        print(f"{Colors.RED}Error reading or parsing '{config_path}': {e}.{Colors.NC}", file=sys.stderr)
        return {}

def create_parser():
    """Creates and configures the argument parser for the tool."""
    parser = argparse.ArgumentParser(
        description="A multi-purpose tool to execute commands or transfer files to multiple remote hosts in parallel.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
GENERAL USAGE:
  {os.path.basename(sys.argv[0])} <action> [action-arguments] [clients...] [options]

  <action> can be 'exec', 'scp', 'download', or 'upload-exec'.
  Run '{os.path.basename(sys.argv[0])} <action> -h' for more details on a specific action.
"""
    )
    subparsers = parser.add_subparsers(dest="action", required=True, help="Available actions")

    # --- Parent parser for shared arguments ---
    parent_parser = argparse.ArgumentParser(add_help=False)
    # This is intentionally left blank. Sub-parsers will add the positional arguments.
    parent_parser.add_argument("--config", default=CONFIG_FILE, help=f"Path to a JSON configuration file. (Default: '{CONFIG_FILE}')")
    parent_parser.add_argument("-u", "--user", help="Remote username. Overrides username from config file.")
    parent_parser.add_argument("-p", "--prompt-password", action="store_true", help="Prompt for a password. Overrides SSH keys or the hardcoded default.")
    parent_parser.add_argument("--json", action="store_true", help="Output results in JSON format.")
    parent_parser.add_argument("--debug", action="store_true", help="Enable debug mode for verbose connection messages.")
    parent_parser.add_argument("--pre-check", action="store_true", help="Perform a reachability check on all hosts before running the main operation.")

    # --- 'exec' sub-command ---
    parser_exec = subparsers.add_parser("exec", parents=[parent_parser], help="Execute a command on remote hosts.", epilog="""
Examples for 'exec':
  # Run 'uptime' on default x86 hosts from config
  %(prog)s "uptime"

  # Run 'ls' on specific hosts and get JSON output
  %(prog)s "ls -l /tmp" 192.168.1.100 192.168.1.101 --json

  # Run a command and save logs for each host
  %(prog)s "cat /var/log/syslog" 192.168.1.100 --log-dir /tmp/logs

  # Run a command on default BMC hosts via a proxy
  %(prog)s --bmc --proxy 192.168.0.1 "wedge_power.sh status"
""")
    parser_exec.add_argument("command", help="The command to execute on the target hosts (in quotes).")
    parser_exec.add_argument("clients", nargs='*', help="Space-separated list of target host IPs. Overrides --use-x86-hosts and --use-bmc-hosts.")
    parser_exec.add_argument("--bmc", action="store_true", help="Execute the command on BMCs. Default is to target x86 hosts.")
    parser_exec.add_argument("--proxy", help="The IP address of a proxy/jump host to connect through (e.g., a BMC to reach an x86).")
    parser_exec.add_argument("--log-dir", help="Directory to save command output logs.", metavar="PATH")
    parser_exec.add_argument("--timeout", type=int, default=300, help="Timeout in seconds for the remote command. (Default: 300)")
    parser_exec.add_argument("--sudo", action="store_true", help="Run the command with sudo. The password from --prompt-password or config will be used.")
    parser_exec.set_defaults(func=handle_exec)

    # --- 'scp' sub-command ---
    parser_scp = subparsers.add_parser("scp", parents=[parent_parser], help="Upload a file to remote hosts.", epilog="""
Examples for 'scp':
  # Upload a script to /tmp on hosts from the default list
  %(prog)s my_script.sh /tmp/

  # Upload a file to a specific host, prompting for a password
  %(prog)s ./config.yaml /home/user/ 10.0.0.5 -p
""")
    parser_scp.add_argument("local_file", help="The local file or directory to transfer.")
    parser_scp.add_argument("remote_path", help="The destination directory on remote hosts.")
    parser_scp.add_argument("clients", nargs='*', help="Space-separated list of client IPs. If omitted, uses the default list from the config file.")
    parser_scp.set_defaults(func=handle_scp)

    # --- 'download' sub-command ---
    parser_download = subparsers.add_parser("download", parents=[parent_parser], help="Download a file from remote hosts.", epilog="""
Examples for 'download':
  # Download a log file from all default hosts into './downloads'
  %(prog)s /var/log/syslog ./downloads

  # Download a config file from a specific host
  %(prog)s /etc/app/config.json . 192.168.1.100
""")
    parser_download.add_argument("remote_file", help="The full path of the file to download from remote hosts.")
    parser_download.add_argument("local_dir", help="The local directory to save downloaded files into.")
    parser_download.add_argument("clients", nargs='*', help="Space-separated list of client IPs. If omitted, uses the default list from the config file.")
    parser_download.set_defaults(func=handle_download)

    # --- 'upload-exec' sub-command ---
    parser_upload_exec = subparsers.add_parser("upload-exec", parents=[parent_parser], help="Upload a script and execute it.", epilog="""
Examples for 'upload-exec':
  # Upload 'check.sh' to the default remote path (/tmp) and run it
  %(prog)s ./check.sh

  # Upload a script and run it with arguments
  %(prog)s ./setup.sh 192.168.1.100 --remote-path /opt/ --args "--force --verbose"
""")
    parser_upload_exec.add_argument("local_file", help="The local script to upload and execute.")
    parser_upload_exec.add_argument("clients", nargs='*', help="Space-separated list of client IPs. If omitted, uses the default list from the config file.")
    parser_upload_exec.add_argument("--remote-path", default="/tmp", help="The destination directory on remote hosts. (Default: /tmp)")
    parser_upload_exec.add_argument("--args", dest="script_args", default="", help="A string of arguments to pass to the remote script (in quotes).")
    parser_upload_exec.add_argument("--timeout", type=int, default=300, help="Timeout in seconds for the remote script execution. (Default: 300)")
    parser_upload_exec.set_defaults(func=handle_upload_exec)

    # --- 'interactive' sub-command ---
    parser_interactive = subparsers.add_parser("interactive", parents=[parent_parser], help="Open an interactive shell on a single remote host.", epilog="""
Examples for 'interactive' (multi-host):
  # Open an interactive shell on all default x86 hosts
  %(prog)s

  # Open a shell on two specific hosts
  %(prog)s 192.168.1.100 192.168.1.101
""")
    # 'clients' is optional; if omitted, it will use the default list from config.
    parser_interactive.add_argument("clients", nargs='*', help="Space-separated list of target host IPs. If omitted, uses the default host list from the config.")
    parser_interactive.set_defaults(func=handle_interactive)
    
    return parser

def configure_run_from_args(args):
    """Loads config and sets up clients and credentials based on parsed arguments."""

    # --- Setup Debug Logging ---
    if args.debug:
        import logging
        # Create a logger for paramiko and set its level to DEBUG
        paramiko_logger = logging.getLogger("paramiko")
        paramiko_logger.setLevel(logging.DEBUG)
        # Add a handler to print the logs to stderr
        paramiko_logger.addHandler(logging.StreamHandler(sys.stderr))
        if not args.json:
            print(f"{Colors.YELLOW}Debug mode enabled. Paramiko logs will be verbose.{Colors.NC}")

    # --- Load Configuration & Set Defaults ---
    config = load_and_extract_config(args.config, args.debug)
    args.config_data = config # Attach full config to args for credential lookup

    # --- Create an efficient IP-to-device-config lookup map ---
    # This avoids iterating the th6_devices list for every host.
    device_map = {}
    active_profile_name = config.get("active_profile")
    profile_data = config.get("profiles", {}).get(active_profile_name, {})
    th6_devices = profile_data.get("th6_devices", [])
    for device in th6_devices:
        if 'ip' in device:
            device_map[device['ip']] = device
        if 'bmc_ip' in device:
            device_map[device['bmc_ip']] = device
    args.device_map = device_map # Attach the map to args for easy access
    
    # Extract hosts from the active profile
    th6_x86_hosts_from_config = config.get("th6_x86_hosts", [])
    th6_bmc_hosts_from_config = config.get("th6_bmc_hosts", [])

    # Set the default username based on the target type (--bmc or not)
    # Only set user from config if it wasn't provided on the command line.
    if not args.user:
        if args.action == 'exec' and args.bmc:
            args.user = config.get('default_bmc_username')
        else:
            # For x86 exec and all other commands (scp, download), use x86 user
            args.user = config.get('default_x86_username')

    # --- Argument Handling ---
    # Only set default client list if 'clients' argument is not provided by the user.
    if hasattr(args, 'clients') and not args.clients:
        if args.action == 'exec' and args.bmc:
            args.clients = config.get("th6_bmc_hosts", [])
            if not args.json:
                print(f"{Colors.BLUE}Using default TH6 BMC host list from active profile in '{args.config}'.{Colors.NC}")
        else: # Default for 'exec' without '--bmc', and for 'scp', 'download', etc.
            args.clients = config.get("th6_x86_hosts", [])
            if not args.json:
                print(f"{Colors.BLUE}Using default TH6 x86 host list from active profile in '{args.config}'.{Colors.NC}")

        # After setting the default, check if the list is still empty.
        if not args.clients:
            print(f"{Colors.RED}Error: No client IPs provided and no default hosts found in the active profile.{Colors.NC}", file=sys.stderr)
            sys.exit(1)

    # Determine the correct password to use
    auth_password = None
    if args.prompt_password:
        try:
            # getpass returns a string. If the user just hits enter, it's ""
            entered_password = getpass.getpass(f"Enter password for user '{args.user}': ")
            if entered_password:
                auth_password = entered_password
        except (EOFError, KeyboardInterrupt):
            print("\nPassword entry cancelled. Exiting.", file=sys.stderr)
            sys.exit(1)
    elif args.action == 'exec' and args.bmc:
        # If not prompting, use the default BMC password from config
        auth_password = config.get('default_bmc_password')
    else:
        # For x86 exec and all other commands, use the default x86 password
        auth_password = config.get('default_x86_password')

    # Pass the determined password to the handler functions by adding it to 'args'
    args.auth_password = auth_password
    return args, config

def main():
    """Main function to parse arguments and dispatch to handlers.""" # noqa: E501
    parser = create_parser()

    # If no arguments are provided (only the script name), print help and exit.
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    # Load config, set up clients, and determine credentials
    args, config = configure_run_from_args(args)

    # --- Pre-check if requested ---
    if args.pre_check:
        reachable_hosts = _run_pre_check(args, config)
        if not reachable_hosts:
            print(f"{Colors.YELLOW}No hosts were reachable. Aborting main operation.{Colors.NC}")
            sys.exit(0) # Exit gracefully, not an error
        args.clients = reachable_hosts # Update the client list to only the reachable ones

    # --- Dispatch to handler ---
    success_count, failure_count = args.func(args)

    # --- Print Summary ---
    if not args.json:
        print("Process complete.")
        summary = (
            f"Summary: {Colors.GREEN}{success_count} succeeded{Colors.NC}, "
            f"{Colors.RED}{failure_count} failed{Colors.NC}."
        )
        print(summary)

    if failure_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Script interrupted by user. Exiting.{Colors.NC}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}An unexpected error occurred: {e}{Colors.NC}", file=sys.stderr)
        sys.exit(1)


"""
Now you can populate config_multi_tool.json with your preferred defaults:
"""