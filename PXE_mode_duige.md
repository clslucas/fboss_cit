# CentOS Stream 9 PXE Automated Installation on a Single Ubuntu Server

## Document Information
- **Document Version**: 1.0
- **Creation Date**: January 2024
- **Applicable Environment**: Test/Production Environment
- **Operating System**: Ubuntu Server + CentOS Stream 9

## Table of Contents
1. [Environment Overview](#environment-overview)
2. [Network Architecture Design](#network-architecture-design)
3. [Ubuntu DHCP Server Configuration](#ubuntu-dhcp-server-configuration)
4. [CentOS TFTP/HTTP Server Configuration](#centos-tftphttp-server-configuration)
5. [PXE Boot Menu Configuration](#pxe-boot-menu-configuration)
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

## Network Architecture Design



+---------------------+

|   Network Switch    |

+----------+----------+

|

+-------------------+

|                   |                   |

+--------------------------+   +----------------------+

| Ubuntu Server            |   | PXE Client           |

| (DHCP, TFTP, HTTP)       |   | (To be installed)    |

| 192.168.1.10             |   | Gets IP via DHCP     |

+--------------------------+   +----------------------+


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

Edit `/etc/dhcp/dhcpd6.conf`:

```ini

default-lease-time 600;
max-lease-time 7200;
authoritative;

option dhcp6.name-servers 2001:4860:4860::8888, 2001:4860:4860::8844;


subnet6 fd00:1234:5678:1::/64 {
    range6 fd00:1234:5678:1::100 fd00:1234:5678:1::200;

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

sudo apt install -y tftpd-hpa apache2 syslinux-common pxelinux wget rsync
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

# 2. Use rsync to download the BaseOS repository.
echo "Syncing BaseOS repository... This will take a while."
sudo rsync -avz --delete rsync://rsync.centos.org/centos/9-stream/BaseOS/x86_64/os/ /var/www/html/centos/9-stream/BaseOS/x86_64/os/

# 3. Use rsync to download the AppStream repository.
echo "Syncing AppStream repository... This will also take a while."
sudo rsync -avz --delete rsync://rsync.centos.org/centos/9-stream/AppStream/x86_64/os/ /var/www/html/centos/9-stream/AppStream/x86_64/os/
# 4. Verify that the files are accessible via HTTP
# This command should return a 200 OK status code and list directory contents.
curl -g http://[fd00:1234:5678:1::10]/centos/9-stream/BaseOS/x86_64/os/

echo "Local mirror creation complete."
```

#### Automate Mirror Updates with Cron

To keep your local mirror current, you can create a cron job that runs the `rsync` commands on a schedule (e.g., daily).

```bash
# 1. Create a sync script.
# This script will contain the rsync commands and log the output
sudo tee /usr/local/bin/update_centos_mirror.sh > /dev/null <<'EOF'
#!/bin/bash

LOG_FILE="/var/log/centos_mirror_sync.log"

echo "========================================" >> $LOG_FILE
echo "Sync started at $(date)" >> $LOG_FILE

# Sync BaseOS repository
rsync -avz --delete rsync://rsync.centos.org/centos/9-stream/BaseOS/x86_64/os/ /var/www/html/centos/9-stream/BaseOS/x86_64/os/ >> $LOG_FILE 2>&1

# Sync AppStream repository
rsync -avz --delete rsync://rsync.centos.org/centos/9-stream/AppStream/x86_64/os/ /var/www/html/centos/9-stream/AppStream/x86_64/os/ >> $LOG_FILE 2>&1

echo "Sync finished at $(date)" >> $LOG_FILE
echo "========================================" >> $LOG_FILE
EOF

# 2. Make the script executable
sudo chmod +x /usr/local/bin/update_centos_mirror.sh

# 3. Add a cron job to run the script
# This example runs the script every day at 2:00 AM
# Use `sudo crontab -e` to edit the root user's crontab and add the following line:
0 2 * * * /usr/local/bin/update_centos_mirror.sh

# You can check the log file to see the sync history:
tail -f /var/log/centos_mirror_sync.log
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

APPEND initrd=images/centos9/initrd.img ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text inst.ks=http://192.168.1.2/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 console=ttyS0,57600n8

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
    linuxefi images/centos9/vmlinuz ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text inst.ks=http://192.168.1.2/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 console=ttyS0,57600n8
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

## Kickstart Automated Installation Configuration

### Create Centralized SSH Key Files (Recommended)

Instead of hardcoding SSH keys inside the Kickstart file, it's better practice to host them in separate files on your HTTP server. This makes key management much easier.

1.  Create files on your web server to hold the public keys for each user.
    ```bash
    sudo touch /var/www/html/ks/authorized_keys_root
    sudo touch /var/www/html/ks/authorized_keys_test
    ```

2.  Add the public SSH key(s) for the `root` user.
    ```bash
    # Replace with the root user's public SSH key
    echo "ssh-rsa AAAA... root-key-comment" | sudo tee /var/www/html/ks/authorized_keys_root
    ```

3.  Add the public SSH key(s) for the `test` user.
    ```bash
    # Replace with the test user's public SSH key
    echo "ssh-rsa AAAA... test-user-key-comment" | sudo tee /var/www/html/ks/authorized_keys_test
    ```

# Create a Directory for Snippets `/var/www/html/ks/snippets`:
1.  Create the directory to hold snippet files.
```bash
sudo mkdir -p /var/www/html/ks/snippets
```

2.  Create snippet files for package groups and post-install tasks.
```bash
# Snippet for base packages
sudo tee /var/www/html/ks/snippets/packages-base.ks > /dev/null <<'EOF'
@^minimal-environment
@"Development Tools"
vim-enhanced
epel-release
wget
curl
git
bash-completion
policycoreutils-python-utils
lldpad
my-custom-tool
EOF

# Snippet for web server packages
sudo tee /var/www/html/ks/snippets/packages-web.ks > /dev/null <<'EOF'
httpd
EOF

# Snippet for database server packages
sudo tee /var/www/html/ks/snippets/packages-db.ks > /dev/null <<'EOF'
mariadb-server
EOF

# Snippet for base post-install tasks (hostname, SSH keys, first-boot script)
sudo tee /var/www/html/ks/snippets/post-base-setup.ks > /dev/null <<'EOF'
#!/bin/bash
# This snippet is included in the main %post script.

echo "--- Running Base Post-Install Setup ---"

# --- Dynamically find the PXE server IP ---
REPO_URL=$(grep -o 'inst.repo=[^ ]*' /proc/cmdline | cut -d'=' -f2)
SERVER_IP=$(echo "$REPO_URL" | awk -F/ '{print $3}' | sed -e 's/\[//' -e 's/\]//')
echo "Detected PXE server IP: ${SERVER_IP}"

# --- User SSH Key Setup ---
echo "Configuring SSH keys for users..."
# Root
install -d -m 700 -o root -g root /root/.ssh
curl -s -o /root/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_root"
chmod 600 /root/.ssh/authorized_keys
chown root:root /root/.ssh/authorized_keys
# Test
install -d -m 700 -o test -g test /home/test/.ssh
curl -s -o /home/test/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_test"
chmod 600 /home/test/.ssh/authorized_keys
chown test:test /home/test/.ssh/authorized_keys
# Appuser
install -d -m 700 -o appuser -g appuser /apphome/.ssh
curl -s -o /apphome/.ssh/authorized_keys "http://${SERVER_IP}/ks/authorized_keys_appuser"
chmod 600 /apphome/.ssh/authorized_keys
chown appuser:appuser /apphome/.ssh/authorized_keys
echo "SSH keys configured."

# --- System Configuration ---
echo "Setting system hostname..."
IP_ADDR=$(hostname -I | awk '{print $1}' | tr '.' '-')
hostnamectl set-hostname "host-${IP_ADDR}"
echo "Hostname set to $(hostname)."

# --- First Boot Script Setup (via systemd) ---
echo "Configuring first-boot service..."
cat > /usr/local/bin/firstboot.sh <<'FBOOT_SH'
#!/bin/bash
echo "First boot script executed successfully on $(date)" > /root/first_boot_ran.log
systemctl disable firstboot.service
FBOOT_SH
chmod +x /usr/local/bin/firstboot.sh

cat > /etc/systemd/system/firstboot.service <<'FBOOT_SVC'
[Unit]
Description=One-time script to run on first boot
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/firstboot.sh
[Install]
WantedBy=multi-user.target
FBOOT_SVC
systemctl enable firstboot.service
echo "First-boot service enabled."
EOF

# Snippet for web server post-install configuration
sudo tee /var/www/html/ks/snippets/post-role-web.ks > /dev/null <<'EOF'
#!/bin/bash
echo "Configuring as a web server..."
systemctl enable httpd
echo "<h1>Web Server - Deployed via PXE</h1>" > /var/www/html/index.html
firewall-cmd --add-service=http --permanent
echo "Web server configuration complete."
EOF

# Snippet for database server post-install configuration
sudo tee /var/www/html/ks/snippets/post-role-db.ks > /dev/null <<'EOF'
#!/bin/bash
echo "Configuring as a database server..."
systemctl enable mariadb
firewall-cmd --add-service=mysql --permanent
echo "Database server configuration complete."
EOF
```

Create `/var/www/html/ks/centos9-ks.cfg`:


```kickstart
lang en_US.UTF-8

keyboard us

timezone Asia/Shanghai --utc

# WARNING: Using a plaintext password is not recommended for production environments.
rootpw --plaintext 11

# Create a standard test user account.
user --name=test --password=test --plaintext --homedir=/test

# Create a third user with a home directory on a separate partition.
# The --homedir flag is crucial here.
user --name=appuser --password=11 --plaintext --homedir=/apphome

# Use the modern authselect command instead of the deprecated auth/authconfig.
authselect select minimal with-mkhomedir --force

text

firstboot --disabled

# The installation source is defined by the 'inst.repo' kernel parameter in the PXE/GRUB menu.
# The installer automatically enables the BaseOS repository from the installation media.
# When using the 'repo' command, you must define a repository that provides the BaseOS group.
# The 'inst.repo' URL passed on the kernel command line serves this purpose.
# We add it here explicitly. This is the main installation source.
repo --name="install" --baseurl=http://192.168.1.2/centos/9-stream/install

# The AppStream repository is on the same media, but must be enabled separately.
repo --name="AppStream" --baseurl=http://192.168.1.2/centos/9-stream/install/AppStream

# Add our new custom local repository (if you create one).
# The IP address should match your PXE server. Use HTTP.
repo --name="custom" --baseurl=http://192.168.1.2/centos/9-stream/custom/x86_64/

services --enabled="sshd,chronyd,NetworkManager"

# Remove --boot-drive to let the installer automatically select the first disk.
bootloader --location=mbr

clearpart --all --initlabel

# Dynamic partitioning based on boot mode (BIOS vs UEFI)
# The partitioning scheme is written to /tmp/part-include by the %pre script.
%include /tmp/part-include

network --bootproto=dhcp --device=link --onboot=on --ipv6=auto

firewall --enabled --service=ssh --service=dhcpv6-client

selinux --enforcing

reboot --eject

%packages
# Install the "Development Tools" group. The @ symbol signifies a group,
# and quotes are needed because the name contains a space.
@"Development Tools"
%include http://192.168.1.2/ks/snippets/packages-base.ks

# The %pre script will write the role-specific package file to /tmp/packages-role.ks
%include /tmp/packages-role.ks
%end

%pre
#!/bin/bash
# This section runs before the installation starts.
# We detect the server role from kernel arguments and the boot mode (UEFI/BIOS)
# to create the appropriate partitioning scheme.

# --- Detect Server Role ---
# We parse /proc/cmdline to find the 'inst.ks.role' parameter.
# If it's not found, we default to 'generic'.
ROLE=$(grep -o 'inst.ks.role=[^ ]*' /proc/cmdline | cut -d'=' -f2)
if [ -z "$ROLE" ]; then
    ROLE="generic"
fi

# --- Generate Role-Specific Package Snippet ---
# Based on the role, we create a small file that includes the correct package snippet.
# This allows us to use %include in the %packages section.
case "$ROLE" in
    web)
        echo "%include http://192.168.1.2/ks/snippets/packages-web.ks" > /tmp/packages-role.ks
        ;;
    db)
        echo "%include http://192.168.1.2/ks/snippets/packages-db.ks" > /tmp/packages-role.ks
        ;;
    *)
        # Create an empty file for the generic role
        touch /tmp/packages-role.ks
        ;;
esac

# --- Detect Boot Mode ---
BOOT_PART=""
if [ -d /sys/firmware/efi ]; then
    # UEFI system detected
    BOOT_PART="part /boot/efi --fstype=\"efi\" --size=200"
else
    # BIOS system detected
    BOOT_PART="" # No separate EFI partition for BIOS
fi

# --- Generate Partitioning Scheme based on Role ---
# The partitioning scheme is written to /tmp/part-include.
cat > /tmp/part-include <<PART_EOF
# Partitioning for role: ${ROLE}
# Boot mode: $([ -n "$BOOT_PART" ] && echo "UEFI" || echo "BIOS")

$BOOT_PART
part /boot --fstype="xfs" --size=1024
part pv.01 --size=1 --grow
volgroup vg_main pv.01

PART_EOF

case "$ROLE" in
    web)
        # Web Server: Larger /var/www for web content and bigger /var/log.
        cat >> /tmp/part-include <<PART_EOF
logvol swap --vgname=vg_main --size=4096 --name=lv_swap
logvol / --vgname=vg_main --size=20480 --name=lv_root --fstype="xfs"
logvol /home --vgname=vg_main --size=5120 --name=lv_home --fstype="xfs"
logvol /apphome --vgname=vg_main --size=5120 --name=lv_apphome --fstype="xfs"
logvol /var/log --vgname=vg_main --size=10240 --name=lv_log --fstype="xfs"
logvol /var/www --vgname=vg_main --size=20480 --grow --name=lv_www --fstype="xfs"
PART_EOF
        ;;

    db)
        # Database Server: Huge partition for data, more swap.
        cat >> /tmp/part-include <<PART_EOF
logvol swap --vgname=vg_main --size=8192 --name=lv_swap
logvol / --vgname=vg_main --size=20480 --name=lv_root --fstype="xfs"
logvol /home --vgname=vg_main --size=2048 --name=lv_home --fstype="xfs"
logvol /apphome --vgname=vg_main --size=2048 --name=lv_apphome --fstype="xfs"
logvol /var/lib/mysql --vgname=vg_main --size=51200 --grow --name=lv_mysql --fstype="xfs"
PART_EOF
        ;;

    *)
        # Generic/Default Server
        cat >> /tmp/part-include <<PART_EOF
logvol swap --vgname=vg_main --size=4096 --name=lv_swap
logvol / --vgname=vg_main --size=20480 --name=lv_root --fstype="xfs"
logvol /home --vgname=vg_main --size=10240 --grow --name=lv_home --fstype="xfs"
logvol /apphome --vgname=vg_main --size=5120 --name=lv_apphome --fstype="xfs"
PART_EOF
        ;;
esac
%end

%post
--nochroot
# This section runs in the installer environment before the system is rebooted.
%end

%post --log=/root/ks-post.log
#!/bin/bash
# This section runs within the chroot of the newly installed system.

echo "--- Starting Kickstart Post-Installation Script ---"

# --- Dynamically find the PXE server IP ---
# Include the base post-install script from the web server
%include http://192.168.1.2/ks/snippets/post-base-setup.ks

# --- Role-Specific Configuration ---
# The %pre script has already detected the role. We re-detect it here for the %post environment.
ROLE=$(grep -o 'inst.ks.role=[^ ]*' /proc/cmdline | cut -d'=' -f2)
if [ -z "$ROLE" ]; then
    ROLE="generic"
fi

echo "Detected server role: ${ROLE}"

case "$ROLE" in
    web)
        %include http://192.168.1.2/ks/snippets/post-role-web.ks
        ;;
    db)
        %include http://192.168.1.2/ks/snippets/post-role-db.ks
        ;;
    *)
        echo "No specific role configuration for 'generic' server."
        ;;
esac

# --- Security Hardening ---
echo "Hardening SSH configuration..."
sed -i 's/^#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
echo "SSH daemon configured to allow root login with password."

# --- Final System Update ---
echo "Performing final system update. This may take a few minutes..."
dnf -y update

firewall-cmd --reload

echo "--- Kickstart Post-Installation Script Finished ---"
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
sudo ufw allow ssh        # SSH for remote management

# Enable the firewall
sudo ufw enable
```


### 验证服务


```bash
检查服务状态

sudo systemctl status isc-dhcp-server
sudo systemctl status isc-dhcp-server6
sudo systemctl status tftpd-hpa
sudo systemctl status apache2
curl -g -I http://[fd00:1234:5678:1::10]/ks/centos9-ks.cfg
```


## 客户端安装测试

### 安装流程
1. 客户端设置为网络启动(PXE)
2. 获取DHCP IP地址
3. 下载PXE引导文件
4. 显示启动菜单
5. 自动执行Kickstart安装
6. 安装完成自动重启

### 验证清单
- [ ] 客户端能获取IP地址
- [ ] 显示PXE启动菜单
- [ ] 自动开始安装过程
- [ ] 无需人工干预完成安装
- [ ] 系统重启后正常启动
- [ ] 网络配置正确
- [ ] 用户账户可正常登录

### First SSH Connection

After the installation is complete and the client has rebooted, you can connect to it via SSH. The Kickstart script configured the root user for key-based authentication.

1.  Find the client's IP address from your DHCP server's logs or by checking your router's client list.
2.  Connect using `ssh root@<client-ip-address>`.

On your first connection, you will see a message about the host's authenticity, which is normal.

```
The authenticity of host '192.168.1.165 (192.168.1.165)' can't be established.
ED25519 key fingerprint is SHA256:SPojjIMewEgwLMXtsuhjh+vi+RHuKwFgxBogFd8hNto.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Type `yes` and press Enter. This saves the new server's public key to your `known_hosts` file and allows the connection to proceed. If your SSH key was correctly placed in the `/var/www/html/ks/authorized_keys` file on the PXE server, you will be logged in without a password.


## 故障排查指南

### 常见问题及解决方案

| 问题现象 | 可能原因 | 解决方案 |
|---------|----------|----------|
| 客户端无法获取IP | DHCP服务未运行或防火墙阻挡 | 检查isc-dhcp-server/isc-dhcp-server6状态和ufw规则 |
| 获取IP后无法启动 | TFTP服务未运行或文件路径错误 | 检查tftpd-hpa状态和/var/lib/tftpboot内容 |
| 启动后找不到Kickstart文件 | HTTP服务问题 | 检查apache2状态和/var/www/html/ks/内容 |
| Kickstart安装失败 | 语法错误 | 验证Kickstart文件语法 |

### 诊断命令


```bash
查看服务状态

systemctl status isc-dhcp-server
systemctl status isc-dhcp-server6

systemctl status tftpd-hpa

systemctl status apache2

查看日志

journalctl -u isc-dhcp-server -f
journalctl -u isc-dhcp-server6 -f

journalctl -u tftpd-hpa -f

tail -f /var/log/apache2/access.log

网络测试

curl -g http://[fd00:1234:5678:1::10]/ks/centos9-ks.cfg
```


## 附录

### 安全建议
1. 生产环境中使用加密密码
2. 配置防火墙限制访问
3. 定期更新系统补丁
4. 监控服务运行状态

### 性能优化建议
1. 使用本地镜像源提高下载速度
2. 配置合适的DHCP租约时间
3. 优化Kickstart安装包选择
4. 使用高速存储存放安装文件

### 扩展功能
1. 支持多版本操作系统安装
2. 添加硬件检测功能
3. 实现安装进度监控
4. 集成系统配置管理

---

**文档结束**


保存方法

您可以选择以下任一方式保存此文件：

方法1：直接复制保存

1. 复制上面的全部内容

2. 打开文本编辑器（如VS Code、Notepad++、Sublime Text等）

3. 粘贴内容

4. 保存为 centos9-pxe-setup-guide.md

方法2：使用命令行保存（Linux/Mac）

# 将内容保存到文件
```bash
cat > centos9-pxe-setup-guide.md << 'EOF'
[在此处粘贴上面的全部内容]
EOF
```


方法3：在服务器上直接创建

如果您想在服务器上直接创建这个文件：

```bash
# 连接到您的服务器
ssh username@server-ip

# 创建并编辑文件
vim centos9-pxe-setup-guide.md
```

# 按 i 进入插入模式，粘贴内容，然后按 ESC，输入 :wq 保存退出


转换为PDF

保存为Markdown文件后，您可以使用以下方法转换为PDF：

使用Pandoc（推荐）

```bash
pandoc centos9-pxe-setup-guide.md -o centos9-pxe-setup-guide.pdf
```


使用VS Code

1. 安装"Markdown PDF"扩展

2. 右键Markdown文件选择"Markdown PDF: Export (pdf)"

在线转换工具

• 访问 markdown-pdf.com

• 或使用其他在线Markdown转PDF服务

这个文档包含了完整的配置指南，可以直接用于实际部署。
