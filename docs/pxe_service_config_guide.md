# CentOS Stream 9 PXE Automated Installation on a Single Ubuntu Server

## Document Information
- **Document Version**: 2.0
- **Creation Date**: December 2025
- **Applicable Environment**: Test/Production Environment
- **Operating System**: Ubuntu Server + CentOS Stream 9(Client)

## Table of Contents
- [CentOS Stream 9 PXE Automated Installation on a Single Ubuntu Server](#centos-stream-9-pxe-automated-installation-on-a-single-ubuntu-server)
  - [Document Information](#document-information)
  - [Table of Contents](#table-of-contents)
  - [Environment Overview](#environment-overview)
    - [Server Role Assignment](#server-role-assignment)
    - [Network Configuration](#network-configuration)
  - [Ubuntu DHCP Server Configuration](#ubuntu-dhcp-server-configuration)
    - [Install DHCP Service](#install-dhcp-service)
    - [(文件名可能不同，请用 ls /etc/netplan/ 查看)](#文件名可能不同请用-ls-etcnetplan-查看)
- [全局配置](#全局配置)
- [IPv4 子网配置](#ipv4-子网配置)
- [全局配置](#全局配置-1)
- [IPv6 子网配置](#ipv6-子网配置)
- [查看所有日志](#查看所有日志)
    - [Configure Network Interface](#configure-network-interface)
    - [Configure Network Interface](#configure-network-interface-1)
    - [Configure DHCP Service](#configure-dhcp-service)
    - [Assigning Static IP Addresses (Optional)](#assigning-static-ip-addresses-optional)
    - [Configure DHCPv6 Service](#configure-dhcpv6-service)
    - [Create the DHCPv6 Clients Include File, this file is managed by the PXE Control API.](#create-the-dhcpv6-clients-include-file-this-file-is-managed-by-the-pxe-control-api)
    - [Start DHCP Service](#start-dhcp-service)
  - [Ubuntu TFTP/HTTP Server Configuration](#ubuntu-tftphttp-server-configuration)
    - [Install Necessary Packages](#install-necessary-packages)
    - [Configure TFTP Service](#configure-tftp-service)
    - [Configure HTTP Service](#configure-http-service)
    - [Prepare Installation Files](#prepare-installation-files)
  - [PXE Boot Menu Configuration (for legacy BIOS)](#pxe-boot-menu-configuration-for-legacy-bios)
  - [GRUB2 Boot Menu Configuration (for UEFI)](#grub2-boot-menu-configuration-for-uefi)
- [Kickstart Automated Installation Configuration](#kickstart-automated-installation-configuration)
    - [Create the kiskstart file](#create-the-kiskstart-file)
  - [PXE Boot Control API (Optional)](#pxe-boot-control-api-optional)
    - [1. Install Dependencies](#1-install-dependencies)
    - [2. Create the API Script](#2-create-the-api-script)
    - [3. Create the systemd Service](#3-create-the-systemd-service)
    - [4. Enable and Start the Service](#4-enable-and-start-the-service)
    - [5. How to Use the New Workflow](#5-how-to-use-the-new-workflow)
        - [Run the command:](#run-the-command)
        - [Run the command:](#run-the-command-1)
    - [6. Client Management Tool (Optional)](#6-client-management-tool-optional)
      - [Create the `pxe-client-manager` Script](#create-the-pxe-client-manager-script)
      - [How to Use the Management Tool](#how-to-use-the-management-tool)
  - [Service Startup and Verification](#service-startup-and-verification)
    - [Start Services](#start-services)
    - [Configure Firewall](#configure-firewall)
    - [Verify Services](#verify-services)
  - [Client Installation Test](#client-installation-test)
  - [Troubleshooting Guide](#troubleshooting-guide)
  - [Appendix](#appendix)

## Environment Overview

### Server Role Assignment
| Server  | Operating System | IP Address   | Service Role               | Notes                            |
|---------|------------------|------------------------------------------|----------------------------|----------------------------------|
| Server1 | Ubuntu Server    | 192.168.1.2 / fd00\:1234\:5678:1::10       | DHCP + TFTP + HTTP Server  | All-in-one PXE server            |

### Network Configuration
- **IPv4 Network Segment**: 192.168.1.0/24
- **IPv4 Gateway**: 192.168.1.1
- **IPv4 DHCP Range**: 192.168.1.20-240
- **IPv6 Network Segment**: fd00\:1234\:5678:1::/64
- **IPv6 DHCP Range**: fd00\:1234\:5678:1::100 - fd00\:1234\:5678:1::200
- **DNS**: 8.8.8.8, 8.8.4.4, 2001:4860:4860::8888


## Ubuntu DHCP Server Configuration

### Install DHCP Service
配置 isc-dhcp-server 同时支持 IPv4 和 IPv6 (Dual Stack) 需要修改三个主要部分：静态 IP 配置、接口绑定配置、以及分别针对 v4 和 v6 的服务配置文件。

以下是针对网口 enp0s31f6 的完整命令行配置步骤。

环境假设
IPv4 网段: 192.168.10.0/24 (网关 IP: 192.168.10.1)

IPv6 网段: fd00::/64 (网关 IP: fd00::1) —— 这里使用内网唯一本地地址作为示例

第一步：配置静态 IP (IPv4 & IPv6)
DHCP 服务器必须在它服务的接口上拥有固定的 IPv4 和 IPv6 地址。

编辑 Netplan 配置文件：

Bash

sudo nano /etc/netplan/00-installer-config.yaml
### (文件名可能不同，请用 ls /etc/netplan/ 查看)
修改为如下内容（注意缩进）：

YAML

network:
  version: 2
  ethernets:
    enp0s31f6:
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.10.1/24
        - fd00::1/64
      nameservers:
         addresses: [8.8.8.8, 2001:4860:4860::8888]
应用配置：

Bash

sudo netplan apply
检查：运行 ip addr show enp0s31f6 确保你看到了两个 IP 地址。

第二步：安装并绑定接口
安装软件：

Bash

sudo apt update
sudo apt install isc-dhcp-server -y
指定监听接口：
编辑默认配置文件：

Bash

sudo nano /etc/default/isc-dhcp-server
修改以下两行，显式指定 enp0s31f6：

Bash

INTERFACESv4="enp0s31f6"
INTERFACESv6="enp0s31f6"
第三步：配置 IPv4 (dhcpd.conf)
备份并编辑：

Bash

sudo cp /etc/dhcp/dhcpd.conf /etc/dhcp/dhcpd.conf.bak
sudo nano /etc/dhcp/dhcpd.conf
在文件末尾添加 IPv4 配置：

Bash

# 全局配置
authoritative;
default-lease-time 600;
max-lease-time 7200;

# IPv4 子网配置
subnet 192.168.10.0 netmask 255.255.255.0 {
    range 192.168.10.50 192.168.10.150;
    option routers 192.168.10.1;
    option domain-name-servers 8.8.8.8, 114.114.114.114;
}
第四步：配置 IPv6 (dhcpd6.conf)
IPv6 的配置文件默认可能不存在或为空，需要单独配置。

创建/编辑 IPv6 配置文件：

Bash

sudo nano /etc/dhcp/dhcpd6.conf
填入以下 IPv6 配置：

Bash

# 全局配置
default-lease-time 600;
max-lease-time 7200;
log-facility local7;

# IPv6 子网配置
subnet6 fd00::/64 {
    # 分配范围
    range6 fd00::1000 fd00::2000;

    # 分配 DNS (Option 23)
    option dhcp6.name-servers 2001:4860:4860::8888;

    # 告知客户端该前缀可用于在链路上进行地址自动配置
    # 注意：IPv6 客户端通常通过 RA (Router Advertisement) 获取网关，
    # DHCPv6 此时主要负责分发 DNS 和其他信息 (Stateless) 或 IP (Stateful)。
}
创建 IPv6 租约文件（关键步骤）
如果这个文件不存在，IPv6 服务启动会报错。

Bash

sudo touch /var/lib/dhcp/dhcpd6.leases
sudo chown dhcpd:dhcpd /var/lib/dhcp/dhcpd6.leases
第五步：启动与排错
Ubuntu 的 isc-dhcp-server 服务脚本会自动检查 /etc/default/isc-dhcp-server 中的配置。如果你同时配置了 INTERFACESv4 和 INTERFACESv6，它会尝试启动两个守护进程。

重启服务：

Bash

sudo systemctl restart isc-dhcp-server
检查状态：

Bash

sudo systemctl status isc-dhcp-server
你应该看到 "active (running)"。

查看详细日志（如果启动失败）：
如果报错，请分协议查看日志：

Bash

# 查看所有日志
journalctl -u isc-dhcp-server -f
验证端口监听：
确认系统正在监听 IPv4 (UDP 67) 和 IPv6 (UDP 547) 端口：

Bash

sudo ss -ulnp | grep dhcp
你应该看到 dhcpd 进程同时出现在 udp 67 和 udp 547 上。

特别提示：IPv6 路由通告 (Router Advertisement)
在 IPv6 网络中，Android 等设备不使用 DHCPv6 获取 IP，只使用 SLAAC。Windows 和 iOS 支持 DHCPv6。
如果你发现客户端分配到了 IP 但没有默认网关，这是正常的。DHCPv6 协议本身不分发“默认网关”（Default Gateway）。
网关必须通过路由器通告 (RA) 分发。

如果是做完整的 IPv6 服务器，你通常还需要安装 radvd：

Bash

sudo apt install radvd
配置 /etc/radvd.conf 让它配合 DHCPv6 工作。

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

# Deny requests from all clients that are not explicitly defined in a 'host' block.
# This ensures only known devices can receive an IPv6 address.
deny unknown-clients;

option dhcp6.name-servers 2001:4860:4860::8888, 2001:4860:4860::8844;

subnet6 fd00:1234:5678:1::/64 {
    # This pool is only available to clients defined in 'host' blocks
    # that do not have a 'fixed-address6' specified.
    pool6 {
        range6 fd00:1234:5678:1::100 fd00:1234:5678:1::200;
        allow known-clients;
    }

    # For any known client, serve the GRUB bootloader for UEFI systems.
    # The client becomes "known" when the API adds its MAC to the include file.
    option dhcp6.bootfile-url "tftp://[fd00:1234:5678:1::10]/grubx64.efi";
}

# Include the file that will be dynamically managed by the pxe_api.py script.
# This file will contain the 'host' entries for clients enabled for installation.
include "/etc/dhcp/dhcpd6-clients.conf";
```
### Create the DHCPv6 Clients Include File, this file is managed by the PXE Control API.
Edit or create the file `/etc/dhcp/dhcpd6-clients.conf`:
```bash
sudo tee /etc/dhcp/dhcpd6-clients.conf
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

# Download the full CentOS Stream 9 DVD ISO. This file is large (~9GB).
sudo mkdir -p /opt/iso
cd /opt/iso
sudo wget https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/iso/CentOS-Stream-9-latest-x86_64-dvd1.iso -O centos9-dvd.iso

# Create a mount point and mount the ISO to serve it via HTTP
sudo mkdir -p /var/www/html/centos/9-stream/install
sudo mount -o loop /opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install

# To make the mount persistent across reboots, add it to /etc/fstab
echo "/opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install iso9660 loop 0 0" | sudo tee -a /etc/fstab

# Copy kernel and initrd for all boot types
sudo cp /var/www/html/centos/9-stream/install/images/pxeboot/{vmlinuz,initrd.img} /var/lib/tftpboot/images/centos9/

# Copy UEFI boot files
sudo cp /var/www/html/centos/9-stream/install/EFI/BOOT/grubx64.efi /var/lib/tftpboot/

# Create the directory
sudo mkdir -p /var/www/html/centos/9-stream/custom/x86_64/

# Copy your custom RPM into it (replace with your actual RPM file)
sudo cp /path/to/my-custom-tool-1.0-1.el9.x86_64.rpm /var/www/html/centos/9-stream/custom/x86_64/
# Update the repository metadata
sudo createrepo_c --update /var/www/html/centos/9-stream/custom/x86_64/

# Verify that the files are accessible via HTTP
# This command should return a 200 OK status code and list directory contents.
curl -g http://192.168.1.2/centos/9-stream/BaseOS/x86_64/os/

echo "Local mirror creation complete."
```

## PXE Boot Menu Configuration (for legacy BIOS)

Create `/var/lib/tftpboot/pxelinux.cfg/default`:
```ini
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

```grub
set timeout=10

menuentry 'Automated CentOS Stream 9 Installation (UEFI)' {
    linuxefi images/centos9/vmlinuz ip=dhcp inst.repo=http://192.168.1.2/centos/9-stream/install inst.text inst.ks=http://192.168.1.2/ks/centos9-ks.cfg biosdevname=0 net.ifnames=0 inst.cmdline console=ttyS0,57600n8
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

### Create the kiskstart file

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

## PXE Boot Control API (Optional)

To prevent accidental reinstalls and provide a safe, on-demand way to provision servers, we will implement a simple web API. This API creates and deletes host-specific PXE configuration files, allowing you to enable or disable PXE booting for a client via a simple `curl` command.

### 1. Install Dependencies

First, install the necessary Python packages. We will also install `gunicorn`, a production-grade web server to run our Flask API.

```bash
# On your Ubuntu PXE server
sudo apt update
sudo apt install -y python3-flask gunicorn
```

### 2. Create the API Script

Create the Python script that will run the API. This script will handle requests to enable and disable PXE for specific MAC addresses.

```bash
sudo tee /var/lib/tftpboot/pxe_api.py > /dev/null <<'FLASK_APP'
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
# Ensure the log directory exists (it should be created by systemd via LogsDirectory)
os.makedirs(LOG_DIR, exist_ok=True)

# Set up a rotating file handler to prevent the log file from growing too large.
# This will create up to 5 backup files of 5MB each.
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
    """Restarts the isc-dhcp-server6 service to apply changes."""
    try:
        # Use systemctl to restart the service.
        subprocess.run(["systemctl", "restart", "isc-dhcp-server6"], check=True)
        app.logger.info("Successfully restarted isc-dhcp-server6.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        app.logger.error(f"Failed to restart isc-dhcp-server6: {e}")
        return False

# --- API Endpoints ---

@app.route("/clients", methods=["GET"])
def get_pxe_clients():
    """
    Returns a list of all clients currently enabled for PXE installation.
    """
    if not os.path.exists(DHCPD6_CLIENTS_FILE):
        return jsonify({"status": "success", "enabled_clients": []}), 200

    try:
        with open(DHCPD6_CLIENTS_FILE, "r") as f:
            content = f.read()

        # Regex to find all MAC addresses in 'hardware ethernet' lines.
        mac_regex = re.compile(r"hardware\s+ethernet\s+([0-9a-fA-F:]+);")
        enabled_clients = mac_regex.findall(content)

        app.logger.info(f"Found {len(enabled_clients)} enabled clients.")
        return jsonify({
            "status": "success",
            "enabled_clients": enabled_clients
        }), 200

    except Exception as e:
        app.logger.error(f"FAILURE: Could not read DHCP clients file: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/clients/<mac>/pxe", methods=["PUT"])
def set_pxe_install(mac: str):
    """
    Adds a client to the known-clients list in DHCPv6 to enable installation.
    """
    mac = mac.lower()
    if not is_valid_mac(mac):
        return jsonify({"status": "error", "message": "Invalid MAC address format."}), 400

    # Normalize MAC to use colons for dhcpd.conf syntax and create the host entry.
    mac_with_colons = mac.lower().replace("-", ":")
    # Create the host entry. We don't need a fixed IP; it can get one from the pool.
    host_entry = f'\nhost install-client-{mac_with_colons.replace(":", "-")} {{\n  hardware ethernet {mac_with_colons};\n}}\n'

    try:
        # Read current clients to avoid duplicates
        if os.path.exists(DHCPD6_CLIENTS_FILE):
            with open(DHCPD6_CLIENTS_FILE, "r") as f:
                content = f.read()
            if mac_with_colons in content:
                app.logger.info(f"Client {mac} already in install list. No changes made.")
                return jsonify({"status": "success", "message": "Client already enabled for install."}), 200

        # Append the new host entry
        with open(DHCPD6_CLIENTS_FILE, "a") as f:
            f.write(host_entry)

        app.logger.info(f"SUCCESS: Added {mac_with_colons} to DHCPv6 install list.")

        # Apply the changes by restarting DHCP
        if not restart_dhcp_service():
            return jsonify({"status": "error", "message": "Failed to restart DHCPv6 service."}), 500

        return jsonify({
            "status": "success",
            "mode": "install",
            "mac": mac,
            "message": f"Client {mac} enabled for PXE install. DHCPv6 service restarted."
        }), 201

    except Exception as e:
        app.logger.error(f"FAILURE: Could not set install mode for MAC {mac}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/clients/<mac>/pxe", methods=["DELETE"])
def set_pxe_localboot(mac: str):
    """
    Removes a client from the DHCPv6 known-clients list to enforce local boot.
    """
    mac = mac.lower()
    if not is_valid_mac(mac):
        return jsonify({"status": "error", "message": "Invalid MAC address format."}), 400

    if not os.path.exists(DHCPD6_CLIENTS_FILE):
        app.logger.info(f"DHCP clients file not found. Assuming {mac} is already disabled.")
        return jsonify({"status": "success", "mode": "localboot", "mac": mac}), 200

    try:
        with open(DHCPD6_CLIENTS_FILE, "r") as f:
            lines = f.readlines()

        # Create a regex to find the entire host block for the given MAC
        # This handles variations in whitespace and comments.
        # The `\s*` at the beginning and end will consume surrounding whitespace, including newlines.
        mac_with_hyphens = mac.lower().replace(":", "-")
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
            app.logger.info(f"INFO: MAC {mac} not found in DHCPv6 install list. No changes made.")

        return jsonify({
            "status": "success",
            "mode": "localboot",
            "mac": mac,
            "message": f"Client {mac} disabled from PXE install. DHCPv6 service restarted."
        }), 200

    except (IOError, OSError) as e:
        app.logger.error(f"FAILURE: Could not delete config for MAC {mac}: {e}")
        return jsonify({"status": "error", "message": f"Error deleting file: {e}"}), 500

# --- Main Execution ---

if __name__ == '__main__':
    # For production, use a proper WSGI server like Gunicorn or uWSGI.
    # The built-in Flask server is being used as requested.
    app.run(host='0.0.0.0', port=5001, debug=False)
FLASK_APP
```

### 3. Create the systemd Service

Create a service file to ensure the API runs automatically on boot.

```bash
sudo tee /etc/systemd/system/pxe-control.service > /dev/null <<'EOF'
[Unit]
Description=PXE Boot Control API Service
After=network.target

[Service]
User=root
Group=root
# Run the Flask application directly with Python.
# The built-in server is not recommended for heavy production use but is simpler.
ExecStart=/usr/bin/python3 /var/lib/tftpboot/pxe_api.py
Restart=always
# systemd will create and manage the log directory and its permissions
LogsDirectory=pxe_api

[Install]
WantedBy=multi-user.target
EOF
```

### 4. Enable and Start the Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pxe-control.service
sudo systemctl status pxe-control.service
```
### 5. How to Use the New Workflow
1. Log in to your Ubuntu PXE server.
2. Enable PXE for a Client: This single command will now create both the BIOS and UEFI config files.

##### Run the command:
```bash
curl -X PUT http://192.168.1.2:5001/clients/88-5a-23-34-0d-65/pxe
```

Expected Output:
```json
{
    "mac": "88:5a:23:34:0d:65",
    "message": "Client 88:5a:23:34:0d:65 enabled for PXE install. DHCPv6 service restarted.",
    "mode": "install",
    "status": "success"
}
```

1. Disable PXE for a Client: This command will now move both files to the disabled directory.
##### Run the command:
```bash
curl -X DELETE http://192.168.1.2:5001/clients/88-5a-23-34-0d-65/pxe
```

### 6. Client Management Tool (Optional)

To simplify the process of enabling and disabling clients, you can use the following management script. This tool provides a more intuitive command-line interface.

#### Create the `pxe-client-manager` Script

Create the following script on your PXE server, for example at `/usr/local/sbin/pxe-client-manager`.

```bash
sudo tee /usr/local/sbin/pxe-client-manager > /dev/null <<'SCRIPT'
#!/bin/bash

# A simple tool to manage PXE boot settings for clients via the PXE Control API.

# --- Configuration ---
API_SERVER="http://127.0.0.1:5001"

# --- Helper Functions ---
usage() {
    echo "Usage: $(basename "$0") <command> <mac_address | --file /path/to/mac_file>"
    echo
    echo "Commands:"
    echo "  add, enable      Enable PXE installation for the client."
    echo "  del, disable     Disable PXE installation for the client (enforce local boot)."
    echo "  status, list     Show a list of all clients currently enabled for PXE boot."
    echo
    echo "Options:"
    echo "  -f, --file       Perform the action on a list of MAC addresses from a file."
    echo
    echo "Examples:"
    echo "  # Single client"
    echo "  $(basename "$0") add 88:5a:23:34:0d:65"
    echo
    echo "  # Bulk operation from a file"
    echo "  $(basename "$0") add --file ./mac_list.txt"
}

# --- Main Script Logic ---

if [ "$#" -lt 1 ]; then
    usage
    exit 1
fi

COMMAND=$(echo "$1" | tr '[:upper:]' '[:lower:]')
# Function to perform the API call for a single MAC
perform_action() {
    local mac=$1
    local cmd=$2
    local http_method=""

    if ! [[ $mac =~ ^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$ ]]; then
        echo "Warning: Skipping invalid MAC address format: '$mac'" >&2
        return
    fi

    case "$cmd" in
        add|enable) http_method="PUT" ;;
        del|disable) http_method="DELETE" ;;
    esac

    echo "-> Processing ${mac}..."
    curl -s -X "${http_method}" "${API_SERVER}/clients/${mac}/pxe" | python3 -m json.tool
}

case "$COMMAND" in
    add|enable|del|disable)
        if [ "$#" -ne 2 ] && [ "$#" -ne 3 ]; then usage; exit 1; fi

        if [ "$2" == "-f" ] || [ "$2" == "--file" ]; then
            if [ "$#" -ne 3 ]; then echo "Error: File path is missing." >&2; usage; exit 1; fi
            MAC_FILE=$3
            if [ ! -f "$MAC_FILE" ]; then
                echo "Error: File not found: $MAC_FILE" >&2
                exit 1
            fi
            echo "Performing bulk operation from file: $MAC_FILE"
            # Read file, ignore comments and empty lines
            grep -v -e '^#' -e '^[[:space:]]*$' "$MAC_FILE" | while IFS= read -r mac_address; do
                # Trim whitespace from the line
                mac_address=$(echo "$mac_address" | xargs)
                perform_action "$mac_address" "$COMMAND"
            done
            echo "Bulk operation complete."
        else
            if [ "$#" -ne 2 ]; then usage; exit 1; fi
            perform_action "$2" "$COMMAND"
        fi
    ;;
    status|list)
        if [ "$#" -ne 1 ]; then echo "Error: 'status' command does not take additional arguments." >&2; usage; exit 1; fi
        echo "Querying server for enabled PXE clients..."
        response=$(curl -s -X GET "${API_SERVER}/clients")
        if ! echo "$response" | python3 -m json.tool > /dev/null 2>&1; then
            echo "Error: Failed to get a valid JSON response from the API server." >&2
        fi
        echo "$response" | python3 -m json.tool
    ;;
    *)
        echo "Error: Unknown command '$COMMAND'" >&2
        usage
        exit 1
        ;;
esac
SCRIPT

# Make the script executable
sudo chmod +x /usr/local/sbin/pxe-client-manager
```

#### How to Use the Management Tool

**To enable PXE install for a client:**
```bash
# For a single client
sudo pxe-client-manager add 88:5a:23:34:0d:65

# For multiple clients from a file
sudo pxe-client-manager add --file /path/to/mac_list.txt
```

**To disable PXE install for a client:**
```bash
sudo pxe-client-manager del 88:5a:23:34:0d:65
```

## Service Startup and Verification

### Start Services


```bash
# On the Ubuntu Server
sudo systemctl restart isc-dhcp-server
sudo systemctl restart isc-dhcp-server6
sudo systemctl restart tftpd-hpa
sudo systemctl restart apache2
sudo systemctl restart pxe-control.service


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
sudo ufw allow 5001/tcp   # PXE Control API (Port 5001)
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