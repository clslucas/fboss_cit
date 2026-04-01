# Comprehensive PXE Boot Guide for CentOS Stream 9 Installation

## Document Information
- **Document Version**: 4.0 (Combined Edition)
- **Applicable Environment**: Test/Production Environment
- **Server Operating Systems**: Ubuntu Server (20.04/22.04) or CentOS Stream 9
- **Client Operating System**: CentOS Stream 9

## Introduction
This guide provides a comprehensive, step-by-step walkthrough for setting up a Preboot Execution Environment (PXE) server to automate the installation of CentOS Stream 9. It covers two popular Linux distributions for the server role: Ubuntu Server and CentOS Stream 9.

The setup includes:
- DHCP (IPv4 & IPv6) for network configuration.
- TFTP for delivering bootloaders.
- HTTP for serving the OS installation files and Kickstart configuration.
- A Kickstart file for fully automated, unattended installations.
- An optional but highly recommended API for on-demand control of PXE booting, preventing accidental reinstalls.

Please follow the sections relevant to your chosen server operating system.

## Table of Contents
- Environment Overview
- Part 1: PXE Server Setup
  - Section A: Using Ubuntu as the PXE Server
  - Section B: Using CentOS Stream 9 as the PXE Server
- Part 2: Common Configuration (For Both Server Types)
  - Section 2.1: Prepare Installation Media and Boot Files
  - Section 2.2: Configure PXE Boot Menus
  - Section 2.3: Configure the Kickstart File
  - Section 2.4: Set up the PXE Boot Control API
  - Section 2.5: Create the Client Management Tool
- Part 3: Service Activation and Usage
  - Section 3.1: Start and Enable Services
  - Section 3.2: Using the PXE System
- Troubleshooting

## Environment Overview

### Server and Client Roles
| Role        | Operating System        | IP Address (Example)                  | Services Hosted                               |
|-------------|-------------------------|---------------------------------------|-----------------------------------------------|
| PXE Server  | Ubuntu or CentOS Stream 9 | 192.168.1.2 / fd00\:1234:5678:1::10    | DHCP, TFTP, HTTP, Control API                 |
| PXE Client  | CentOS Stream 9         | Assigned by DHCP                      | Boots from network to install OS              |

### Common Network Configuration
- **IPv4 Network**: 192.168.1.0/24
- **IPv4 Gateway**: 192.168.1.1
- **IPv4 DHCP Range**: 192.168.1.100 - .200
- **IPv6 Network**: fd00\:1234:5678:1::/64
- **IPv6 DHCP Range**: ::100 - ::200
- **DNS**: 8.8.8.8, 8.8.4.4, 2001:4860:4860::8888

---

## Part 1: PXE Server Setup

Choose the section that matches your server's operating system.

### Section A: Using Ubuntu as the PXE Server

These instructions are for setting up the necessary services on an Ubuntu Server.

#### 1. Install Necessary Packages

```bash
sudo apt update
sudo apt install -y isc-dhcp-server tftpd-hpa apache2 syslinux-common pxelinux wget createrepo-c python3-flask gunicorn
```

#### 2. Configure Static Network Interface

Configure a static IP for your server using Netplan. Your interface name (e.g., `eno3`) may differ.

```bash
# Edit the Netplan configuration file (filename may vary)
sudo nano /etc/netplan/00-installer-config.yaml
```

Update the file with the following content:
```yaml
network:
  version: 2
  ethernets:
    eno3: # <-- Change this to your interface name
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.1.2/24
        - fd00:1234:5678:1::10/64
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
         addresses: [8.8.8.8, 8.8.4.4, "2001:4860:4860::8888"]
```

Apply the network configuration:
```bash
sudo netplan apply
```

#### 3. Configure DHCP Server

First, tell the DHCP server which interfaces to listen on.

```bash
# Edit the default configuration
sudo nano /etc/default/isc-dhcp-server
```

Set the `INTERFACESv4` and `INTERFACESv6` variables:
```ini
INTERFACESv4="eno3" # <-- Change this to your interface name
INTERFACESv6="eno3" # <-- Change this to your interface name
```

Now, configure the IPv4 and IPv6 scopes.

**IPv4 Configuration (`/etc/dhcp/dhcpd.conf`)**
```bash
sudo nano /etc/dhcp/dhcpd.conf
```
Add the following content. This file will serve both BIOS and UEFI clients by detecting their architecture.
```ini
option domain-name "pxe.lab";
option domain-name-servers 8.8.8.8, 8.8.4.4;
default-lease-time 600;
max-lease-time 7200;
authoritative;

subnet 192.168.1.0 netmask 255.255.255.0 {
    range 192.168.1.100 192.168.1.200;
    option routers 192.168.1.1;
    option subnet-mask 255.255.255.0;
    next-server 192.168.1.2;
}
```

**IPv6 Configuration (`/etc/dhcp/dhcpd6.conf`)**
This configuration uses a control file (`dhcpd6-clients.conf`) managed by our API to only allow PXE booting for authorized clients.

```bash
sudo nano /etc/dhcp/dhcpd6.conf
```
```ini
default-lease-time 600;
max-lease-time 7200;
authoritative;

# Deny unknown clients for security
deny unknown-clients;

option dhcp6.name-servers 2001:4860:4860::8888, 2001:4860:4860::8844;

subnet6 fd00:1234:5678:1::/64 {
    pool6 {
        range6 fd00:1234:5678:1::100 fd00:1234:5678:1::200;
        allow known-clients;
    }
    option dhcp6.bootfile-url "tftp://[fd00:1234:5678:1::10]/grubx64.efi";
}

# Include the file that will be dynamically managed by the API
include "/etc/dhcp/dhcpd6-clients.conf";
```

Create the managed include file:
```bash
sudo touch /etc/dhcp/dhcpd6-clients.conf
```

#### 4. Configure TFTP Server

```bash
sudo nano /etc/default/tftpd-hpa
```
Update the configuration to enable the service:
```ini
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/var/lib/tftpboot"
TFTP_ADDRESS=":69"
TFTP_OPTIONS="--secure --create"
```

#### 5. Configure Firewall

Open the necessary ports using `ufw`.
```bash
sudo ufw allow 67/udp     # DHCPv4
sudo ufw allow 547/udp    # DHCPv6
sudo ufw allow 69/udp     # TFTP
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 5001/tcp   # PXE Control API
sudo ufw enable
```

### Section B: Using CentOS Stream 9 as the PXE Server

These instructions are for setting up the necessary services on a CentOS Stream 9 server.

#### 1. Install Necessary Packages

```bash
sudo dnf update -y
sudo dnf install -y dhcp-server tftp-server httpd syslinux syslinux-tftpboot wget createrepo_c python3-flask python3-gunicorn
```

#### 2. Configure Static Network Interface

Configure a static IP for your server using `nmcli`. Your interface name (e.g., `eno3`) may differ.

```bash
# Configure IPv4
sudo nmcli con modify eno3 ipv4.addresses 192.168.1.2/24 ipv4.gateway 192.168.1.1 ipv4.method manual
sudo nmcli con modify eno3 ipv4.dns "8.8.8.8 8.8.4.4"

# Configure IPv6
sudo nmcli con modify eno3 ipv6.addresses fd00:1234:5678:1::10/64 ipv6.method manual
sudo nmcli con modify eno3 ipv6.dns "2001:4860:4860::8888"

# Apply changes
sudo nmcli con up eno3
```

#### 3. Configure DHCP Server

The configuration files for the ISC DHCP server on CentOS are the same as on Ubuntu.

**IPv4 Configuration (`/etc/dhcp/dhcpd.conf`)**
```bash
sudo nano /etc/dhcp/dhcpd.conf
```
Add the following content. This file will serve both BIOS and UEFI clients by detecting their architecture.
```ini
option domain-name "pxe.lab";
option domain-name-servers 8.8.8.8, 8.8.4.4;
default-lease-time 600;
max-lease-time 7200;
authoritative;

subnet 192.168.1.0 netmask 255.255.255.0 {
    range 192.168.1.100 192.168.1.200;
    option routers 192.168.1.1;
    option subnet-mask 255.255.255.0;
    next-server 192.168.1.2;
}
```

**IPv6 Configuration (`/etc/dhcp/dhcpd6.conf`)**
This configuration uses a control file (`dhcpd6-clients.conf`) managed by our API to only allow PXE booting for authorized clients.

```bash
sudo nano /etc/dhcp/dhcpd6.conf
```
```ini
default-lease-time 600;
max-lease-time 7200;
authoritative;

# Deny unknown clients for security
deny unknown-clients;

option dhcp6.name-servers 2001:4860:4860::8888, 2001:4860:4860::8844;

subnet6 fd00:1234:5678:1::/64 {
    pool6 {
        range6 fd00:1234:5678:1::100 fd00:1234:5678:1::200;
        allow known-clients;
    }
    option dhcp6.bootfile-url "tftp://[fd00:1234:5678:1::10]/grubx64.efi";
}

# Include the file that will be dynamically managed by the API
include "/etc/dhcp/dhcpd6-clients.conf";
```

Create the managed include file and set correct ownership for the `dhcpd` user.
```bash
sudo touch /etc/dhcp/dhcpd6-clients.conf
sudo chown dhcpd:dhcpd /etc/dhcp/dhcpd6-clients.conf
```

#### 4. Configure SELinux

SELinux is enforced by default. You must set the correct security contexts for the TFTP and HTTP directories.
```bash
sudo restorecon -Rv /var/lib/tftpboot/
sudo restorecon -Rv /var/www/html/
```

#### 5. Configure Firewall

Open the necessary ports using `firewalld`.
```bash
sudo firewall-cmd --permanent --add-service=dhcp
sudo firewall-cmd --permanent --add-service=dhcpv6
sudo firewall-cmd --permanent --add-service=tftp
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-port=5001/tcp  # PXE Control API
sudo firewall-cmd --reload
```

---

## Part 2: Common Configuration (For Both Server Types)

The following steps are required for both Ubuntu and CentOS PXE servers.

### Section 2.1: Prepare Installation Media and Boot Files

#### 1. Create Directories

```bash
# For TFTP
sudo mkdir -p /var/lib/tftpboot/images/centos9

# For HTTP
sudo mkdir -p /var/www/html/ks
sudo mkdir -p /var/www/html/centos/9-stream/install
```

#### 2. Download and Mount CentOS 9 ISO

```bash
# Download the ISO to a temporary location
sudo mkdir -p /opt/iso
cd /opt/iso
sudo wget https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/iso/CentOS-Stream-9-latest-x86_64-dvd1.iso -O centos9-dvd.iso

# Mount the ISO to the HTTP directory
sudo mount -o loop /opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install

# Make the mount persistent across reboots
echo "/opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install iso9660 loop 0 0" | sudo tee -a /etc/fstab
```

#### 3. Copy Boot Files

```bash
# Copy Kernel and Initrd from the mounted ISO
sudo cp /var/www/html/centos/9-stream/install/images/pxeboot/{vmlinuz,initrd.img} /var/lib/tftpboot/images/centos9/

# Copy UEFI boot file (GRUB) from the mounted ISO
sudo cp /var/www/html/centos/9-stream/install/EFI/BOOT/grubx64.efi /var/lib/tftpboot/
```

### Section 2.2: Configure PXE Boot Menus

#### UEFI Boot Menu (`/var/lib/tftpboot/grub.cfg`)

The GRUB2 configuration file `/var/lib/tftpboot/grub.cfg` serves as the boot menu for all UEFI clients.
```bash
sudo nano /var/lib/tftpboot/grub.cfg
```
```grub
set timeout=10

menuentry 'Automated CentOS Stream 9 Installation (UEFI)' {
    linuxefi images/centos9/vmlinuz ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text inst.ks=http://192.168.1.2/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 inst.cmdline console=ttyS0,57600n8
    initrdefi images/centos9/initrd.img
}

menuentry 'Boot from Local Drive' {
    exit
}
```

### Section 2.3: Configure the Kickstart File

The Kickstart file contains all the instructions for an unattended installation. This file is compatible with CentOS Stream 9.

Create the file `/var/www/html/ks/centos9-ks.cfg`:
```bash
sudo nano /var/www/html/ks/centos9-ks.cfg
```

Paste the following content:
```kickstart
#
# --- CentOS Stream 9 Automated Kickstart File (Self-Contained) ---
# This version is designed to be a single, robust file without relying on
# external snippets fetched via HTTP during installation.
#

lang en_US.UTF-8
keyboard us
timezone Asia/Shanghai --utc
 
# WARNING: Using a plaintext password is not recommended for production environments.
rootpw --plaintext 11
 
# Create user accounts. The /apphome directory will be created by the partitioning logic.
# Create the 'test' user and add them to the 'wheel' group for sudo privileges.
user --name=test --password=11 --plaintext --groups=wheel
 
# Use the modern authselect command instead of the deprecated auth/authconfig.
authselect select minimal with-mkhomedir --force
 
text
firstboot --disabled
 
# The installation source is defined by the 'inst.repo' kernel parameter in the PXE/GRUB menu.
# We explicitly define the repos here to ensure AppStream is used for packages like "Development Tools".
repo --name="BaseOS" --baseurl=http://192.168.1.2/centos/9-stream/install/BaseOS/
repo --name="AppStream" --baseurl=http://192.168.1.2/centos/9-stream/install/AppStream/
%include /tmp/repo-include

services --enabled="sshd,chronyd,NetworkManager"
 
network --bootproto=dhcp --device=link --onboot=on --ipv6=auto
firewall --enabled --service=ssh --service=dhcpv6-client
selinux --enforcing
reboot --eject

# Include the partitioning configuration generated by the %pre script.
%include /tmp/partitioning.ks
 
%packages
# Use the "Server" environment as a base instead of "Minimal Install".
@server
# Add essential tools that are useful for any server role.
vim-enhanced
wget
curl
git
bash-completion
policycoreutils-python-utils
# Needed for creating temporary repos in the %post script
createrepo_c
# Keep lldpad for Link Layer Discovery Protocol support.
lldpad
# The full "Development Tools" group is large. Install a smaller, more targeted set.
@development
# Add additional software groups based on the provided selection.
@debugging
@ftp-server # Corrected from @ftp
@hardware-support
@infiniband
@network-file-system-client # Corrected from @nfs-client
@network-server # Corrected from @network-server-environment
@performance
@remote-desktop-clients # Corrected from @remote-management
@virtualization-hypervisor
@web-server
# @legacy-unix-compatibility # Temporarily disabled due to repo metadata issues.
@console-internet
@container-management
@dotnet
@headless-management
@rpm-development-tools
@scientific
@security-tools
@system-tools
%end
 
%pre
#!/bin/bash
# This script runs in the installer environment before partitioning.

# --- Find PXE Server IP from Kernel Arguments ---
REPO_URL=$(grep -o 'inst.repo=[^ ]*' /proc/cmdline | cut -d'=' -f2)
SERVER_IP=$(echo "$REPO_URL" | awk -F/ '{print $3}' | sed -e 's/\[//' -e 's/\]//')
HTTP_BASE="http://${SERVER_IP}"
 
# --- Detect Server Role from Kernel Arguments ---
# (This is kept for future flexibility, even if not currently used)
ROLE=$(grep -o 'inst.ks.role=[^ ]*' /proc/cmdline | cut -d'=' -f2)
if [ -z "$ROLE" ]; then
    ROLE="generic"
fi

echo "Detected ROLE: ${ROLE}" > /dev/tty1

# --- Generate Repository Configuration ---
# The installer automatically uses BaseOS and AppStream from the 'inst.repo' boot parameter.
# We ONLY need to add our custom repositories here.
cat > /tmp/repo-include <<EOF
repo --name="custom" --baseurl=${HTTP_BASE}/centos/9-stream/custom/x86_64/
EOF
# --- Generate Dynamic Partitioning and Bootloader Scheme ---

# --- Dynamically Detect First Disk ---
# Find the first block device of type 'disk', excluding non-installable devices like zram.
FIRST_DISK=$(lsblk -d -n -o NAME,TYPE | grep -E 'disk' | grep -v 'zram' | head -n 1 | awk '{print $1}')

# Start with clearing all partitions. The bootloader location will be set dynamically.
cat > /tmp/partitioning.ks <<PART_EOF
clearpart --all --initlabel
# Use the dynamically detected disk to prevent interactive prompts.
ignoredisk --only-use=${FIRST_DISK}
PART_EOF

if [ -d /sys/firmware/efi ]; then
    # UEFI system detected
    # Add the EFI boot partition and specify the bootloader location.
    # For UEFI, the bootloader is handled automatically by the presence of /boot/efi.
    echo "bootloader --boot-drive=${FIRST_DISK}" >> /tmp/partitioning.ks
    echo "part /boot/efi --fstype=\"efi\" --size=200 --ondisk=${FIRST_DISK}" >> /tmp/partitioning.ks
 else
    # BIOS system detected
    # For BIOS, explicitly set the bootloader location to the MBR.
    echo "bootloader --location=mbr --boot-drive=${FIRST_DISK}" >> /tmp/partitioning.ks
fi

# Base partitioning scheme for all roles
cat >> /tmp/partitioning.ks <<PART_EOF
# Partitioning for role: ${ROLE}

part /boot --fstype="xfs" --size=1024 --ondisk=${FIRST_DISK}
part pv.01 --size=1 --grow --ondisk=${FIRST_DISK}
volgroup vg_main pv.01
PART_EOF
 
# Generic/Default Server Partitioning
cat >> /tmp/partitioning.ks <<PART_EOF
logvol swap --vgname=vg_main --size=4096 --name=lv_swap
logvol / --vgname=vg_main --size=20480 --name=lv_root --fstype="xfs" --label=root
logvol /apphome --vgname=vg_main --size=5120 --name=lv_apphome --fstype="xfs"
logvol /home --vgname=vg_main --size=10240 --grow --name=lv_home --fstype="xfs"
%end
 
%post --log=/root/ks-post.log
#!/bin/bash
# This script runs in the chroot of the newly installed system before reboot.

# ==============================================================================
# ROBUST LOGGING AND ERROR HANDLING
# ==============================================================================
# Redirect all stdout and stderr to a dedicated log file on the new system.
exec > /root/ks-post-script.log 2>&1

# Enable command tracing. Every command will be printed to the log before it's executed.
set -x
# ==============================================================================

# --- Dynamic Variable Setup ---
REPO_URL=$(grep -o 'inst.repo=[^ ]*' /proc/cmdline | cut -d'=' -f2)
SERVER_IP=$(echo "$REPO_URL" | awk -F/ '{print $3}' | sed -e 's/\[//' -e 's/\]//')
ROLE=$(grep -o 'inst.ks.role=[^ ]*' /proc/cmdline | cut -d'=' -f2)
[ -z "$ROLE" ] && ROLE="generic"
CUSTOM_FILES_URL="http://${SERVER_IP}/custom-files"

echo "--- KICKSTART POST-INSTALL SCRIPT ---"
echo "Detected Server IP: ${SERVER_IP}"
echo "Detected Server Role: ${ROLE}"
echo "Custom files URL: ${CUSTOM_FILES_URL}"

### --- General System Configuration ---

echo "--- Allowing root SSH login with password ---"
# WARNING: This is not recommended for production environments.
# The previous sed command was not reliably uncommenting and setting the value.
# Using a two-step approach to ensure the setting is applied correctly.
# First, uncomment the line if it's commented.
/usr/bin/sed -i '/^#PermitRootLogin/s/^#//' /etc/ssh/sshd_config
# Then, ensure the value is 'yes'.
/usr/bin/sed -i 's/^PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
echo "--- Configuring SSH keys for users ---"
# Root
/usr/bin/install -d -m 700 -o root -g root /root/.ssh
/usr/bin/curl -s -o /root/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_root"
/usr/bin/chmod 600 /root/.ssh/authorized_keys
/usr/bin/chown root:root /root/.ssh/authorized_keys
# Test
/usr/bin/install -d -m 700 -o test -g test /home/test/.ssh
/usr/bin/curl -s -o /home/test/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_test" && \
    /usr/bin/chmod 600 /home/test/.ssh/authorized_keys && /usr/bin/chown test:test /home/test/.ssh/authorized_keys

echo "Setting system hostname..."
IP_ADDR=$(/usr/bin/hostname -I | /usr/bin/awk '{print $1}' | /usr/bin/tr '.' '-')
/usr/bin/hostnamectl set-hostname "host-${IP_ADDR}"

echo "Enabling LLDP service..."
systemctl enable lldpad

echo "No specific role configuration needed."

### --- PXE Control Functionality ---

echo "--- Creating /usr/local/sbin/pxe-reinstall utility ---"
/usr/bin/cat > /usr/local/sbin/pxe-reinstall <<REINSTALL_SCRIPT
#!/bin/bash
PXE_SERVER_IP="${SERVER_IP}"
API_PORT="5001"

if [ -z "\$PXE_SERVER_IP" ]; then
    echo "Error: Could not determine PXE Server IP. Cannot run script."
    exit 1
fi

PRIMARY_IP=\$(/usr/bin/hostname -I | /usr/bin/awk '{print \$1}')
INTERFACE_NAME=\$(/usr/sbin/ip -o addr show | /usr/bin/grep "inet \$PRIMARY_IP" | /usr/bin/awk '{print \$2}')
MAC_ADDR=\$(/usr/bin/cat /sys/class/net/\$INTERFACE_NAME/address)

if [ -z "\$MAC_ADDR" ]; then
    echo "Error: Could not determine an active MAC address."
    exit 1
fi

echo "This script will configure the server to boot from PXE on the next reboot."
echo "Server MAC Address: \$MAC_ADDR"
read -p "Are you sure you want to continue? (y/n) " -n 1 -r
echo
if [[ ! \$REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo "Enabling PXE boot for the next reboot..."
/usr/bin/curl -s -X PUT "http://\${PXE_SERVER_IP}:\${API_PORT}/clients/\${MAC_ADDR}/pxe"
echo "Done. Please reboot the server to begin the installation."
REINSTALL_SCRIPT
/usr/bin/chmod +x /usr/local/sbin/pxe-reinstall
 
echo "--- Disabling PXE boot for this host to ensure local boot on next startup ---"
# Find the first active network interface that is not 'lo' (loopback).
# This is more reliable in the %post environment than using 'hostname -I'.
INTERFACE_NAME=$(/usr/sbin/ip -o link show | /usr/bin/awk '!/LOOPBACK/ && /state UP/ {print $2}' | /usr/bin/sed 's/://' | /usr/bin/head -n 1)

echo "DEBUG: Discovered active interface: '${INTERFACE_NAME}'"

if [ -n "$INTERFACE_NAME" ]; then
    # Get the MAC address from the discovered interface.
    MAC_ADDR=$(/usr/bin/cat /sys/class/net/$INTERFACE_NAME/address)
    echo "DEBUG: Found MAC address: '${MAC_ADDR}'"

    API_URL="http://${SERVER_IP}:5001/clients/${MAC_ADDR}/pxe"
    echo "DEBUG: Sending DELETE request to ${API_URL}"

    # Use curl with verbose output (-v) and capture the HTTP status code.
    # The -s flag is removed to allow verbose logging.
    HTTP_STATUS=$(/usr/bin/curl -v -o /dev/null -w "%{http_code}" -X DELETE "${API_URL}")
    CURL_EXIT_CODE=$?

    echo "DEBUG: curl exit code: ${CURL_EXIT_CODE}"
    echo "DEBUG: API server responded with HTTP status: ${HTTP_STATUS}"

    if [ "${CURL_EXIT_CODE}" -eq 0 ] && [ "${HTTP_STATUS}" -eq 200 ]; then
        echo "SUCCESS: Successfully disabled PXE boot via API."
    else
        echo "ERROR: Failed to disable PXE boot. Check curl output above for details."
    fi
else
    echo "Warning: Could not determine MAC address to disable PXE boot via API."
fi

/usr/bin/firewall-cmd --reload
 
echo "--- KICKSTART POST-INSTALL SCRIPT FINISHED ---"

# Disable command tracing at the end of the script
set +x
%end
```

### Section 2.4: Set up the PXE Boot Control API

This API dynamically manages the `/etc/dhcp/dhcpd6-clients.conf` file to enable or disable PXE booting on demand.

#### 1. Create the API Script

Create the file `/var/lib/tftpboot/pxe_api.py`.
```bash
sudo nano /var/lib/tftpboot/pxe_api.py
```

Paste the following Python code.
```python
#!/usr/bin/env python3
import os
import logging
from logging.handlers import RotatingFileHandler
import re
import subprocess
from flask import Flask, request, jsonify

# --- Configuration ---
DHCPD6_CLIENTS_FILE = "/etc/dhcp/dhcpd6-clients.conf"
LOG_DIR = "/var/log/pxe_api"
LOG_FILE = os.path.join(LOG_DIR, "pxe_api.log")

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Logging Configuration ---
os.makedirs(LOG_DIR, exist_ok=True)
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=5)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

# --- Helper Functions ---

def is_valid_mac(mac: str) -> bool:
    """Validates a MAC address format."""
    return re.match(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$", mac) is not None

def restart_dhcp_service():
    """Restarts the DHCPv6 service to apply changes."""
    # --- IMPORTANT: CHOOSE THE CORRECT SERVICE NAME ---
    # For Ubuntu, use "isc-dhcp-server6"
    # For CentOS, use "dhcpd6"
    service_name = "dhcpd6" # or "isc-dhcp-server6"
    # -------------------------------------------------
    try:
        subprocess.run(["systemctl", "restart", service_name], check=True)
        app.logger.info(f"Successfully restarted {service_name}.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        app.logger.error(f"Failed to restart {service_name}: {e}")
        return False

@app.route("/clients/<mac>/pxe", methods=["PUT"])
def set_pxe_install(mac: str):
    """Adds a client to the known-clients list in DHCPv6 to enable installation."""
    mac = mac.lower()
    if not is_valid_mac(mac):
        return jsonify({"status": "error", "message": "Invalid MAC address format."}), 400

    mac_with_colons = mac.replace("-", ":")
    host_entry = f'\nhost install-client-{mac_with_colons.replace(":", "-")} {{\n  hardware ethernet {mac_with_colons};\n}}\n'

    try:
        if os.path.exists(DHCPD6_CLIENTS_FILE):
            with open(DHCPD6_CLIENTS_FILE, "r") as f:
                if mac_with_colons in f.read():
                    return jsonify({"status": "success", "message": "Client already enabled."}), 200

        with open(DHCPD6_CLIENTS_FILE, "a") as f:
            f.write(host_entry)

        app.logger.info(f"SUCCESS: Added {mac_with_colons} to DHCPv6 install list.")
        if not restart_dhcp_service():
            return jsonify({"status": "error", "message": "Failed to restart DHCPv6 service."}), 500

        return jsonify({"status": "success", "message": f"Client {mac} enabled for PXE install."}), 201

    except Exception as e:
        app.logger.error(f"FAILURE: Could not enable install for MAC {mac}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/clients/<mac>/pxe", methods=["DELETE"])
def set_pxe_localboot(mac: str):
    """Removes a client from the DHCPv6 known-clients list."""
    mac = mac.lower()
    if not is_valid_mac(mac):
        return jsonify({"status": "error", "message": "Invalid MAC address format."}), 400

    if not os.path.exists(DHCPD6_CLIENTS_FILE):
        return jsonify({"status": "success", "message": "Client already disabled."}), 200

    try:
        with open(DHCPD6_CLIENTS_FILE, "r") as f:
            lines = f.readlines()

        mac_with_hyphens = mac.replace(":", "-")
        host_regex = re.compile(r"\s*host\s+install-client-" + re.escape(mac_with_hyphens) + r"\s*\{[^}]*\}\s*", re.DOTALL)

        with open(DHCPD6_CLIENTS_FILE, "w") as f:
            content = "".join(lines)
            new_content, count = host_regex.subn("", content)
            f.write(new_content)

        if count > 0:
            app.logger.info(f"SUCCESS: Removed {mac} from DHCPv6 install list.")
            if not restart_dhcp_service():
                 return jsonify({"status": "error", "message": "Failed to restart DHCPv6 service."}), 500
        else:
            app.logger.info(f"INFO: MAC {mac} not found in install list.")

        return jsonify({"status": "success", "message": f"Client {mac} disabled from PXE install."}), 200

    except Exception as e:
        app.logger.error(f"FAILURE: Could not disable for MAC {mac}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
```

> **IMPORTANT**: In the `pxe_api.py` script above, you **must** edit the `service_name` variable inside the `restart_dhcp_service` function to match your server's OS:
> - For **Ubuntu**, set it to: `service_name = "isc-dhcp-server6"`
> - For **CentOS**, set it to: `service_name = "dhcpd6"`

#### 2. Create the Systemd Service

Create a service file to run the API automatically.
```bash
sudo nano /etc/systemd/system/pxe-control.service
```
The content is the same for both Ubuntu and CentOS.
```ini
[Unit]
Description=PXE Boot Control API Service
After=network.target

[Service]
User=root
Group=root
ExecStart=/usr/bin/python3 /var/lib/tftpboot/pxe_api.py
Restart=always
# systemd will create and manage the log directory
LogsDirectory=pxe_api

[Install]
WantedBy=multi-user.target
```

### Section 2.5: Create the Client Management Tool

This script provides a simple command-line interface to the API.
```bash
sudo nano /usr/local/sbin/pxe-client-manager
```
Paste the following bash script:
```bash
#!/bin/bash
# A simple tool to manage PXE boot settings for clients via the PXE Control API.

API_SERVER="http://127.0.0.1:5001"

usage() {
    echo "Usage: $(basename "$0") <command> <mac_address>"
    echo "Commands:"
    echo "  add, enable      Enable PXE installation for the client."
    echo "  del, disable     Disable PXE installation for the client."
    echo "  status, list     Show a list of all clients enabled for PXE boot."
}

if [ "$#" -lt 1 ]; then
    usage
    exit 1
fi

COMMAND=$(echo "$1" | tr '[:upper:]' '[:lower:]')
MAC_ADDRESS=$2

case "$COMMAND" in
    add|enable)
        if [ -z "$MAC_ADDRESS" ]; then usage; exit 1; fi
        curl -s -X PUT "${API_SERVER}/clients/${MAC_ADDRESS}/pxe" | python3 -m json.tool
    ;;
    del|disable)
        if [ -z "$MAC_ADDRESS" ]; then usage; exit 1; fi
        curl -s -X DELETE "${API_SERVER}/clients/${MAC_ADDRESS}/pxe" | python3 -m json.tool
    ;;
    status|list)
        curl -s -X GET "${API_SERVER}/clients" | python3 -m json.tool
    ;;
    *)
        echo "Error: Unknown command '$COMMAND'" >&2
        usage
        exit 1
        ;;
esac
```

Make the script executable:
```bash
sudo chmod +x /usr/local/sbin/pxe-client-manager
```

---

## Part 3: Service Activation and Usage

### Section 3.1: Start and Enable Services

Reload the systemd daemon to recognize the new API service, then start all services.

**For Ubuntu:**
```bash
sudo systemctl daemon-reload
sudo systemctl restart isc-dhcp-server
sudo systemctl restart isc-dhcp-server6
sudo systemctl restart tftpd-hpa
sudo systemctl restart apache2
sudo systemctl enable --now pxe-control.service
```

**For CentOS Stream 9:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dhcpd
sudo systemctl enable --now dhcpd6
sudo systemctl enable --now tftp.socket
sudo systemctl enable --now httpd
sudo systemctl enable --now pxe-control.service
```

### Section 3.2: Using the PXE System

1.  **Enable a client for installation**:
    From the PXE server, run the management tool with the client's MAC address.
    ```bash
    sudo pxe-client-manager add 08:00:27:12:34:56
    ```

2.  **Boot the client**:
    Power on the client machine and ensure it is set to boot from the network (PXE). It will receive an IP, download the boot files, and start the automated installation.

3.  **Installation Completes**:
    At the end of the Kickstart `%post` script, the client automatically calls the API to disable PXE booting for its own MAC address.

4.  **Reboot**:
    The server reboots into its newly installed operating system from the local disk.

5.  **Re-installing a server**:
    Log in to the client machine you wish to re-install and run the script created by the Kickstart file.
    ```bash
    sudo pxe-reinstall
    ```
    Confirm the prompt, then reboot the machine. It will once again boot into the PXE installation menu.

## Troubleshooting
- **DHCP Issues**: Check service status and logs. On Ubuntu, check `journalctl -u isc-dhcp-server -u isc-dhcp-server6`. On CentOS, check `journalctl -u dhcpd -u dhcpd6`.
- **TFTP/HTTP Issues**: Ensure services are running and firewall/SELinux rules are correct. Use `curl http://<server-ip>/ks/centos9-ks.cfg` to test accessibility.
- **API Issues**: Check the API service status with `systemctl status pxe-control.service` and view logs with `journalctl -u pxe-control.service -f`.
- **Kickstart Issues**: During installation, press `Ctrl+Alt+F3` on the client to switch to a shell. Logs are located in `/tmp`. After installation, check `/root/ks-post.log` and `/root/ks-post-script.log` on the client.
