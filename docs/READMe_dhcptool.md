# dhcptool User Manual
dhcptool is a command-line utility for managing and diagnosing the ISC DHCP server on Linux systems. It provides a user-friendly interface to view active leases, manage the DHCP service, validate configurations, and run diagnostic tests.

# 1. Prerequisites and Dependencies
Before using dhcptool, ensure your system meets the following requirements:

Operating System: A modern Linux distribution that uses systemd (e.g., Debian, Ubuntu, CentOS).
Python: Python 3.6 or newer.
Root Access: Most commands require sudo privileges to access lease files, manage services, or use raw network sockets.
ISC DHCP Server Environment: This tool is designed to manage an existing `isc-dhcp-server` installation. You must have the `isc-dhcp-server` package installed and configured on the system.
Scapy (Optional but Recommended): The test-server command requires the scapy library.
Dependency Installation
To install the scapy library on Debian-based systems (like Ubuntu), run:

```bash
sudo apt-get update
sudo apt-get install python3-scapy
```
On other systems, you might be able to use pip:

```bash
pip install scapy
```

# 2. Command Reference
The tool is invoked by running:
```bash
python3 dhcptool.py <command> [options].

list
Lists all active IPv4 and IPv6 leases from the DHCP server.

Usage:

bash
sudo python3 dhcptool.py list [filter_terms...] [options]
Options:

Option	Description
filter_terms	One or more terms to filter the list (e.g., IP, MAC, hostname).
--sort-by <col>	Sort the output by a column. (Default: hostname).Choices: hostname, ip, mac, model, serial, expires.
--reverse	Sort in descending order.
--case-sensitive	Make filtering case-sensitive.
--duplicates-only	Only show leases for MAC addresses that have been assigned multiple IPs.
--output-json <FILE>	Output the lease list to a specified JSON file.
```

Demo Commands:

 Show full code block 
# List all active leases, sorted by hostname
```bash
sudo python3 dhcptool.py list

# List leases containing "server-01", sorted by IP address
sudo python3 dhcptool.py list server-01 --sort-by ip

# List all leases and sort by expiration date in descending order
sudo python3 dhcptool.py list --sort-by expires --reverse

# find alease feature
find
Finds a single lease by a search term and displays its detailed information.

Usage:
sudo python3 dhcptool.py find <search_term>

Demo Command:

# Find the lease associated with a specific MAC address or serial number
sudo python3 dhcptool.py find 00:1a:2b:3c:4d:5e

# service
service
Manages the DHCP systemd service. Requires sudo.

Usage:

sudo python3 dhcptool.py service <action>
Actions:

Action	Description
status	Check if the service is active.
start	Start the service.
stop	Stop the service.
restart	Restart the service.
reload	Reload the configuration without stopping.


Demo Command:

# Check the status of the DHCP service
sudo python3 dhcptool.py service status

# Restart the DHCP service
sudo python3 dhcptool.py service restart
log
Displays recent log entries for the DHCP service from the system journal.

Usage:

sudo python3 dhcptool.py log [options]
Options:

Option	Description
-n, --lines	Number of log lines to show. (Default: 20)
Demo Command:

# Show the last 50 log entries for the DHCP service
sudo python3 dhcptool.py log -n 50

# check-config
check-config
Validates the syntax of the DHCP server's configuration files by running dhcpd -t.

Usage:

sudo python3 dhcptool.py check-config
test-server
config-path
Shows the paths to the DHCP server's configuration files. This is useful for quickly locating the files for manual inspection or editing.

Usage:

sudo python3 dhcptool.py config-path

# test-server
Tests the DHCP server's responsiveness by sending a DHCP DISCOVER packet and listening for an OFFER. This command requires sudo and the scapy library.

Usage:

sudo python3 dhcptool.py test-server [options]
Options:

Option	Description
--timeout	Seconds to wait for a response. (Default: 5)


Demo Command:

# Test the IPv4 DHCP server
sudo python3 dhcptool.py test-server

# summary
summary
Shows a quick overview of the number of active leases and the service status.

Usage:

sudo python3 dhcptool.py summary
```

# 3. Troubleshooting Guide
Here are solutions to common issues you might encounter.

Problem: PermissionError: [Errno 1] Operation not permitted when running test-server.

Cause: The test-server command creates raw network sockets, which requires root privileges.
Solution: Run the command with sudo.
```bash
sudo python3 dhcptool.py test-server
```
Problem: Permission denied to read lease file...

Cause: The DHCP lease file (/var/lib/dhcp/dhcpd.leases) is owned by root and not readable by other users.
Solution: Run the command with sudo.
```bash
sudo python3 dhcptool.py list
```
Problem: Warning: 'scapy' library not found.

Cause: The scapy Python library is not installed. The test-server command will not be available.
Solution: Install the library using your system's package manager. For Debian/Ubuntu:
```bash
sudo apt-get install python3-scapy
```
Problem: No active leases found, but you expect clients to be connected.

Cause: This can have several causes. The script provides helpful next steps.
Solution:
The script will automatically check the service status. If it's inactive, start it:

sudo python3 dhcptool.py service start
If the service is active, check the logs for errors:
```bash
sudo python3 dhcptool.py log
```
If the logs show no errors, test if the server is responding on the network:

```bash
sudo python3 dhcptool.py test-server
```
Problem: The script fails with an externally-managed-environment error when trying to pip install scapy.

Cause: Your Linux distribution's package manager (e.g., apt) controls system-level Python packages to ensure stability.
Solution: Use apt to install the scapy package instead of pip.

```bash
sudo apt-get install python3-scapy
```