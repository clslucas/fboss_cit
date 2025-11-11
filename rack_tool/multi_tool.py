#!/usr/bin/env python3

import argparse
import getpass
import sys
import os
import concurrent.futures
import json
from contextlib import contextmanager
import time
import paramiko
from utils import Colors

# --- Default Configuration ---
CONFIG_FILE = "config_multi_tool.json"
DEFAULT_USERNAME = "root"
DEFAULT_PASSWORD = "" # Insecure, use SSH keys if possible.
MAX_WORKERS = 10
CONNECTION_RETRIES = 3
RETRY_DELAY_SECONDS = 5
DEFAULT_CLIENTS = []

class RemoteOperation:
    """Encapsulates remote operations for a single host."""
    def __init__(self, hostname, username, password):
        self.hostname = hostname
        self.username = username
        self.password = password

    @contextmanager
    def _get_connection(self):
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
                    client.connect(
                        hostname=self.hostname, username=self.username, password=self.password, timeout=10,
                        allow_agent=self.password is None, look_for_keys=self.password is None
                    )
                    yield client  # Connection successful, yield to the 'with' block
                    return      # Exit after successful operation
                except Exception as e:
                    last_exception = e
                    if attempt < CONNECTION_RETRIES - 1:
                        print(f"{Colors.YELLOW}   Connection to '{self.hostname}' failed (attempt {attempt + 1}/{CONNECTION_RETRIES}). Retrying in {RETRY_DELAY_SECONDS}s... ({e}){Colors.NC}", file=sys.stderr)
                        time.sleep(RETRY_DELAY_SECONDS)
            raise last_exception  # Re-raise the last exception after all retries fail
        finally:
            if client:
                client.close()

    def execute_command(self, command, log_dir=None, command_timeout=None):
        """
        Connects to a remote host and executes a command.
        Returns: A dictionary containing the operation result.
        """
        client = None
        stdout_buffer, stderr_buffer = [], []
        log_file = None

        try:
            with self._get_connection() as client:
                if log_dir:
                    log_path = os.path.join(log_dir, f"{self.hostname}.log")
                    log_file = open(log_path, 'w')
                    log_file.write(f"--- Command: {command} ---\n")

                stdin, stdout, stderr = client.exec_command(command, timeout=command_timeout)

                # Read from the streams while the connection is still open
                for line in iter(stdout.readline, ""):
                    stdout_buffer.append(line)
                for line in iter(stderr.readline, ""):
                    stderr_buffer.append(line)

                exit_status = stdout.channel.recv_exit_status()
            
            return {
                "hostname": self.hostname,
                "success": exit_status == 0,
                "exit_code": exit_status,
                "stdout": "".join(stdout_buffer),
                "stderr": "".join(stderr_buffer),
            }

        except paramiko.AuthenticationException as e:
            return {"hostname": self.hostname, "success": False, "exit_code": -1, "stdout": "", "stderr": f"FAILURE: Authentication failed on '{self.hostname}': {e}"}
        except Exception as e:
            return {
                "hostname": self.hostname, "success": False, "exit_code": -1,
                "stdout": "", "stderr": f"FAILURE: Could not connect or execute on '{self.hostname}': {e}"
            }
        finally:
            # The 'finally' block for closing the client is now inside the context manager.
            # This block is just for closing the log file.
            if log_file:
                log_file.writelines(stdout_buffer + stderr_buffer)
                log_file.close()

    def transfer_file(self, local_path, remote_path):
        """
        Connects to a remote host and transfers a file using SCP.
        Returns: A dictionary containing the operation result.
        """
        client = None
        try:
            with self._get_connection() as client:
                with client.open_sftp() as sftp:
                    remote_file_path = os.path.join(remote_path, os.path.basename(local_path))
                    sftp.put(local_path, remote_file_path)

            return {
                "hostname": self.hostname, "success": True,
                "message": f"File transferred to '{self.hostname}'."
            }
        except Exception as e:
            return {
                "hostname": self.hostname, "success": False,
                "message": f"Could not transfer to '{self.hostname}': {e}"
            }

    def download_file(self, remote_path, local_dir):
        """
        Connects to a remote host and downloads a file using SFTP.
        Returns: A dictionary containing the operation result.
        """
        client = None
        try:
            with self._get_connection() as client:
                # Construct a unique local path to avoid overwriting files from different hosts
                local_filename = f"{self.hostname}_{os.path.basename(remote_path)}"
                local_file_path = os.path.join(local_dir, local_filename)

                with client.open_sftp() as sftp:
                    sftp.get(remote_path, local_file_path)

            return {"hostname": self.hostname, "success": True, "message": f"File downloaded from '{self.hostname}' to '{local_file_path}'."}
        except Exception as e:
            return {"hostname": self.hostname, "success": False, "message": f"Could not download from '{self.hostname}': {e}"}

    def upload_and_execute(self, local_path, remote_dir, script_args, command_timeout=None):
        """
        Uploads a script, makes it executable, and then runs it on the remote host.
        """
        stdout_buffer, stderr_buffer = [], []
        try:
            with self._get_connection() as client:
                # --- Part 1: Upload the file ---
                with client.open_sftp() as sftp:
                    remote_script_name = os.path.basename(local_path)
                    # Ensure remote_dir is treated as a directory
                    if not remote_dir.endswith('/'):
                        remote_dir += '/'
                    remote_script_path = f"{remote_dir}{remote_script_name}"
                    sftp.put(local_path, remote_script_path)

                # --- Part 2: Execute the script ---
                command = f"chmod +x {remote_script_path} && {remote_script_path} {script_args}"
                stdin, stdout, stderr = client.exec_command(command, timeout=command_timeout)

                for line in iter(stdout.readline, ""):
                    stdout_buffer.append(line)
                for line in iter(stderr.readline, ""):
                    stderr_buffer.append(line)

                exit_status = stdout.channel.recv_exit_status()

            return {
                "hostname": self.hostname,
                "success": exit_status == 0,
                "exit_code": exit_status,
                "stdout": "".join(stdout_buffer),
                "stderr": "".join(stderr_buffer),
            }
        except paramiko.AuthenticationException as e:
            return {"hostname": self.hostname, "success": False, "exit_code": -1, "stdout": "", "stderr": f"FAILURE: Authentication failed on '{self.hostname}': {e}"}
        except Exception as e:
            return {
                "hostname": self.hostname, "success": False, "exit_code": -1,
                "stdout": "".join(stdout_buffer), "stderr": f"FAILURE: Could not upload or execute on '{self.hostname}': {e}"
            }


def handle_exec(args):
    """Orchestrates remote command execution."""
    if not args.json:
        print(f"{Colors.BLUE}Executing command: {Colors.YELLOW}{args.command}{Colors.NC}")
        print("=======================================")

    if args.log_dir:
        try:
            os.makedirs(args.log_dir, exist_ok=True)
            if not args.json:
                print(f"{Colors.BLUE}Logging output to directory: {args.log_dir}{Colors.NC}")
        except OSError as e:
            print(f"{Colors.RED}Error creating log directory '{args.log_dir}': {e}{Colors.NC}", file=sys.stderr)
            args.log_dir = None

    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_client = {}
        for client_ip in args.clients:
            op = RemoteOperation(client_ip, args.user, args.auth_password)
            future = executor.submit(op.execute_command, args.command, args.log_dir, args.timeout)
            future_to_client[future] = client_ip

        completed_futures = concurrent.futures.as_completed(future_to_client)
        for future in completed_futures:
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                client = future_to_client[future]
                results.append({
                    "hostname": client, "success": False,
                    "exit_code": -1, "stdout": "",
                    "stderr": f"EXCEPTION: An error occurred while processing host '{client}': {exc}"
                })

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for res in sorted(results, key=lambda x: x['hostname']):
            print(f"-> Results for {Colors.YELLOW}{args.user}@{res['hostname']}{Colors.NC}:")
            if res['stdout']:
                print(res['stdout'], end="")
            if res['stderr']:
                print(f"{Colors.RED}{res['stderr']}{Colors.NC}", end="")
            
            print("----------------------------------------")
            if res['success']:
                print(f"{Colors.GREEN}   SUCCESS: Command executed on '{res['hostname']}'.{Colors.NC}")
            else:
                if res['exit_code'] != -1:
                    print(f"{Colors.RED}   FAILURE: Command failed on '{res['hostname']}' with exit code {res['exit_code']}.{Colors.NC}")
                else: # Exception case
                    # The error is already in stderr, so just a simple failure message
                    print(f"{Colors.RED}   FAILURE: Could not execute on '{res['hostname']}'.{Colors.NC}")
            print("----------------------------------------")

    return sum(1 for r in results if r['success']), sum(1 for r in results if not r['success'])

def handle_scp(args):
    """Orchestrates remote file transfer."""
    if not os.path.isfile(args.local_file):
        print(f"{Colors.RED}Error: Local file '{args.local_file}' not found.{Colors.NC}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"{Colors.BLUE}Starting file transfer of '{args.local_file}' to {len(args.clients)} host(s)...{Colors.NC}")
        print("=======================================")

    success_count = 0
    failure_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_client = {}
        for client_ip in args.clients:
            op = RemoteOperation(client_ip, args.user, args.auth_password)
            future = executor.submit(op.transfer_file, args.local_file, args.remote_path)
            future_to_client[future] = client_ip

        results = []
        completed_futures = concurrent.futures.as_completed(future_to_client)
        for future in completed_futures:
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                client = future_to_client[future]
                results.append({
                    "hostname": client, "success": False, "message":
                    f"EXCEPTION: An error occurred while processing host '{client}': {exc}"
                })

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for res in sorted(results, key=lambda x: x['hostname']):
            print(f"-> Results for {Colors.YELLOW}{args.user}@{res['hostname']}{Colors.NC}:")
            print("----------------------------------------")
            color = Colors.GREEN if res['success'] else Colors.RED
            status = "SUCCESS" if res['success'] else "FAILURE"
            print(f"{color}   {status}: {res['message']}{Colors.NC}")
            print("----------------------------------------")

    return sum(1 for r in results if r['success']), sum(1 for r in results if not r['success'])

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

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_client = {}
        for client_ip in args.clients:
            op = RemoteOperation(client_ip, args.user, args.auth_password)
            future = executor.submit(op.download_file, args.remote_file, args.local_dir)
            future_to_client[future] = client_ip

        results = []
        completed_futures = concurrent.futures.as_completed(future_to_client)
        for future in completed_futures:
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                client = future_to_client[future]
                results.append({
                    "hostname": client, "success": False, "message":
                    f"EXCEPTION: An error occurred while processing host '{client}': {exc}"
                })

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for res in sorted(results, key=lambda x: x['hostname']):
            print(f"-> Results for {Colors.YELLOW}{args.user}@{res['hostname']}{Colors.NC}:")
            print("----------------------------------------")
            color = Colors.GREEN if res['success'] else Colors.RED
            status = "SUCCESS" if res['success'] else "FAILURE"
            print(f"{color}   {status}: {res['message']}{Colors.NC}")
            print("----------------------------------------")

    return sum(1 for r in results if r['success']), sum(1 for r in results if not r['success'])

def handle_upload_exec(args):
    """Orchestrates script upload and execution."""
    if not os.path.isfile(args.local_file):
        print(f"{Colors.RED}Error: Local file '{args.local_file}' not found.{Colors.NC}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"{Colors.BLUE}Uploading and executing '{os.path.basename(args.local_file)}' on {len(args.clients)} host(s)...{Colors.NC}")
        print("=======================================")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_client = {}
        for client_ip in args.clients:
            op = RemoteOperation(client_ip, args.user, args.auth_password)
            future = executor.submit(op.upload_and_execute, args.local_file, args.remote_path, args.script_args, args.timeout)
            future_to_client[future] = client_ip

        completed_futures = concurrent.futures.as_completed(future_to_client)
        for future in completed_futures:
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                client = future_to_client[future]
                results.append({
                    "hostname": client, "success": False,
                    "exit_code": -1, "stdout": "",
                    "stderr": f"EXCEPTION: An error occurred while processing host '{client}': {exc}"
                })

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for res in sorted(results, key=lambda x: x['hostname']):
            print(f"-> Results for {Colors.YELLOW}{args.user}@{res['hostname']}{Colors.NC}:")
            if res['stdout']:
                print(res['stdout'], end="")
            if res['stderr']:
                print(f"{Colors.RED}{res['stderr']}{Colors.NC}", end="")
            
            print("----------------------------------------")
            if res['success']:
                print(f"{Colors.GREEN}   SUCCESS: Script executed on '{res['hostname']}'.{Colors.NC}")
            else:
                if res['exit_code'] != -1:
                    print(f"{Colors.RED}   FAILURE: Script failed on '{res['hostname']}' with exit code {res['exit_code']}.{Colors.NC}")
            print("----------------------------------------")

    return sum(1 for r in results if r['success']), sum(1 for r in results if not r['success'])

def load_configuration(config_path):
    """Loads configuration from the specified JSON file, returning a dictionary."""
    if not os.path.exists(config_path):
        # If the user specified a file that doesn't exist, it's an error.
        # If it's the default file, it's just a warning.
        if config_path != CONFIG_FILE:
            print(f"{Colors.RED}Error: Configuration file '{config_path}' not found.{Colors.NC}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"{Colors.YELLOW}Warning: Default config '{config_path}' not found. Using hardcoded defaults.{Colors.NC}")
            return {}
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"{Colors.RED}Error reading '{config_path}': {e}. Using hardcoded defaults.{Colors.NC}")
        return {}

def main():
    """Main function to parse arguments and dispatch to handlers."""
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
    parent_parser.add_argument("clients", nargs='*', help="Space-separated list of client IPs. If omitted, uses the hardcoded default list.")
    parent_parser.add_argument("--config", default=CONFIG_FILE, help=f"Path to a custom JSON configuration file. (Default: '{CONFIG_FILE}')")
    parent_parser.add_argument("-u", "--user", default=DEFAULT_USERNAME, help=f"Remote username. (Default: '{DEFAULT_USERNAME}')")
    parent_parser.add_argument("-p", "--prompt-password", action="store_true", help="Prompt for a password. Overrides SSH keys or the hardcoded default.")
    parent_parser.add_argument("--json", action="store_true", help="Output results in JSON format.")

    # --- 'exec' sub-command ---
    parser_exec = subparsers.add_parser("exec", parents=[parent_parser], help="Execute a command on remote hosts.", epilog="""
Examples:
  # Run 'uptime' on hosts from the default list
  %(prog)s "uptime"

  # Run 'ls' on specific hosts and get JSON output
  %(prog)s "ls -l /tmp" 192.168.1.100 192.168.1.101 --json

  # Run a command and save logs for each host
  %(prog)s "cat /var/log/syslog" --log-dir /tmp/logs
""")
    parser_exec.add_argument("command", help="The command to execute (in quotes).")
    parser_exec.add_argument("--log-dir", help="Directory to save command output logs.", metavar="PATH")
    parser_exec.add_argument("--timeout", type=int, help="Timeout in seconds for the remote command.", metavar="SECONDS")
    parser_exec.set_defaults(func=handle_exec)

    # --- 'scp' sub-command ---
    parser_scp = subparsers.add_parser("scp", parents=[parent_parser], help="Upload a file to remote hosts.", epilog="""
Examples:
  # Upload a script to /tmp on hosts from the default list
  %(prog)s my_script.sh /tmp/

  # Upload a file to a specific host, prompting for a password
  %(prog)s ./config.yaml /home/user/ -p 10.0.0.5
""")
    parser_scp.add_argument("local_file", help="The local file to transfer.")
    parser_scp.add_argument("remote_path", help="The destination directory on remote hosts.")
    parser_scp.set_defaults(func=handle_scp)

    # --- 'download' sub-command ---
    parser_download = subparsers.add_parser("download", parents=[parent_parser], help="Download a file from remote hosts.", epilog="""
Examples:
  # Download a log file from all default hosts into the './downloads' directory
  %(prog)s /var/log/syslog ./downloads

  # Download a config file from a specific host
  %(prog)s /etc/app/config.json . 192.168.1.100
""")
    parser_download.add_argument("remote_file", help="The full path of the file to download from remote hosts.")
    parser_download.add_argument("local_dir", help="The local directory to save downloaded files into.")
    parser_download.set_defaults(func=handle_download)

    # --- 'upload-exec' sub-command ---
    parser_upload_exec = subparsers.add_parser("upload-exec", parents=[parent_parser], help="Upload a script and execute it.", epilog="""
Examples:
  # Upload 'check.sh' to /tmp and run it on all default hosts
  %(prog)s ./check.sh /tmp

  # Upload a script and run it with arguments
  %(prog)s ./setup.sh /opt/ --args "--force --verbose"
""")
    parser_upload_exec.add_argument("local_file", help="The local script to upload and execute.")
    parser_upload_exec.add_argument("remote_path", help="The destination directory on remote hosts.")
    parser_upload_exec.add_argument("--args", dest="script_args", default="", help="A string of arguments to pass to the remote script (in quotes).")
    parser_upload_exec.add_argument("--timeout", type=int, help="Timeout in seconds for the remote script execution.", metavar="SECONDS")
    parser_upload_exec.set_defaults(func=handle_upload_exec)

    args = parser.parse_args()

    # --- Load Configuration & Set Defaults ---
    config = load_configuration(args.config)
    # Use loaded config to supplement args, but don't modify globals
    # This avoids the SyntaxError by not re-assigning to global variables
    # that were read during parser setup.
    effective_default_clients = config.get("default_clients", DEFAULT_CLIENTS)
    effective_default_password = config.get("default_password", DEFAULT_PASSWORD)
    # The username default is already handled by argparse, so we don't need to touch it here.

    # --- Argument Handling ---
    if not args.clients:
        if effective_default_clients:
            args.clients = effective_default_clients
            if not args.json:
                print(f"{Colors.BLUE}Using default client list from '{args.config}'.{Colors.NC}")
        else:
            print(f"{Colors.RED}Error: No clients specified and no default client list is configured.{Colors.NC}", file=sys.stderr)
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
    elif effective_default_password:  # Use default from config/script only if it's not empty
        auth_password = effective_default_password

    # Pass the determined password to the handler functions by adding it to 'args'
    args.auth_password = auth_password

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