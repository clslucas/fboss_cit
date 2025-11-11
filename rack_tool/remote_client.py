#!/usr/bin/env python3

import os
import re
from datetime import datetime
import paramiko
from utils import Colors

class RemoteClient:
    """A wrapper for Paramiko to handle SSH connections and command execution, with optional logging."""
    def __init__(self, hostname, username, password=None, log_dir=None):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.log_dir = log_dir # Store the log directory
        self.client = None

    def connect(self):
        """Establishes an SSH connection."""
        if not self.hostname:
            print(f"{Colors.RED}Error: Hostname/IP is not set. Cannot connect.{Colors.NC}")
            return False
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            print(f"Connecting to {self.username}@{self.hostname}...")
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
            print(f"Connecting to {self.username}@{self.hostname} via proxy...")
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

    def run_command(self, command, print_output=True): # Removed command_timeout as it's not used in this script
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

            stdin, stdout, stderr = self.client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status() # Block until command is done and get status
            
            # Buffer stdout
            stdout_lines = list(iter(stdout.readline, ""))
            stdout_str = "".join(stdout_lines)

            # Print to console if requested
            if print_output:
                print(stdout_str, end="")
            
            # Buffer stderr
            for line in iter(stderr.readline, ""):
                # Print stderr directly as it's captured
                print(f"{Colors.RED}{line}{Colors.NC}", end="")
                output_buffer.append(line) # Log raw stderr

            combined_output_for_log = stdout_str + "".join(output_buffer)

            if log_file:
                # Strip ANSI escape codes for logging
                clean_output = re.sub(r'\x1b\[[0-9;]*m', '', combined_output_for_log)
                log_file.write(clean_output)
                log_file.write(f"--- Command Finished ---\n")

            if exit_status != 0:
                print(f"{Colors.RED}Command failed with exit code {exit_status}.{Colors.NC}")
                if log_file:
                    log_file.write(f"--- Command failed with exit code {exit_status} ---\n")
        except Exception as e:
            exit_status = -1
            error_msg = f"{Colors.RED}An error occurred while executing command: {e}{Colors.NC}"
            print(error_msg)
            if log_file:
                log_file.write(re.sub(r'\x1b\[[0-9;]*m', '', error_msg) + "\n") # Log error without colors
        finally:
            if log_file:
                log_file.close()
        
        return stdout_str, exit_status

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