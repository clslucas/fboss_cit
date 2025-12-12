#!/bin/bash
echo "upgarde kernel..."
set -euo pipefail

echo "Upgrade kernel and install tools..."

# Check if a kernel version is provided as an argument
if [ -z "$1" ]; then
  echo "Error: Please provide a kernel version as an argument."
  echo "Supported kernel versions are: 6.4.3, 6.11.1"
  exit 1
else
  # Check if the provided kernel version is supported
  if [[ "$1" == "6.4.3" || "$1" == "6.11.1" ]]; then
    echo "Kernel version $1 is supported."
  else
    echo "Error: Unsupported kernel version provided."
    echo "Supported kernel versions are: 6.4.3, 6.11.1"
    exit 1
  fi
fi

echo "Configuring DNF to use network repository..."
# Clean up any old repo configurations
rm -f /etc/yum.repos.d/cdrom.repo
mv /etc/yum.repos.d/centos-addons.repo /etc/yum.repos.d/centos-addons.repo.bak
mv /etc/yum.repos.d/centos.repo /etc/yum.repos.d/centos.repo.bak
sync

# Create a new repo file pointing to the network server
cat > /etc/yum.repos.d/network-install.repo << EOF
[network-install-baseos]
name=Network Install - BaseOS
baseurl=http://192.168.1.2/centos/9-stream/install/BaseOS/
enabled=1
gpgcheck=0

[network-install-appstream]
name=Network Install - AppStream
baseurl=http://192.168.1.2/centos/9-stream/install/AppStream/
enabled=1
gpgcheck=0

EOF



dnf clean all
dnf makecache

echo "Installing base tools..."
dnf install -y double-conversion dhclient expect libgpiod-utils i2c-tools iperf3 ipmitool python3-pip lm_sensors xxhash zstd stress-ng xxhash-libs lldpad

echo "Removing old kernel packages..."
# Use dnf to handle removal gracefully. The wildcard ensures all related 5.14 packages are targeted.
dnf remove -y --nobest 'kernel*5.14*'

echo "Installing new kernel version $1..."
# Use dnf to install local RPMs. It handles dependencies better than rpm.
# The --nogpgcheck flag prevents warnings about unsigned packages.
dnf install -y --nogpgcheck \
    ./kernel/kernel-$1*.x86_64.rpm \
    ./kernel/kernel-devel-$1*.x86_64.rpm \
    ./kernel/kernel-headers-$1*.x86_64.rpm

echo "Kernel-$1 is installed."

grub2-set-default 0
grub2-mkconfig -o /boot/grub2/grub.cfg

echo "update rc.local..."
rm -rf /etc/rc.d/rc.local
cp -rf ./config/rc.local /etc/rc.d/rc.local
chmod +x /etc/rc.d/rc.local

cp -rf VERSION /etc/

echo "delete root password..."
passwd -d root

echo "Setting up print product names..."
cp -rf ./config/.bashrc /root/ 

echo "Setting up fb script..."
cp -rf ./config/fb.sh /etc/rc.d/
chmod +x /etc/rc.d/fb.sh

echo "Configure usb0..."
cp -rf ./config/ifcfg-usb0 /etc/sysconfig/network-scripts/

echo "Configure eth0..."
# Create the ifcfg-eth0 file with DHCP options
# Replace "YourVendorString" with your actual Vendor Class Identifier
cat > /etc/sysconfig/network-scripts/ifcfg-eth0 << EOF
DEVICE=eth0
BOOTPROTO=dhcp
ONBOOT=yes
TYPE=Ethernet
USERCTL=no
PEERDNS=yes
IPV6INIT=no
DHCP_VENDOR_CLASS_IDENTIFIER="YourVendorString"
EOF

echo "set auto login..."
cp -rf ./config/serial-getty@.service /usr/lib/systemd/system/

echo "Add eeupdate tool..."
cp -rf ./bin/eeupdate64e /usr/local/bin/ 

echo "Add decode tool..."
cp -rf ./bin/decode-dimms /usr/local/bin/

echo "Add flashrom..."
cp -rf ./bin/flashrom /usr/bin/

echo "set ssh config..."
cp -rf ./config/sshd_config /etc/ssh/

echo "install stressapptest..."
dnf install -y --nogpgcheck ./stressapp/stressapptest-1.0.9-1.20220222git6714c57.el9.x86_64.rpm

echo "install devmem2..."
dnf install -y --nogpgcheck ./devmem/d_devmem2-1.0-17.43.x86_64.rpm

echo "install libunwind..."
dnf install -y --nogpgcheck ./unwind/libunwind-1.2-2.el7.x86_64.rpm


echo "Add mprime tool..."
tar -xvf ./mprime/p95v3019b20.linux64.tar.gz -C /usr/local/bin/

echo "Add i801 modprobe config..."
echo "options i2c-i801 disable_features=0x10" > /etc/modprobe.d/i2c-i801.conf

echo "Enabling lldpad service..."
systemctl enable lldpad

echo "##########All tools are installed, Please reboot system##########"
