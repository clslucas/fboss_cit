#!/bin/bash

# ==============================================================================
# PXE Server Setup Script for Ubuntu
# ==============================================================================
# This script automates the setup of a PXE server for CentOS Stream 9
# installations, including DHCP, TFTP, and HTTP services.
#
# Run this script with sudo:
#   sudo bash ./setup_pxe_server.sh
# ==============================================================================

set -e # Exit immediately if a command exits with a non-zero status.
set -o pipefail # Return the exit status of the last command in the pipe that failed

# --- Configuration ---
# Please review and change these variables to match your network environment.

# Network interface for DHCP/TFTP services
NETWORK_INTERFACE="eno3"

# IPv4 Configuration
IPV4_SERVER_IP="192.168.1.2"
IPV4_SUBNET="192.168.1.0"
IPV4_NETMASK="255.255.255.0"
IPV4_ROUTER="192.168.1.1"
IPV4_DHCP_RANGE_START="192.168.1.50"
IPV4_DHCP_RANGE_END="192.168.1.240"

# IPv6 Configuration
IPV6_SERVER_IP="fd00:1234:5678:1::10"
IPV6_SUBNET="fd00:1234:5678:1::/64"
IPV6_DHCP_RANGE_START="fd00:1234:5678:1::100"
IPV6_DHCP_RANGE_END="fd00:1234:5678:1::200"

# DNS Servers
IPV4_DNS_SERVERS="8.8.8.8, 8.8.4.4"
IPV6_DNS_SERVERS="2001:4860:4860::8888, 2001:4860:4860::8844"

# CentOS ISO URL
CENTOS_ISO_URL="https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/iso/CentOS-Stream-9-latest-x86_64-dvd1.iso"
ISO_DOWNLOAD_PATH="/opt/iso/centos9-dvd.iso"

# --- Pre-flight Checks ---
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script as root or with sudo."
  exit 1
fi

echo "--- Starting PXE Server Setup ---"

# --- 1. Install Required Packages ---
echo ">>> Installing DHCP, TFTP, HTTP, and utility packages..."
apt-get update
apt-get install -y isc-dhcp-server tftpd-hpa apache2 syslinux-common pxelinux wget createrepo-c

# --- 2. Configure DHCP Service (IPv4 & IPv6) ---
echo ">>> Configuring DHCP services..."

# Set listening interfaces
echo "INTERFACESv4=\"${NETWORK_INTERFACE}\"" > /etc/default/isc-dhcp-server
echo "INTERFACESv6=\"${NETWORK_INTERFACE}\"" > /etc/default/isc-dhcp-server6

# Configure DHCPv4 (dhcpd.conf)
cat > /etc/dhcp/dhcpd.conf <<EOF
option domain-name "pxe.lab";
option domain-name-servers ${IPV4_DNS_SERVERS};
default-lease-time 600;
max-lease-time 7200;
authoritative;

option client-arch code 93 = unsigned integer 16;

subnet ${IPV4_SUBNET} netmask ${IPV4_NETMASK} {
    range ${IPV4_DHCP_RANGE_START} ${IPV4_DHCP_RANGE_END};
    option routers ${IPV4_ROUTER};
    option subnet-mask ${IPV4_NETMASK};
    next-server ${IPV4_SERVER_IP};

    filename "pxelinux.0";

    if option client-arch = 00:07 or option client-arch = 00:09 {
        filename "grubx64.efi";
    }
}
EOF

# Configure DHCPv6 (dhcpd6.conf)
cat > /etc/dhcp/dhcpd6.conf <<EOF
default-lease-time 600;
max-lease-time 7200;
authoritative;

deny unknown-clients;

option dhcp6.name-servers ${IPV6_DNS_SERVERS};

subnet6 ${IPV6_SUBNET} {
    pool6 {
        range6 ${IPV6_DHCP_RANGE_START} ${IPV6_DHCP_RANGE_END};
        allow known-clients;
    }
    option dhcp6.bootfile-url "tftp://[${IPV6_SERVER_IP}]/grubx64.efi";
}

include "/etc/dhcp/dhcpd6-clients.conf";
EOF

# Create the include file for dynamic client management
touch /etc/dhcp/dhcpd6-clients.conf
chown _dhcp:_dhcp /etc/dhcp/dhcpd6-clients.conf # Ensure correct ownership

# --- 3. Configure TFTP Service ---
echo ">>> Configuring TFTP service..."
cat > /etc/default/tftpd-hpa <<EOF
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/var/lib/tftpboot"
TFTP_ADDRESS=":69"
TFTP_OPTIONS="--secure --create"
EOF

# --- 4. Configure HTTP Service ---
echo ">>> Configuring Apache HTTP service..."
mkdir -p /var/www/html/ks

# --- 5. Prepare Custom Repository ---
echo ">>> Preparing custom package repository..."
CUSTOM_REPO_PATH="/var/www/html/custom-files/kernel"
mkdir -p "${CUSTOM_REPO_PATH}"
echo "--> NOTE: Please ensure your custom kernel RPMs are placed in ${CUSTOM_REPO_PATH}"
echo "--> Running createrepo_c to generate repository metadata..."
# This command creates the 'repodata' directory needed by dnf.
# Run this command again if you add or remove RPMs from the directory.
createrepo_c "${CUSTOM_REPO_PATH}"

# --- 5. Prepare Installation Files ---
echo ">>> Preparing CentOS installation files..."

# Create TFTP directory structure
mkdir -p /var/lib/tftpboot/pxelinux.cfg
mkdir -p /var/lib/tftpboot/images/centos9

# Copy PXELINUX boot files
cp /usr/lib/PXELINUX/pxelinux.0 /var/lib/tftpboot/
cp /usr/lib/syslinux/modules/bios/{vesamenu.c32,ldlinux.c32} /var/lib/tftpboot/

# Download CentOS ISO if it doesn't exist
if [ ! -f "${ISO_DOWNLOAD_PATH}" ]; then
    echo ">>> Downloading CentOS Stream 9 DVD ISO (~9GB). This may take a while..."
    mkdir -p "$(dirname "${ISO_DOWNLOAD_PATH}")"
    wget -O "${ISO_DOWNLOAD_PATH}" "${CENTOS_ISO_URL}"
else
    echo ">>> CentOS ISO already exists. Skipping download."
fi

# Mount ISO via HTTP
ISO_MOUNT_POINT="/var/www/html/centos/9-stream/install"
mkdir -p "${ISO_MOUNT_POINT}"
if ! mountpoint -q "${ISO_MOUNT_POINT}"; then
    mount -o loop "${ISO_DOWNLOAD_PATH}" "${ISO_MOUNT_POINT}"
    echo ">>> ISO mounted at ${ISO_MOUNT_POINT}"
else
    echo ">>> ISO mount point is already active."
fi

# Make mount persistent
if ! grep -q "${ISO_DOWNLOAD_PATH}" /etc/fstab; then
    echo "${ISO_DOWNLOAD_PATH} ${ISO_MOUNT_POINT} iso9660 loop 0 0" >> /etc/fstab
    echo ">>> Added ISO mount to /etc/fstab."
fi

# Copy kernel, initrd, and UEFI bootloader
echo ">>> Copying kernel and bootloader files to TFTP root..."
cp "${ISO_MOUNT_POINT}/images/pxeboot/{vmlinuz,initrd.img}" /var/lib/tftpboot/images/centos9/
cp "${ISO_MOUNT_POINT}/EFI/BOOT/grubx64.efi" /var/lib/tftpboot/

# --- 6. Create PXE Boot Menu (Legacy BIOS) ---
echo ">>> Creating Legacy BIOS PXE boot menu..."
cat > /var/lib/tftpboot/pxelinux.cfg/default <<EOF
DEFAULT vesamenu.c32
PROMPT 0
TIMEOUT 100
MENU TITLE CentOS Stream 9 PXE Install Server

LABEL auto_install
MENU LABEL ^Automated CentOS Stream 9 Installation
KERNEL images/centos9/vmlinuz
APPEND initrd=images/centos9/initrd.img ip=dhcp inst.repo=http://${IPV4_SERVER_IP}/centos/9-stream/install inst.text inst.ks=http://${IPV4_SERVER_IP}/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 console=ttyS0,57600n8 inst.cmdline

LABEL manual_install
MENU LABEL ^Manual CentOS Stream 9 Installation
KERNEL images/centos9/vmlinuz
APPEND initrd=images/centos9/initrd.img ip=dhcp inst.repo=http://${IPV4_SERVER_IP}/centos/9-stream/install inst.text biosdevname=0 net.ifnames=0

LABEL local
MENU LABEL Boot from ^Local Drive
LOCALBOOT 0
EOF

# --- 7. Configure Firewall ---
echo ">>> Configuring firewall (UFW)..."
ufw allow 67/udp     # DHCP
ufw allow 547/udp    # DHCPv6
ufw allow 69/udp     # TFTP
ufw allow 80/tcp     # HTTP
ufw allow 5001/tcp   # PXE Control API
ufw allow ssh
ufw --force enable

# --- 8. Start and Enable Services ---
echo ">>> Starting and enabling all services..."
systemctl enable --now isc-dhcp-server
systemctl enable --now isc-dhcp-server6
systemctl enable --now tftpd-hpa
systemctl enable --now apache2

echo "--- PXE Server Setup Complete! ---"
echo "Please create the GRUB and Kickstart configuration files next."
echo "Services status:"
systemctl is-active isc-dhcp-server isc-dhcp-server6 tftpd-hpa apache2


### 2. GRUB Configuration Generator

This simple script will create the `grub.cfg` file used by UEFI clients. It uses the IP address variables defined within the script.

I'll create this as a new file named `generate_grub_config.sh`.

```diff
#!/bin/bash

# ==============================================================================
# GRUB Configuration Generator for UEFI PXE Boot
# ==============================================================================
# This script creates the grub.cfg file in the TFTP root directory.
#
# Run this script with sudo:
#   sudo bash ./generate_grub_config.sh
# ==============================================================================

set -e

# --- Configuration ---
IPV4_SERVER_IP="192.168.1.2"
TFTP_ROOT="/var/lib/tftpboot"

if [ "$EUID" -ne 0 ]; then
  echo "Please run this script as root or with sudo."
  exit 1
fi

echo ">>> Generating GRUB config for UEFI clients..."

cat > "${TFTP_ROOT}/grub.cfg" <<EOF
set timeout=10

menuentry 'Automated CentOS Stream 9 Installation (UEFI)' {
    linuxefi images/centos9/vmlinuz ip=dhcp inst.repo=http://${IPV4_SERVER_IP}/centos/9-stream/install inst.text inst.ks=http://${IPV4_SERVER_IP}/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 inst.cmdline console=ttyS0,57600n8
    initrdefi images/centos9/initrd.img
}

menuentry 'Manual CentOS Stream 9 Installation (UEFI)' {
    linuxefi images/centos9/vmlinuz ip=dhcp inst.repo=http://${IPV4_SERVER_IP}/centos/9-stream/install inst.text biosdevname=0 net.ifnames=0 console=ttyS0,57600n8
    initrdefi images/centos9/initrd.img
}

menuentry 'Boot from Local Drive' {
    exit
}
EOF

echo "GRUB configuration written to ${TFTP_ROOT}/grub.cfg"

### 3. Kickstart Script

This is the Kickstart file from your guide. It should be placed in the `/var/www/html/ks/` directory on your PXE server so it can be accessed by clients during installation. I've extracted it into its own file for clarity.

I'll create this as a new file named `centos9-ks.cfg`.

```diff
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

### How to Use These Scripts

1.  **Save the Scripts**: Save the three code blocks above into their respective files (`setup_pxe_server.sh`, `generate_grub_config.sh`, and `centos9-ks.cfg`) in a directory on your Ubuntu server.
2.  **Run the Setup Script**: Execute the main setup script with `sudo`. This will install and configure all the necessary server components.
   ```bash
   sudo bash ./setup_pxe_server.sh
   ```
3.  **Generate GRUB Config**: After the main setup is complete, run the GRUB generator.
   ```bash
   sudo bash ./generate_grub_config.sh
   ```
4.  **Place the Kickstart File**: Copy the Kickstart file to the location expected by the HTTP server. The setup script already created the directory.
   ```bash
   sudo cp ./centos9-ks.cfg /var/www/html/ks/centos9-ks.cfg
   ```

Your PXE server should now be fully configured and ready to install CentOS Stream 9 on your client machines.
