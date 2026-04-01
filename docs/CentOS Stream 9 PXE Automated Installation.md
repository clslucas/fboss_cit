# CentOS Stream 9 PXE Automated Installation Guide (All-in-One CentOS Server)

## Document Information
- **Document Version**: 3.0 (CentOS Native Edition)
- **Applicable Environment**: Test/Production Environment
- **Operating System**: CentOS Stream 9 (Server) + CentOS Stream 9 (Client)

## Table of Contents
- [CentOS Stream 9 PXE Automated Installation Guide (All-in-One CentOS Server)](#centos-stream-9-pxe-automated-installation-guide-all-in-one-centos-server)
  - [Document Information](#document-information)
  - [Table of Contents](#table-of-contents)
  - [Environment Overview](#environment-overview)
    - [Server Role Assignment](#server-role-assignment)
    - [Network Configuration](#network-configuration)
  - [Server Network Configuration](#server-network-configuration)
  - [Install Necessary Packages](#install-necessary-packages)
  - [DHCP Server Configuration (IPv4 \& IPv6)](#dhcp-server-configuration-ipv4--ipv6)
    - [1. Configure IPv4 (`/etc/dhcp/dhcpd.conf`)](#1-configure-ipv4-etcdhcpdhcpdconf)
    - [2. Configure IPv6 (`/etc/dhcp/dhcpd6.conf`)](#2-configure-ipv6-etcdhcpdhcpd6conf)
    - [3. Create the Managed Include File](#3-create-the-managed-include-file)
  - [TFTP \& HTTP Server Configuration](#tftp--http-server-configuration)
    - [1. Prepare HTTP Directories](#1-prepare-http-directories)
    - [2. Mount CentOS Stream 9 ISO](#2-mount-centos-stream-9-iso)
    - [3. Prepare TFTP Directories and Boot Files](#3-prepare-tftp-directories-and-boot-files)
  - [PXE \& GRUB2 Boot Menu Configuration](#pxe--grub2-boot-menu-configuration)
    - [UEFI Boot Menu (`/var/lib/tftpboot/grub.cfg`)](#uefi-boot-menu-varlibtftpbootgrubcfg)
  - [Kickstart Automated Installation Configuration](#kickstart-automated-installation-configuration)
  - [PXE Boot Control API (Optional but Recommended)](#pxe-boot-control-api-optional-but-recommended)
    - [1. Create the API Script](#1-create-the-api-script)
    - [2. Create the Systemd Service](#2-create-the-systemd-service)
  - [Service Startup, Firewall \& SELinux](#service-startup-firewall--selinux)
    - [1. Configure SELinux Policies](#1-configure-selinux-policies)
    - [2. Configure Firewalld](#2-configure-firewalld)
    - [3. Start and Enable Services](#3-start-and-enable-services)
  - [Client Management Tool](#client-management-tool)
    - [Usage](#usage)

## Environment Overview

### Server Role Assignment
| Server  | Operating System  | IP Address                            | Service Role                | Notes                 |
|---------|-------------------|---------------------------------------|-----------------------------|-----------------------|
| Server1 | CentOS Stream 9   | 192.168.1.2 / fd00:1234:5678:1::10    | DHCP + TFTP + HTTP + API    | All-in-one PXE server |

### Network Configuration
- **IPv4 Network**: 192.168.1.0/24 (Gateway: 192.168.1.1, DHCP Range: .100 - .200)
- **IPv6 Network**: fd00:1234:5678:1::/64 (DHCP Range: ::100 - ::200)
- **DNS**: 8.8.8.8, 8.8.4.4, 2001:4860:4860::8888

## Server Network Configuration

In CentOS Stream 9, use `nmcli` to configure static IP addresses for your network interface (assuming `eno3`).

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

## Install Necessary Packages

Install the required services using `dnf`.

```bash
sudo dnf update -y
sudo dnf install -y dhcp-server tftp-server httpd syslinux syslinux-tftpboot wget createrepo_c python3-flask python3-gunicorn
```

## DHCP Server Configuration (IPv4 & IPv6)

### 1. Configure IPv4 (`/etc/dhcp/dhcpd.conf`)
Edit the IPv4 DHCP configuration to serve IP addresses and the appropriate boot file (BIOS or UEFI).

```bash
sudo nano /etc/dhcp/dhcpd.conf
```

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

### 2. Configure IPv6 (`/etc/dhcp/dhcpd6.conf`)
Configure DHCPv6 to only assign IPs and boot files to known clients.

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

# Include dynamic managed file
include "/etc/dhcp/dhcpd6-clients.conf";
```

### 3. Create the Managed Include File

```bash
sudo touch /etc/dhcp/dhcpd6-clients.conf
sudo chown dhcpd:dhcpd /etc/dhcp/dhcpd6-clients.conf
```

## TFTP & HTTP Server Configuration

### 1. Prepare HTTP Directories

```bash
sudo mkdir -p /var/www/html/ks
sudo mkdir -p /var/www/html/centos/9-stream/install
```

### 2. Mount CentOS Stream 9 ISO

```bash
sudo mkdir -p /opt/iso
cd /opt/iso
# Download the ISO
sudo wget https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/iso/CentOS-Stream-9-latest-x86_64-dvd1.iso -O centos9-dvd.iso

# Mount it to the HTTP directory
sudo mount -o loop /opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install

# Make it persistent
echo "/opt/iso/centos9-dvd.iso /var/www/html/centos/9-stream/install iso9660 loop 0 0" | sudo tee -a /etc/fstab
```

### 3. Prepare TFTP Directories and Boot Files

```bash
sudo mkdir -p /var/lib/tftpboot/images/centos9

# Copy Kernel and Initrd
sudo cp /var/www/html/centos/9-stream/install/images/pxeboot/{vmlinuz,initrd.img} /var/lib/tftpboot/images/centos9/

# Copy UEFI boot file
sudo cp /var/www/html/centos/9-stream/install/EFI/BOOT/grubx64.efi /var/lib/tftpboot/
```

## PXE & GRUB2 Boot Menu Configuration

### UEFI Boot Menu (`/var/lib/tftpboot/grub.cfg`)

This menu is for modern UEFI clients.

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

## Kickstart Automated Installation Configuration

Create the automated configuration file for the client.

```bash
sudo nano /var/www/html/ks/centos9-ks.cfg
```

> **Note:** Paste the exact Kickstart content from the Ubuntu server guide. The partitioning, packages, and `%pre`/`%post` scripts are fully compatible with CentOS Stream 9.
>
> The following lines inside the `%post` script should be verified, but are expected to be correct:
> - `API_PORT="5001"`
> - `PXE_SERVER_IP="${SERVER_IP}"`

## PXE Boot Control API (Optional but Recommended)

This API manages the `/etc/dhcp/dhcpd6-clients.conf` file to dynamically enable/disable PXE installations.

### 1. Create the API Script

```bash
sudo nano /var/lib/tftpboot/pxe_api.py
```

> **Note:** Paste the Python API script from the Ubuntu server guide.
>
> **Crucial Update for CentOS:** Ensure the `restart_dhcp_service()` function uses `dhcpd6` instead of `isc-dhcp-server6`.
>
> ```python
> # pxe_api.py (snippet)
> def restart_dhcp_service():
>     """Restarts the DHCPv6 service to apply changes."""
>     try:
>         # Changed for CentOS Stream 9
>         subprocess.run(["systemctl", "restart", "dhcpd6"], check=True)
>         app.logger.info("Successfully restarted dhcpd6.")
>         return True
>     except (subprocess.CalledProcessError, FileNotFoundError) as e:
>         app.logger.error(f"Failed to restart dhcpd6: {e}")
>         return False
> ```

### 2. Create the Systemd Service

```bash
sudo nano /etc/systemd/system/pxe-control.service
```

```ini
[Unit]
Description=PXE Boot Control API Service
After=network.target

[Service]
User=root
Group=root
ExecStart=/usr/bin/python3 /var/lib/tftpboot/pxe_api.py
Restart=always
LogsDirectory=pxe_api

[Install]
WantedBy=multi-user.target
```

## Service Startup, Firewall & SELinux

### 1. Configure SELinux Policies
CentOS enforces SELinux by default. You must ensure HTTP and TFTP can read the files:

```bash
sudo restorecon -Rv /var/lib/tftpboot/
sudo restorecon -Rv /var/www/html/
```

### 2. Configure Firewalld

```bash
sudo firewall-cmd --permanent --add-service=dhcp
sudo firewall-cmd --permanent --add-service=dhcpv6
sudo firewall-cmd --permanent --add-service=tftp
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-port=5001/tcp
sudo firewall-cmd --reload
```

### 3. Start and Enable Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dhcpd
sudo systemctl enable --now dhcpd6
sudo systemctl enable --now tftp.socket
sudo systemctl enable --now httpd
sudo systemctl enable --now pxe-control.service
```

## Client Management Tool

To interact with your API easily, create the CLI manager.

```bash
sudo nano /usr/local/sbin/pxe-client-manager
```

> **Note:** Paste the `pxe-client-manager` bash script from the Ubuntu server guide.

Make it executable:

```bash
sudo chmod +x /usr/local/sbin/pxe-client-manager
```

### Usage

```bash
# Enable a client for PXE installation
sudo pxe-client-manager add 88:5a:23:34:0d:65

# Disable PXE installation for a client
sudo pxe-client-manager del 88:5a:23:34:0d:65
```