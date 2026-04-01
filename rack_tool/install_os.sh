#!/bin/bash
set -euo pipefail

# --- Function to check for required commands ---
check_dependencies() {
  local missing_deps=0
  # List of critical commands this script relies on
  local deps=(
    "dnf"
    "grub2-set-default"
    "grub2-mkconfig"
    "systemctl"
    "passwd"
    "tar"
  )

  echo ">>> Checking for required tools..."
  for cmd in "${deps[@]}"; do
    if ! command -v "$cmd" &> /dev/null; then
      echo "Error: Required command '$cmd' not found. Please ensure it is installed and in your PATH."
      missing_deps=$((missing_deps + 1))
    fi
  done

  if [ "$missing_deps" -gt 0 ]; then
    echo "Aborting due to missing dependencies."
    exit 1
  fi
  echo "All required tools are present."
}

# --- Function to copy a file and optionally set its permissions ---
install_file() {
    local src="$1"
    local dest="$2"
    local perms="${3:-}" # Optional: permissions. Default to empty string if not provided.
    local filename
    filename=$(basename "$src")

    echo ">>> Installing '${filename}' to '${dest}'..."
    if [ ! -f "$src" ]; then
        # Construct the remote URL, preserving the source directory structure.
        REMOTE_URL="${SERVER_URL}/custom-files/${src#./}" # Removes leading './'
        TEMP_FILE=$(mktemp)
        echo "--> Local file not found: $src. Attempting to download from ${REMOTE_URL}..."

        # Use curl to download the file, checking the HTTP status code
        HTTP_STATUS=$(curl -s -o "$TEMP_FILE" -w "%{http_code}" "$REMOTE_URL")

        if [ "$HTTP_STATUS" -eq 200 ]; then
            echo "--> Download successful. Installing from temporary file."
            cp -f "$TEMP_FILE" "${dest}/${filename}"
            rm -f "$TEMP_FILE"
        else
            echo "Warning: Failed to download from ${REMOTE_URL} (HTTP status: ${HTTP_STATUS}). Skipping installation."
            rm -f "$TEMP_FILE"
            return 0
        fi
    else
        cp -f "$src" "${dest}/${filename}"
    fi

    # Set permissions if provided
    [ -n "$perms" ] && chmod "$perms" "${dest}/${filename}"

    # Explicitly return 0 to signal success and prevent set -e from exiting
    return 0
}

echo "Upgrade kernel and install tools..."
KERNEL_VERSION="$1"
REPO_SOURCE="${2:-}" # Second argument is the optional repo source

if [ -z "$KERNEL_VERSION" ]; then
  echo "Error: Please provide a kernel version as an argument."
  echo "Supported kernel versions are: 6.4.3, 6.11.1"
  exit 1
else
  # Check if the provided kernel version is supported
  if [[ "$KERNEL_VERSION" != "6.4.3" && "$KERNEL_VERSION" != "6.11.1" ]]; then
    echo "Error: Unsupported kernel version provided."
    echo "Supported kernel versions are: 6.4.3, 6.11.1"
    exit 1
  fi
fi

# Run the dependency check before proceeding
check_dependencies

# --- Dynamic Repository Configuration ---
echo "Configuring DNF repositories..."

if [ -n "$REPO_SOURCE" ]; then
    echo "Using repository source provided via command-line argument: $REPO_SOURCE"
    # If the source is a local path (e.g., /mnt), prepend 'file://'
    if [[ "$REPO_SOURCE" == /* ]]; then
        BASE_URL_BASEOS="file://${REPO_SOURCE}/BaseOS"
        BASE_URL_APPSTREAM="file://${REPO_SOURCE}/AppStream"
    else
        # Assume it's an HTTP URL
        BASE_URL_BASEOS="${REPO_SOURCE}/BaseOS"
        BASE_URL_APPSTREAM="${REPO_SOURCE}/AppStream"
    fi
else
    echo "No repository source provided. Using default network repository."
    BASE_URL_BASEOS="http://192.168.1.2/centos/9-stream/install/BaseOS"
    BASE_URL_APPSTREAM="http://192.168.1.2/centos/9-stream/install/AppStream"
fi

# Clean up any old repo configurations
echo "Backing up old repository configurations if they exist..."
rm -f /etc/yum.repos.d/cdrom.repo
# Only move the files if they exist to prevent errors
[ -f /etc/yum.repos.d/centos-addons.repo ] && mv /etc/yum.repos.d/centos-addons.repo /etc/yum.repos.d/centos-addons.repo.bak
[ -f /etc/yum.repos.d/centos.repo ] && mv /etc/yum.repos.d/centos.repo /etc/yum.repos.d/centos.repo.bak
sync

echo "Determining kernel RPM source URL..."
# Extract the base server URL (e.g., http://192.168.1.2) from the AppStream URL
SERVER_URL=$(echo "${BASE_URL_APPSTREAM}" | sed -E 's|/centos/9-stream/install/AppStream/?$||')
KERNEL_RPM_URL_BASE="${SERVER_URL}/custom-files/kernel"

# Create a new repo file pointing to the detected or default server
cat > /etc/yum.repos.d/network-install.repo << EOF
[network-install-baseos]
name=Network Install - BaseOS
baseurl=${BASE_URL_BASEOS}
enabled=1
gpgcheck=0

[network-install-appstream]
name=Network Install - AppStream
baseurl=${BASE_URL_APPSTREAM}
enabled=1
gpgcheck=0

[network-install-custom-kernel]
name=Network Install - Custom Kernel
baseurl=${KERNEL_RPM_URL_BASE}
enabled=1
gpgcheck=0

EOF


dnf clean all
dnf makecache

echo "Installing base tools..."
dnf install -y double-conversion dhclient expect libgpiod-utils i2c-tools iperf3 ipmitool python3-pip lm_sensors xxhash zstd stress-ng xxhash-libs lldpad

echo "Installing new kernel version $KERNEL_VERSION..."

# Check if local kernel files exist
if [ -f ./kernel/kernel-${KERNEL_VERSION}*.x86_64.rpm ]; then
    echo ">>> Found local kernel RPMs. Installing from local directory..."
    # Use dnf to install local RPMs. It handles dependencies better than rpm.
    # The --nogpgcheck flag prevents warnings about unsigned packages.
    dnf install -y --nogpgcheck \
        ./kernel/kernel-${KERNEL_VERSION}*.x86_64.rpm \
        ./kernel/kernel-devel-${KERNEL_VERSION}*.x86_64.rpm \
        ./kernel/kernel-headers-${KERNEL_VERSION}*.x86_64.rpm
else
    echo ">>> Local kernel RPMs not found. Attempting to install from remote repository: ${KERNEL_RPM_URL_BASE}"
    # Install by package name, letting DNF find the exact file from the repository metadata.
    # The package name doesn't include the full release string, just the base version.
    dnf install -y --nobest --nogpgcheck "kernel-${KERNEL_VERSION}" "kernel-devel-${KERNEL_VERSION}" "kernel-headers-${KERNEL_VERSION}"
fi

echo "Kernel-$KERNEL_VERSION is installed."

echo "Removing old, unused kernel packages..."
# Use dnf autoremove, which safely removes old kernels while keeping the
# currently running one and a configured number of previous versions.
dnf autoremove -y

grub2-set-default 0
grub2-mkconfig -o /boot/grub2/grub.cfg

echo ">>> Configuring system files and installing tools..."
rm -rf /etc/rc.d/rc.local
install_file ./config/rc.local /etc/rc.d/ "+x"
install_file ./VERSION /etc/
install_file ./config/.bashrc /root/
install_file ./config/fb.sh /etc/rc.d/ "+x"

echo "Configure usb0..."
install_file ./config/ifcfg-usb0 /etc/sysconfig/network-scripts/

echo "Configure eth0..."
# Dynamically generate the Vendor Class Identifier from hardware details.
# The 'dmidecode' command should be available from the base installation.
PRODUCT_NAME=$(dmidecode -s system-product-name | tr -d '[:space:]' || echo "UnknownProduct")

# Combine them into a single identifier string, e.g., "ProLiantDL360Gen10:a1:b2:c3:d4:e5:f6"
VENDOR_ID="CentOS9:model=${PRODUCT_NAME}:serial="

# Create the ifcfg-eth0 file with the dynamic DHCP option
cat > /etc/sysconfig/network-scripts/ifcfg-eth0 << EOF
DEVICE=eth0
BOOTPROTO=dhcp
ONBOOT=yes
TYPE=Ethernet
USERCTL=no
PEERDNS=yes
IPV6INIT=no
DHCP_VENDOR_CLASS_IDENTIFIER="${VENDOR_ID}"
EOF

install_file ./config/serial-getty@.service /usr/lib/systemd/system/
install_file ./bin/eeupdate64e /usr/local/bin/ "+x"
install_file ./bin/decode-dimms /usr/local/bin/ "+x"
install_file ./bin/flashrom /usr/bin/ "+x"
install_file ./config/sshd_config /etc/ssh/

echo ">>> Installing additional local/remote RPM packages..."

declare -a RPM_PATHS=(
    "./stressapp/stressapptest-1.0.9-1.20220222git6714c57.el9.x86_64.rpm"
    "./devmem/d_devmem2-1.0-17.43.x86_64.rpm"
    "./unwind/libunwind-1.2-2.el7.x86_64.rpm"
)

declare -a RPMS_TO_INSTALL=()

for rpm_path in "${RPM_PATHS[@]}"; do
    if [ -f "$rpm_path" ]; then
        echo "--> Found local RPM: $rpm_path"
        RPMS_TO_INSTALL+=("$rpm_path")
    else
        REMOTE_URL="${SERVER_URL}/custom-files/${rpm_path#./}"
        echo "--> Local RPM not found. Attempting to install from remote: ${REMOTE_URL}"
        RPMS_TO_INSTALL+=("${REMOTE_URL}")
    fi
done

if [ ${#RPMS_TO_INSTALL[@]} -gt 0 ]; then
    dnf install -y --nogpgcheck "${RPMS_TO_INSTALL[@]}"
else
    echo "--> No additional RPMs specified for installation."
fi

echo "Add mprime tool..."
MPRIME_TAR="./mprime/p95v3019b20.linux64.tar.gz"
if [ -f "$MPRIME_TAR" ]; then
    echo "--> Found local mprime tarball. Installing..."
    tar -xvf "$MPRIME_TAR" -C /usr/local/bin/
else
    REMOTE_URL="${SERVER_URL}/custom-files/${MPRIME_TAR#./}"
    echo "--> Local mprime tarball not found. Attempting to download from ${REMOTE_URL}..."
    curl -sL "${REMOTE_URL}" | tar -xvz -C /usr/local/bin/
fi

echo "Add i801 modprobe config..."
echo "options i2c-i801 disable_features=0x10" > /etc/modprobe.d/i2c-i801.conf

echo ">>> Finalizing system settings..."

echo "Deleting root password..."
passwd -d root

# --- Set a descriptive hostname ---
echo "Setting system hostname..."
if [ -f /etc/os-release ]; then
    # Source the os-release file to get variables like ID and VERSION_ID
    . /etc/os-release
    OS_ID="${ID:-linux}"
    OS_VERSION="${VERSION_ID:-}"
    
    # Get the MAC address of the first network interface (e.g., eth0)
    MAC_ADDR=$(cat /sys/class/net/eth0/address || echo "00:00:00:00:00:00")
    MAC_SUFFIX=$(echo "${MAC_ADDR}" | cut -d: -f4-6 | tr -d ':')

    # Construct and set the new hostname, e.g., "X86-centos9-445566"
    hostnamectl set-hostname "X86"
    hostnamectl set-hostname "${OS_ID}${OS_VERSION}-${MAC_SUFFIX:-unknown}" --pretty
fi

echo "Enabling lldpad service..."
systemctl enable lldpad

echo "##########All tools are installed, Please reboot system##########"
