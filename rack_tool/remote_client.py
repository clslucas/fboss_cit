#!/usr/bin/env python3

import os
import re
from datetime import datetime
import paramiko
from utils import Colors

class RemoteClient:
    """A wrapper for Paramiko to handle SSH connections and command execution, with optional logging."""
    def __init__(self, hostname, username, password=None, log_dir=None, debug=False):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.log_dir = log_dir # Store the log directory
        self.client = None
        self.debug = debug

    def connect(self):
        """Establishes an SSH connection."""
        if not self.hostname:
            print(f"{Colors.RED}Error: Hostname/IP is not set. Cannot connect.{Colors.NC}")
            return False
        try:
            if self.debug: print(f"Connecting to {self.username}@{self.hostname}...")
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.hostname,
                username=self.username,
                password=self.password,
                timeout=10,
                allow_agent=self.password is None,
                look_for_keys=self.password is None
            )
            return True
        except Exception as e:
            print(f"{Colors.RED}Failed to connect to {self.hostname}: {e}{Colors.NC}")
            self.client = None
            return False

    def connect_via_proxy(self, proxy_client):
        """
        Establishes an SSH connection through another established Paramiko client (proxy/jump host).
        """
        if not self.hostname:
            print(f"{Colors.RED}Error: Target hostname for proxy connection is not set.{Colors.NC}")
            return False
        if not proxy_client or not proxy_client.get_transport() or not proxy_client.get_transport().is_active():
            print(f"{Colors.RED}Error: Proxy client is not connected. Cannot establish a proxied connection.{Colors.NC}")
            return False

        try:
            # Get the transport from the already connected proxy client
            proxy_transport = proxy_client.get_transport()
            dest_addr = (self.hostname, 22) # Standard SSH port
            # Use an ephemeral source address
            local_addr = ('127.0.0.1', 0)
            proxy_channel = proxy_transport.open_channel("direct-tcpip", dest_addr, local_addr)

            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if self.debug: print(f"Connecting to {self.username}@{self.hostname} via proxy...")
            self.client.connect(
                hostname=self.hostname, username=self.username, password=self.password,
                allow_agent=self.password is None, look_for_keys=self.password is None, sock=proxy_channel
            )
            return True
        except Exception as e:
            print(f"{Colors.RED}Failed to connect to {self.hostname} via proxy: {e}{Colors.NC}")
            return False

    def get_client(self):
        """Returns the underlying Paramiko client object, connecting if necessary."""
        if not self.client:
            self.connect()
        return self.client

    def run_command(self, command, print_output=True, command_timeout=None):
        """
        Executes a command on the remote host, prints the output to console,
        and optionally logs it to a file.
        """
        if not self.client:
            if not self.connect():
                return "", -1 # Return empty string and error code on connection failure

        output_buffer = []
        log_file = None
        
        try:
            if self.log_dir:
                os.makedirs(self.log_dir, exist_ok=True) # Ensure log directory exists
                log_path = os.path.join(self.log_dir, f"{self.hostname}.log")
                log_file = open(log_path, 'a') # Open in append mode
                log_file.write(f"\n--- Executing Command: {command} ---\n")
                log_file.write(f"--- Timestamp: {datetime.now().isoformat()} ---\n")

            # Wrap the command in a login shell ('bash -l -c') to ensure that the
            # remote user's full PATH is loaded. This is crucial for finding
            # commands installed in locations like /usr/local/bin (e.g., rackmoncli).
            # 'set -o pipefail' ensures that if any command in a pipeline fails,
            # the entire pipeline's exit code reflects that failure. 
            # Explicitly set PATH to include /opt/py39/bin and /usr/local/bin for robustness.
            # Securely escape the command to prevent command injection.
            escaped_command = command.replace("'", "'\\''")
            wrapped_command = f"bash -l -c 'export PATH=\"/opt/py39/bin:/usr/local/bin:$PATH\"; set -o pipefail; {escaped_command}'"
            # get_pty=True allocates a pseudo-terminal, which makes the remote
            # execution environment behave like an interactive shell. This is crucial
            # for programs like rackmoncli that expect a terminal.
            stdin, stdout, stderr = self.client.exec_command(wrapped_command, get_pty=True, timeout=command_timeout)
 
            # Close stdin to signal that no input will be sent. This is crucial for
            # preventing hangs with interactive commands that wait for input.
            stdin.close()
 
            # --- Streaming for Large Outputs ---
            # This is the most robust way to read all output. The `stdout` file-like
            # object will read in chunks until the remote channel is closed, which
            # happens only after the command has finished and all output is sent.
            # This avoids complex non-blocking loops and potential race conditions.
            all_output_chunks = []
            while True:
                # Read a chunk of data from the stdout channel
                chunk = stdout.channel.recv(4096)
                if not chunk:
                    break
                
                decoded_chunk = chunk.decode('utf-8', errors='replace')
                all_output_chunks.append(decoded_chunk)
                
                # Print to console in real-time if requested.
                # Note: Coloring based on exit_status is not possible here as it's not yet known.
                if print_output:
                    print(decoded_chunk, end="")
            
            combined_output = "".join(all_output_chunks)

            # Now that all output has been read and the channel is closed,
            # it is safe to get the exit status without deadlocking.
            exit_status = stdout.channel.recv_exit_status()

            if print_output and exit_status != 0:
                print(f"\n{Colors.RED}[ FAIL ] Command failed with exit code {exit_status}.{Colors.NC}")

            if log_file:
                # Strip ANSI escape codes for logging
                clean_output = re.sub(r'\x1b\[[0-9;]*m', '', combined_output)
                log_file.write(clean_output)
                log_file.write(f"--- Command Finished ---\n")

        except Exception as e:
            exit_status = -1
            error_msg = f"{Colors.RED}An error occurred while executing command: {e}{Colors.NC}"
            print(error_msg)
            if log_file:
                log_file.write(re.sub(r'\x1b\[[0-9;]*m', '', error_msg) + "\n") # Log error without colors
        finally:
            if log_file:
                log_file.close()
        
        return combined_output, exit_status

    def upload_file(self, local_path, remote_path):
        """Uploads a local file to a remote path using SFTP."""
        if not self.client:
            if not self.connect():
                return False

        print(f"Uploading '{local_path}' to '{self.hostname}:{remote_path}'...")
        try:
            with self.client.open_sftp() as sftp:
                # Ensure remote directory exists if it's part of the path
                remote_dir = os.path.dirname(remote_path)
                if remote_dir:
                    try:
                        sftp.stat(remote_dir)
                    except FileNotFoundError:
                        print(f"Remote directory '{remote_dir}' not found, attempting to create it.")
                        sftp.mkdir(remote_dir) # This is a simple mkdir, not recursive.

                sftp.put(local_path, remote_path)
            print(f"{Colors.GREEN}Successfully uploaded file to {self.hostname}.{Colors.NC}")
            return True
        except Exception as e:
            print(f"{Colors.RED}Failed to upload file to {self.hostname}: {e}{Colors.NC}")
            return False

    def close(self):
        """Closes the SSH connection."""
        if self.client:
            self.client.close()
            self.client = None