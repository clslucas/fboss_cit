# CentOS Stream 9 PXE Automated Installation on a Single Ubuntu Server

## Document Information
- **Document Version**: 1.0
- **Creation Date**: January 2024
- **Applicable Environment**: Test/Production Environment
- **Operating System**: Ubuntu Server + CentOS Stream 9

## Table of Contents
1. [Environment Overview](#environment-overview)
2. [Ubuntu DHCP Server Configuration](#ubuntu-dhcp-server-configuration)
3. [Ubuntu TFTP/HTTP Server Configuration](#ubuntu-tftphttp-server-configuration)
4. [PXE Boot Menu Configuration](#pxe-boot-menu-configuration)
5. [GRUB2 Boot Menu Configuration (for UEFI)](#grub2-boot-menu-configuration-for-uefi)
6. [Kickstart Automated Installation Configuration](#kickstart-automated-installation-configuration)
7. [Service Startup and Verification](#service-startup-and-verification)
8. [Client Installation Test](#client-installation-test)
9. [Troubleshooting Guide](#troubleshooting-guide)
10. [Appendix](#appendix)

## Environment Overview

### Server Role Assignment
| Server  | Operating System | IP Address   | Service Role               | Notes                            |
|---------|------------------|------------------------------------------|----------------------------|----------------------------------|
| Server1 | Ubuntu Server    | 192.168.1.2 / fd00:1234:5678:1::10       | DHCP + TFTP + HTTP Server  | All-in-one PXE server            |

### Network Configuration
- **IPv4 Network Segment**: 192.168.1.0/24
- **IPv4 Gateway**: 192.168.1.1
- **IPv4 DHCP Range**: 192.168.1.100-200
- **IPv6 Network Segment**: fd00:1234:5678:1::/64
- **IPv6 DHCP Range**: fd00:1234:5678:1::100 - fd00:1234:5678:1::200
- **DNS**: 8.8.8.8, 8.8.4.4, 2001:4860:4860::8888


## Ubuntu DHCP Server Configuration

### Install DHCP Service


```bash
sudo apt update
sudo apt install isc-dhcp-server -y
```


### Configure Network Interface
Edit `/etc/default/isc-dhcp-server`:


```ini
INTERFACESv4="eno3"
```

### Configure Network Interface
Edit `/etc/default/isc-dhcp-server6`:

```ini
INTERFACESv6="eno3"
```


### Configure DHCP Service
Edit `/etc/dhcp/dhcpd.conf`:


```ini
option domain-name "pxe.lab";

option domain-name-servers 8.8.8.8, 8.8.4.4;

default-lease-time 600;

max-lease-time 7200;

authoritative;

# Add this logic to detect client architecture for IPv4
option client-arch code 93 = unsigned integer 16;

subnet 192.168.1.0 netmask 255.255.255.0 {
    range 192.168.1.100 192.168.1.200;
    option routers 192.168.1.1;
    option subnet-mask 255.255.255.0;
    next-server 192.168.1.2;

    # --- Host Definitions for Allowed Clients ---
    # Add a 'host' block for each machine you want to allow.
    # These clients will be assigned a specific IP address.

    # Default to BIOS boot file
    filename "pxelinux.0";

    # Check client architecture and provide UEFI boot file if needed
    if option client-arch = 00:07 {
        # UEFI x64
        filename "grubx64.efi";
    } else if option client-arch = 00:09 {
        # UEFI x64
        filename "grubx64.efi";
    }
}
```

### Assigning Static IP Addresses (Optional)
To assign a fixed IP address to a specific client, you can add a `host` block based on its MAC address.

**For IPv4:**
Edit `/etc/dhcp/dhcpd.conf` and add a host definition. This ensures a client always gets the same IPv4 address.


```ini
host pxe-client-01 {
  hardware ethernet 08:00:27:12:34:56; # Replace with client's MAC address
  fixed-address 192.168.1.50;        # Replace with the desired static IP
}
```


**For IPv6:**
Edit `/etc/dhcp/dhcpd6.conf` to assign a fixed IPv6 address.


```ini
host pxe-client-01 {
  hardware ethernet 08:00:27:12:34:56;      # Replace with client's MAC address
  fixed-address6 fd00:1234:5678:1::50;    # Replace with the desired static IPv6
}
```
### Configure DHCPv6 Service
Edit `/etc/dhcp/dhcpd6.conf`:

```ini

default-lease-time 600;
max-lease-time 7200;
authoritative;

# Deny requests from unknown clients for enhanced security.
deny unknown-clients;

option dhcp6.name-servers 2001:4860:4860::8888, 2001:4860:4860::8844;


subnet6 fd00:1234:5678:1::/64 {
    # This pool is only available to clients defined in 'host' blocks
    # that do not have a 'fixed-address6' specified.
    pool6 {
        range6 fd00:1234:5678:1::100 fd00:1234:5678:1::200;
        allow known-clients;
    }

    # --- Host Definitions for Allowed Clients ---
    # Add a 'host' block for each machine you want to allow.
    # These clients will be assigned a specific IPv6 address.
    
    # Provide the router (gateway) for the IPv6 subnet. This is critical for connectivity.
    #option dhcp6.routers fd00:1234:5678:1::1;

    # Logic to serve different boot files based on client architecture
    if option dhcp6.client-arch-type = 00:07 {
        # UEFI x64 Client
        option dhcp6.bootfile-url "tftp://[fd00:1234:5678:1::10]/grubx64.efi";
    } elsif option dhcp6.client-arch-type = 00:09 {
        # UEFI x64 Client (EBC)
        option dhcp6.bootfile-url "tftp://[fd00:1234:5678:1::10]/grubx64.efi";
    } else {
        # Default for other UEFI clients, though BIOS clients use IPv4/DHCPv4.
        option dhcp6.bootfile-url "tftp://[fd00:1234:5678:1::10]/pxelinux.0";
    }

    host pxe-client-01 {
      hardware ethernet 88:5a:23:34:0d:65;      # Client 1 MAC address
      fixed-address6 fd00:1234:5678:1::50;
    }

    host pxe-client-02 {
      hardware ethernet 88:5a:23:34:0e:7d;      # Client 2 MAC address
      fixed-address6 fd00:1234:5678:1::51;
    }
}

```

### Start DHCP Service
```bash
sudo systemctl enable --now isc-dhcp-server
sudo systemctl enable --now isc-dhcp-server6

sudo systemctl status isc-dhcp-server
sudo systemctl status isc-dhcp-server6

```

## Ubuntu TFTP/HTTP Server Configuration

### Install Necessary Packages
```bash

sudo apt update

sudo apt install -y tftpd-hpa apache2 syslinux-common pxelinux wget createrepo-c
```

### Configure TFTP Service
Edit `/etc/default/tftpd-hpa` to enable the service and set options.


```ini
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/var/lib/tftpboot"
TFTP_ADDRESS=":69"
TFTP_OPTIONS="--secure --create"
```


### Configure HTTP Service

```bash
sudo mkdir -p /var/www/html/ks

sudo systemctl enable --now apache2
```


### Prepare Installation Files

```bash
# Create TFTP directory structure
sudo mkdir -p /var/lib/tftpboot/pxelinux.cfg
sudo mkdir -p /var/lib/tftpboot/images/centos9

# Copy PXE boot files from syslinux package.
# The location of pxelinux.0 can vary. First, find it:
# sudo find /usr -name pxelinux.0
# Then, copy the file using the path found. For example:
sudo cp /usr/lib/PXELINUX/pxelinux.0 /var/lib/tftpboot/
sudo cp /usr/lib/syslinux/modules/bios/{vesamenu.c32,ldlinux.c32} /var/lib/tftpboot/
```

```bash
# Download the full CentOS Stream 9 DVD ISO. This file is large (~9GB).
sudo mkdir -p /opt/iso
cd /opt/iso
sudo wget https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/iso/CentOS-Stream-9-latest-x86_64-dvd1.iso -O centos9-dvd.iso
```

```bash
# Create a mount point and mount the ISO to serve it via HTTP
sudo mkdir -p /var/www/html/centos/9-stream/install
sudo mount -o loop /opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install

# To make the mount persistent across reboots, add it to /etc/fstab
echo "/opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install iso9660 loop 0 0" | sudo tee -a /etc/fstab

# Copy kernel and initrd for all boot types
sudo cp /var/www/html/centos/9-stream/install/images/pxeboot/{vmlinuz,initrd.img} /var/lib/tftpboot/images/centos9/

# Copy UEFI boot files
sudo cp /var/www/html/centos/9-stream/install/EFI/BOOT/grubx64.efi /var/lib/tftpboot/
```

### Create a Local Installation Mirror (Optional but Recommended)

To avoid relying on an internet connection during installation and to speed up the process, you can create a local mirror of the CentOS Stream repositories. This is an alternative to using the mounted ISO for repository access.

**Note:** This will download a significant amount of data (20GB+) and will take some time.

```bash
# 1. Create the directory structure for the repositories on your web server
sudo mkdir -p /var/www/html/centos/9-stream/BaseOS/x86_64/os/
sudo mkdir -p /var/www/html/centos/9-stream/AppStream/x86_64/os/

# Create the directory
sudo mkdir -p /var/www/html/centos/9-stream/custom/x86_64/

# Copy your custom RPM into it (replace with your actual RPM file)
sudo cp /path/to/my-custom-tool-1.0-1.el9.x86_64.rpm /var/www/html/centos/9-stream/custom/x86_64/
# Update the repository metadata
sudo createrepo_c --update /var/www/html/centos/9-stream/custom/x86_64/

# 2. Verify that the files are accessible via HTTP
# This command should return a 200 OK status code and list directory contents.
curl -g http://192.168.1.2/centos/9-stream/BaseOS/x86_64/os/

echo "Local mirror creation complete."
```

## PXE Boot Menu Configuration

Create `/var/lib/tftpboot/pxelinux.cfg/default`:


```
DEFAULT vesamenu.c32

PROMPT 0

TIMEOUT 100

MENU TITLE CentOS Stream 9 PXE Install Server

LABEL auto_install

MENU LABEL ^Automated CentOS Stream 9 Installation

KERNEL images/centos9/vmlinuz

APPEND initrd=images/centos9/initrd.img ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text inst.ks=http://192.168.1.2/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 console=ttyS0,57600n8 inst.cmdline

LABEL manual_install

MENU LABEL ^Manual CentOS Stream 9 Installation

KERNEL images/centos9/vmlinuz

APPEND initrd=images/centos9/initrd.img ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text biosdevname=0 net.ifnames=0

LABEL local

MENU LABEL Boot from ^Local Drive

LOCALBOOT 0
```


## GRUB2 Boot Menu Configuration (for UEFI)

Create `/var/lib/tftpboot/grub.cfg`. This is the configuration file for UEFI clients that load `grubx64.efi`.


```
set timeout=10

menuentry 'Automated CentOS Stream 9 Installation (UEFI)' {
    linuxefi images/centos9/vmlinuz ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text inst.ks=http://192.168.1.2/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 console=ttyS0,57600n8 inst.cmdline
    initrdefi images/centos9/initrd.img
}

menuentry 'Manual CentOS Stream 9 Installation (UEFI)' {
    linuxefi images/centos9/vmlinuz ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text biosdevname=0 net.ifnames=0 console=ttyS0,57600n8
    initrdefi images/centos9/initrd.img
}

menuentry 'Boot from Local Drive' {
    exit
}
```

# Kickstart Automated Installation Configuration
Create `/var/www/html/ks/centos9-ks.cfg`:

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

# Role-specific packages are added dynamically via a script block
%include /tmp/packages.ks
%end
 
%pre
#!/bin/bash
# This script runs in the installer environment before partitioning.

# --- Find PXE Server IP from Kernel Arguments ---
REPO_URL=$(grep -o 'inst.repo=[^ ]*' /proc/cmdline | cut -d'=' -f2)
SERVER_IP=$(echo "$REPO_URL" | awk -F/ '{print $3}' | sed -e 's/\[//' -e 's/\]//')
HTTP_BASE="http://${SERVER_IP}"
 
# --- Debugging Output ---
echo "--- KICKSTART PRE-SCRIPT DEBUG ---" > /dev/tty1
echo "Detected SERVER_IP: ${SERVER_IP}" > /dev/tty1

# --- Detect Server Role from Kernel Arguments ---
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
 
# --- Generate Dynamic Package List ---
echo "Generating package list for role: ${ROLE}" > /dev/tty1
cat > /tmp/packages.ks <<PACKAGES_EOF
# This file is generated by the %pre script

PACKAGES_EOF

case "$ROLE" in
    web)
        echo "httpd" >> /tmp/packages.ks
        ;;
    db)
        echo "mariadb-server" >> /tmp/packages.ks
        ;;
esac
# --- Generate Dynamic Partitioning and Bootloader Scheme ---
echo "Generating partitioning and bootloader configuration..." > /dev/tty1

# --- Dynamically Detect First Disk ---
# Find the first block device of type 'disk', excluding non-installable devices like zram.
FIRST_DISK=$(lsblk -d -n -o NAME,TYPE | grep -E 'disk' | grep -v 'zram' | head -n 1 | awk '{print $1}')
echo "Detected first disk for installation: ${FIRST_DISK}" > /dev/tty1

# Start with clearing all partitions and setting the bootloader location.
cat > /tmp/partitioning.ks <<PART_EOF
clearpart --all --initlabel
# Use the dynamically detected disk to prevent interactive prompts.
ignoredisk --only-use=${FIRST_DISK}
bootloader --location=mbr
PART_EOF

if [ -d /sys/firmware/efi ]; then
    # UEFI system detected
    echo "Boot Mode: UEFI" > /dev/tty1
    # Add the EFI boot partition, specifying the disk.
    echo "part /boot/efi --fstype=\"efi\" --size=200 --ondisk=${FIRST_DISK}" >> /tmp/partitioning.ks
 else
    # BIOS system detected
    echo "Boot Mode: BIOS" > /dev/tty1
fi

# Base partitioning scheme for all roles
cat >> /tmp/partitioning.ks <<PART_EOF
# Partitioning for role: ${ROLE}

part /boot --fstype="xfs" --size=1024 --ondisk=${FIRST_DISK}
part pv.01 --size=1 --grow --ondisk=${FIRST_DISK}
volgroup vg_main pv.01
PART_EOF
 
# Append role-specific logical volumes
case "$ROLE" in
     web)
        # Web Server: Larger /var/www for web content and bigger /var/log.
        cat >> /tmp/partitioning.ks <<PART_EOF
logvol swap --vgname=vg_main --size=4096 --name=lv_swap
logvol / --vgname=vg_main --size=20480 --name=lv_root --fstype="xfs" --label=root
logvol /apphome --vgname=vg_main --size=5120 --name=lv_apphome --fstype="xfs"
logvol /var/log --vgname=vg_main --size=10240 --name=lv_log --fstype="xfs"
logvol /var/www --vgname=vg_main --size=20480 --grow --name=lv_www --fstype="xfs"
PART_EOF
        ;;
     db)
        # Database Server: Huge partition for data, more swap.
        cat >> /tmp/partitioning.ks <<PART_EOF
logvol swap --vgname=vg_main --size=8192 --name=lv_swap
logvol / --vgname=vg_main --size=20480 --name=lv_root --fstype="xfs" --label=root
logvol /apphome --vgname=vg_main --size=2048 --name=lv_apphome --fstype="xfs"
logvol /var/lib/mysql --vgname=vg_main --size=51200 --grow --name=lv_mysql --fstype="xfs"
PART_EOF
        ;;
     *)
        # Generic/Default Server
        cat >> /tmp/partitioning.ks <<PART_EOF
logvol swap --vgname=vg_main --size=4096 --name=lv_swap
logvol / --vgname=vg_main --size=20480 --name=lv_root --fstype="xfs" --label=root
logvol /apphome --vgname=vg_main --size=5120 --name=lv_apphome --fstype="xfs"
logvol /home --vgname=vg_main --size=10240 --grow --name=lv_home --fstype="xfs"
PART_EOF
        ;;
esac
%end
 
%post --log=/root/ks-post.log
#!/bin/bash
# This script runs in the chroot of the newly installed system before reboot.

echo "--- KICKSTART POST-INSTALL SCRIPT ---"

# --- Find PXE Server IP and Role from Kernel Arguments ---
REPO_URL=$(grep -o 'inst.repo=[^ ]*' /proc/cmdline | cut -d'=' -f2)
SERVER_IP=$(echo "$REPO_URL" | awk -F/ '{print $3}' | sed -e 's/\[//' -e 's/\]//')

ROLE=$(grep -o 'inst.ks.role=[^ ]*' /proc/cmdline | cut -d'=' -f2)
[ -z "$ROLE" ] && ROLE="generic"

echo "Detected PXE Server IP: ${SERVER_IP}"
echo "Detected Server Role: ${ROLE}"

# --- User SSH Key Setup ---
echo "Configuring SSH keys for users..."
# Root
install -d -m 700 -o root -g root /root/.ssh
curl -s -o /root/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_root"
chmod 600 /root/.ssh/authorized_keys
chown root:root /root/.ssh/authorized_keys
# Test
install -d -m 700 -o test -g test /home/test
install -d -m 700 -o test -g test /home/test/.ssh
curl -s -o /home/test/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_test" && \
    chmod 600 /home/test/.ssh/authorized_keys && chown test:test /home/test/.ssh/authorized_keys
# Appuser
install -d -m 700 -o appuser -g appuser /apphome/.ssh
curl -s -o /apphome/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_appuser"
chmod 600 /apphome/.ssh/authorized_keys
chown appuser:appuser /apphome/.ssh/authorized_keys

# --- System Configuration ---
echo "Setting system hostname..."
IP_ADDR=$(hostname -I | awk '{print $1}' | tr '.' '-')
hostnamectl set-hostname "host-${IP_ADDR}"

# --- Create PXE Re-install Utility ---
echo "Creating /usr/local/sbin/pxe-reinstall utility..."
cat > /usr/local/sbin/pxe-reinstall <<'REINSTALL_SCRIPT'
#!/bin/bash

PXE_SERVER_IP="${SERVER_IP}"
if [ -z "$PXE_SERVER_IP" ]; then
    echo "Error: Could not determine PXE Server IP. Cannot create pxe-reinstall script."
    exit 0 # Exit gracefully from post-install
fi

API_PORT="5001"

# Find the MAC address of the first active, non-virtual interface
MAC_ADDR=$(ip -o link show | awk '!/LOOPBACK/ && /LOWER_UP/ {print $17; exit}')

if [ -z "$MAC_ADDR" ]; then
    echo "Error: Could not determine an active MAC address."
    exit 1
fi

echo "This script will configure the server to boot from PXE on the next reboot."
echo "Server MAC Address: $MAC_ADDR"
read -p "Are you sure you want to continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo "Enabling PXE boot for next reboot..."
curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"mac\": \"$MAC_ADDR\"}" \
    "http://${PXE_SERVER_IP}:${API_PORT}/pxe/enable"

echo "Done. Please reboot the server to begin the installation."
REINSTALL_SCRIPT

chmod +x /usr/local/sbin/pxe-reinstall

# --- Role-Specific Post-Install Tasks ---
case "$ROLE" in
     web)
        echo "Configuring as a web server..."
        systemctl enable httpd
        echo "<h1>Web Server - Deployed via PXE</h1>" > /var/www/html/index.html
        firewall-cmd --add-service=http --permanent
        ;;
     db)
        echo "Configuring as a database server..."
        systemctl enable mariadb
        firewall-cmd --add-service=mysql --permanent
        ;;
     *)
        echo "No specific role configuration for 'generic' server."
        ;;
esac

# --- LLDP Configuration ---
# Enable the LLDP agent daemon to start on boot. This makes the server discoverable on the network.
echo "Enabling LLDP service..."
systemctl enable lldpad

echo "Enabling root SSH login with password..."
# Ensure PermitRootLogin is set to 'yes' to allow root login.
sed -i 's/.*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
 
# --- Disable PXE Boot for this Host ---
echo "Disabling PXE boot for this host to ensure local boot on next startup..."
MAC_ADDR=$(ip -o link show | awk '!/LOOPBACK/ && /LOWER_UP/ {print $17; exit}')
if [ -n "$MAC_ADDR" ]; then
    curl -s -X POST -H "Content-Type: application/json" \
        -d "{\"mac\": \"$MAC_ADDR\"}" \
        "http://${SERVER_IP}:5001/pxe/disable"
else
    echo "Warning: Could not determine MAC address to disable PXE boot."
fi

echo "Performing final system update. This may take a few minutes..."
# Install epel-release first, then update all packages.
#dnf -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && dnf -y update
 
firewall-cmd --reload
 
echo "--- KICKSTART POST-INSTALL SCRIPT FINISHED ---"
%end
```


## Service Startup and Verification

### Start Services


```bash
# On the Ubuntu Server
sudo systemctl restart isc-dhcp-server
sudo systemctl restart isc-dhcp-server6
sudo systemctl restart tftpd-hpa
sudo systemctl restart apache2


```
### Configure Firewall

```bash
# Using ufw (Uncomplicated Firewall) on Ubuntu.
# These rules will allow the necessary traffic for both IPv4 and IPv6.
sudo ufw allow 67/udp     # DHCP (for IPv4)
sudo ufw allow 547/udp    # DHCPv6 (for IPv6)
sudo ufw allow 69/udp     # TFTP
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 443/tcp    # HTTPS (if you decide to use it)
sudo ufw allow 5001/tcp   # PXE Control API
sudo ufw allow ssh        # SSH for remote management

# Enable the firewall
sudo ufw enable
```

### Verify Services

```bash
# Check the status of each service to ensure they are running without errors.
sudo systemctl status isc-dhcp-server
sudo systemctl status isc-dhcp-server6
sudo systemctl status tftpd-hpa
sudo systemctl status apache2
curl -g -I http://[fd00:1234:5678:1::10]/ks/centos9-ks.cfg
```

## Client Installation Test
1.  Configure the client machine to boot from the network (PXE boot). This is usually done in the BIOS/UEFI settings.
2.  Power on the client machine and observe the PXE boot process.
3.  Select the "Automated CentOS Stream 9 Installation" option from the PXE boot menu.
4.  The installation should proceed automatically using the Kickstart configuration.
5.  After installation, verify that the system is configured as expected (users created, hostname set, services enabled, etc.).
## Troubleshooting Guide
- **DHCP Issues**: Ensure the DHCP server is running and correctly configured. Check logs in `/var/log/syslog` for DHCP-related messages.
- **TFTP Issues**: Verify that the TFTP server is running and that the necessary files are in the correct directory. Check `/var/log/syslog` for TFTP errors.
- **HTTP Issues**: Ensure the Apache server is running and that the installation files are accessible via HTTP. Use `curl` to test access to the Kickstart file and installation media.
- **Client Boot Issues**: Ensure the client is set to boot from the network and that it supports PXE booting. Check the client BIOS/UEFI settings.
- **Kickstart Issues**: Review the Kickstart log files on the client machine, typically found in `/var/log/anaconda/` for errors during installation.
## Appendix
- **Useful Commands**:
  - Restart services: `sudo systemctl restart <service-name>`
  - Check service status: `sudo systemctl status <service-name>`
  - View logs: `tail -f /var/log/syslog` or specific log files.
- **References**:
  - [ISC DHCP Server Documentation](https://kb.isc.org/docs/documentation)
  - [TFTPD-HPA Documentation](https://manpages.debian.org/stable/tftpd-hpa/tftpd.8.en.html)
  - [Apache HTTP Server Documentation](https://httpd.apache.org/docs/)
    - [RHEL 9 Installation Guide](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/performing_a_standard_rhel_9_installation/index)
    - [Kickstart Documentation](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/performing_an_advanced_rhel_9_installation/kickstart-reference_installing-rhel-as-an-experienced-user)
- **Log Locations**:
  - DHCP Server: `/var/log/syslog`
  - TFTP Server: `/var/log/syslog`
  - Apache Server: `/var/log/httpd/` or `/var/log/apache2/` depending on your distribution
  - Kickstart Logs: `/var/log/anaconda/`
- **Security Considerations**:
  - Ensure that the PXE server is on a secure network segment to prevent unauthorized access.
    - Use secure passwords and consider using SSH keys for remote access.
    - Regularly update the server software to patch vulnerabilities.
- **Backup Configurations**:
  - Regularly back up configuration files for DHCP, TFTP, and Apache to prevent data loss.
- **Maintenance Tips**:
  - Periodically check for updates to CentOS Stream 9 and apply them as needed.
- Monitor disk space on the PXE server to ensure there is enough space for installation files and logs.
- Test the PXE boot process periodically to ensure it continues to function correctly after updates or changes to the network environment.