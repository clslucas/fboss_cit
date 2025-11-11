#!/bin/bash

# --- Color Definitions ---
COLOR_GREEN='\033[0;32m'
COLOR_RED='\033[0;31m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m' # No Color

# --- Configuration ---
BUS_DEFAULT=10
ADDR_DEFAULT=0x23
# --- Pre-configured password (optional). If set, password prompts will be skipped.
# --- SECURITY WARNING: Hardcoding passwords in scripts is insecure. Use SSH keys if possible.
CONFIGURED_PASSWORD=""


# --- Remote Execution Globals ---
RMC_IP=""
W400_IP=""
REMOTE_USER=""
REMOTE_PASSWORD=""
SSH_OPTIONS="-T -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10"

# --- Helper Functions ---

# Function to check if a command exists
command_exists () {
    command -v "$1" >/dev/null 2>&1
}

# Function to execute a command on the remote target
run_remote() {
    local target_ip=$1
    local cmd_to_run=$2
    if [ -z "$target_ip" ] || [ -z "$REMOTE_USER" ]; then
        echo -e "${COLOR_RED}Error: Target IP and Remote User must be set for this operation.${COLOR_NC}"
        return 1
    fi
    if [ -n "$REMOTE_PASSWORD" ]; then
        # Use sshpass for non-interactive password authentication
        sshpass -p "$REMOTE_PASSWORD" ssh $SSH_OPTIONS "${REMOTE_USER}@${target_ip}" "$cmd_to_run"
    else
        # No pre-set password. Remove BatchMode to allow interactive password prompt from ssh itself.
        # This handles both key-based auth and interactive password auth.
        local interactive_ssh_options
        interactive_ssh_options=$(echo "$SSH_OPTIONS" | sed 's/-o BatchMode=yes//')
        ssh $interactive_ssh_options "${REMOTE_USER}@${target_ip}" "$cmd_to_run"
    fi
}

# Function to run RMC Status Check
run_rmc_status_check() {
    echo -e "${COLOR_BLUE}--- Running RMC Status Check ---${COLOR_NC}"
    # The script is expected to exist on the remote machine at this path.
    local remote_script_path="/home/root/rmc_status_check.sh"
    echo "Executing script on remote host: ${remote_script_path}"
    run_remote "$RMC_IP" "chmod +x ${remote_script_path} && ${remote_script_path} ${BUS_DEFAULT} ${ADDR_DEFAULT}"
    echo -e "${COLOR_BLUE}--- RMC Status Check Complete ---${COLOR_NC}"
    echo
}

# --- RMC Specific Functions ---

# Function to check AALC LC GPIO Cable Detect
check_aal_gpio_cable() {
    echo -e "${COLOR_BLUE}--- Checking AALC LC GPIO Cable Detect (RMC) ---${COLOR_NC}"
    echo -e "${COLOR_YELLOW}Reading register 0x13 from I2C device bus $BUS_DEFAULT at address $ADDR_DEFAULT:${COLOR_NC}"
    run_remote "$RMC_IP" "i2cget -y $BUS_DEFAULT $ADDR_DEFAULT 0x13"
    echo
}

# Function to check AALC RPU Ready status
check_aal_rpu_ready() {
    echo -e "${COLOR_BLUE}--- Checking AALC RPU Ready Status ---${COLOR_NC}"
    echo -e "${COLOR_YELLOW}Reading register 0x00 from I2C device bus $BUS_DEFAULT at address $ADDR_DEFAULT:${COLOR_NC}"
    run_remote "$RMC_IP" "i2cget -y $BUS_DEFAULT $ADDR_DEFAULT 0x00"
    echo -e "${COLOR_NC}Note: Refer to rmc_status_check.sh for bit interpretation (wRPU_READY_PLD_R, etc.).${COLOR_NC}"
    echo -e "${COLOR_BLUE}--- AALC RPU Ready Check Complete ---${COLOR_NC}"
    echo
}

# Function to check RMC version
check_rmc_version() {
    echo -e "${COLOR_BLUE}--- Checking RMC Software & Firmware Versions ---${COLOR_NC}"
    run_remote "$RMC_IP" "mfg-tool version-display"
    echo
}

# Function to check TH6 LC cable detect
check_th6_lc_cable() {
    echo -e "${COLOR_BLUE}--- Checking TH6 LC Cable Detect (RMC) ---${COLOR_NC}"
    echo -e "${COLOR_YELLOW}Reading registers 0x10, 0x11, 0x12:${COLOR_NC}"
    run_remote "$RMC_IP" "i2cget -f -y 10 0x23 0x10"
    run_remote "$RMC_IP" "i2cget -f -y 10 0x23 0x11"
    run_remote "$RMC_IP" "i2cget -f -y 10 0x23 0x12"
    echo
}

# Function to check Drip Pan leakage sensor cable present
check_drip_pan_leak_sensor() {
    echo -e "${COLOR_BLUE}--- Checking Drip Pan Leak Sensor Presence (RMC) ---${COLOR_NC}"
    echo -e "${COLOR_YELLOW}Reading registers 0x14, 0x15, 0x16:${COLOR_NC}"
    run_remote "$RMC_IP" "i2cget -y 10 0x23 0x14"
    run_remote "$RMC_IP" "i2cget -y 10 0x23 0x15"
    run_remote "$RMC_IP" "i2cget -y 10 0x23 0x16"
    echo
}

# Function to check RMC FRU info
check_rmc_fru_info() {
    echo -e "${COLOR_BLUE}--- Checking RMC FRU Information ---${COLOR_NC}"
    run_remote "$RMC_IP" "mfg-tool inventory"
    echo
}

# Function to check RMC sensor status
check_rmc_sensor_status() {
    echo -e "${COLOR_BLUE}--- Checking RMC Sensor Status ---${COLOR_NC}"
    run_remote "$RMC_IP" "mfg-tool sensor-display"
    echo
}

# Function to check RMC boot slot
check_rmc_boot_slot() {
    echo -e "${COLOR_BLUE}--- Checking RMC Boot Slot ---${COLOR_NC}"
    run_remote "$RMC_IP" "cat /run/media/slot"
    echo
}

# --- W400 Specific Functions ---

# Function to check PSU shelf Ishare Cable status
check_psu_ishare_cable() {
    echo -e "${COLOR_BLUE}--- Checking PSU Shelf Ishare Cable Status ---${COLOR_NC}"
    echo -e "${COLOR_YELLOW}Checking dev-addr 32:${COLOR_NC}"
    run_remote "$W400_IP" "rackmoncli data --dev-addr 32 --latest | grep -i ISHARE_Cable_Connected"
    echo -e "${COLOR_YELLOW}Checking dev-addr 33:${COLOR_NC}"
    run_remote "$W400_IP" "rackmoncli data --dev-addr 33 --latest | grep -i ISHARE_Cable_Connected"
    echo -e "${COLOR_BLUE}--- PSU Shelf Ishare Cable Check Complete ---${COLOR_NC}"
    echo
}

# Function to check BBU shelf Ishare Cable status
check_bbu_ishare_cable() {
    echo -e "${COLOR_BLUE}--- Checking BBU Shelf Ishare Cable Status ---${COLOR_NC}"
    echo -e "${COLOR_YELLOW}Checking dev-addr 16:${COLOR_NC}"
    run_remote "$W400_IP" "rackmoncli data --dev-addr 16 --latest | grep -i ISHARE_Cable_Connected"
    echo -e "${COLOR_YELLOW}Checking dev-addr 17:${COLOR_NC}"
    run_remote "$W400_IP" "rackmoncli data --dev-addr 17 --latest | grep -i ISHARE_Cable_Connected"
    echo -e "${COLOR_BLUE}--- BBU Shelf Ishare Cable Check Complete ---${COLOR_NC}"
    echo
}

# Function to check power source
check_power_source() {
    echo -e "${COLOR_BLUE}--- Checking Power Source Detect (W400) ---${COLOR_NC}"
    run_remote "$W400_IP" "rackmoncli list"
    echo
}

# Function to check Power AC loss cable detect
check_power_ac_loss() {
    echo -e "${COLOR_BLUE}--- Checking Power AC Loss Cable Detect (W400) ---${COLOR_NC}"
    #command rackmoncli data --dev-addr 48 --latest |grep -i  AC_Loss_; addresses 48 to 53 and 58 to 63
    for dev_addr in {48..53} {58..63}; do
        echo -e "${COLOR_YELLOW}Checking dev-addr ${dev_addr}:${COLOR_NC}"
        run_remote "$W400_IP" "rackmoncli data --dev-addr ${dev_addr} --latest | grep -i AC_Loss_"
    done
    echo -e "${COLOR_BLUE}--- Power AC Loss Cable Check Complete ---${COLOR_NC}"
    echo
}

# Function to check power Shelf Version
check_power_shelf_version() {
    echo -e "${COLOR_BLUE}--- Checking Power Shelf Version (W400) ---${COLOR_NC}"
    #command rackmoncli data --dev-addr 16 --latest |grep PMM_FW_Revision; addresses 16 17 32 33
    for dev_addr in 16 17 32 33; do
        echo -e "${COLOR_YELLOW}Checking dev-addr ${dev_addr}:${COLOR_NC}"
        run_remote "$W400_IP" "rackmoncli data --dev-addr ${dev_addr} --latest | grep PMM_FW_Revision"
    done
    echo -e "${COLOR_BLUE}--- Power Shelf Version Check Complete ---${COLOR_NC}"
    echo
}

# Function to check PSU and BBU versions
check_psu_bbu_versions() {
    echo -e "${COLOR_BLUE}--- Checking PSU and BBU Versions (W400) ---${COLOR_NC}"
    #command rackmoncli data --dev-addr 48 --latest |grep FW_Revision; addresses 48 to 53 and 58 to 63, 144 to 149 and 154 to 159
    for dev_addr in {48..53} {58..63} {144..149} {154..159}; do
        echo -e "${COLOR_YELLOW}Checking dev-addr ${dev_addr}:${COLOR_NC}"
        run_remote "$W400_IP" "rackmoncli data --dev-addr ${dev_addr} --latest | grep FW_Revision"
    done
    echo -e "${COLOR_BLUE}--- PSU and BBU Version Check Complete ---${COLOR_NC}"
    echo
}

# Function to check power FRU info
check_power_fru_info() {
    echo -e "${COLOR_BLUE}--- Checking Power FRU Info (W400) ---${COLOR_NC}"
    #command rackmoncli data --dev-addr 16 --latest; addresses 16 17 and from 144 to 149; 32 33 and from 154 to 159
    for dev_addr in 16 17 32 33; do
        echo -e "${COLOR_YELLOW}Checking dev-addr ${dev_addr}:${COLOR_NC}"
        run_remote "$W400_IP" "rackmoncli data --dev-addr ${dev_addr} --latest"
    done
    for dev_addr in {144..149} {154..159}; do
        echo -e "${COLOR_YELLOW}Checking dev-addr ${dev_addr}:${COLOR_NC}"
        run_remote "$W400_IP" "rackmoncli data --dev-addr ${dev_addr} --latest"
    done
    echo -e "${COLOR_BLUE}--- Power FRU Info Check Complete ---${COLOR_NC}"
    echo
}

# Function to check W400 versions
check_w400_versions() {
    echo -e "${COLOR_BLUE}--- Checking Wedge400 SW/FW Versions ---${COLOR_NC}"
    local w400_version_cmds="
        echo '--- Common Versions ---';
        (cd /usr/local/cls_diag/rack/ && ./cls_version);
        (cd /usr/local/cls_diag/bin && ./cel-version-test --show);
        echo '--- SSD Version ---';
        (cd /usr/local/cls_diag/bin/ && ./cel-nvme-test -i | grep 'Version');
        echo '--- SDK Version ---';
        (cd /usr/local/cls_diag/SDK/ && cat Version);
    "
    run_remote "$W400_IP" "$w400_version_cmds"
    echo
}

# Function to check W400 FRU info
check_w400_fru_info() {
    echo -e "${COLOR_BLUE}--- Checking Wedge400 FRU Information ---${COLOR_NC}"
    run_remote "$W400_IP" "weutil; seutil; bsm-eutil; psu-util psu2 --get_eeprom_info"
    echo
}

# Function to check ALLC sensor status
check_allc_sensor_status() {
    echo -e "${COLOR_BLUE}--- Checking ALLC Sensor Status (W400) ---${COLOR_NC}"
    ### rpm 
    ### command rackmoncli data --dev-addr 12 | grep TACH_RPM 
    ### temp 
    ### command rackmoncli data --dev-addr 12 | grep -i temp | grep -v Status 
    ### Hum Pct RH 
    #   rackmoncli data --dev-addr 12| grep Hum_Pct_RH 
    ### 48V 
    ### command rackmoncli data --dev-addr 12 | grep HSC_P48V 
    ### Alarm ALL 
    ### command rackmoncli data --dev-addr 12 | grep Alarm
    echo -e "${COLOR_YELLOW}Checking dev-addr 12 for ALLC sensor status:${COLOR_NC}"
    run_remote "$W400_IP" "rackmoncli data --dev-addr 12 | grep -E 'TACH_RPM|temp|Hum_Pct_RH|HSC_P48V|Alarm'"
    echo -e "${COLOR_BLUE}--- ALLC Sensor Status Check Complete ---${COLOR_NC}"
    echo
}

# Function to check AALC Leakage Sensor Status
check_aalc_leakage_sensor_status() {
    echo -e "${COLOR_BLUE}--- Checking AALC Leakage Sensor Status (W400) ---${COLOR_NC}"
    # command rackmoncli read 12 0x9202
    echo -e "${COLOR_YELLOW}Checking dev-addr 12 for AALC Leakage sensor status:${COLOR_NC}"
    run_remote "$W400_IP" "rackmoncli read 12 0x9202"
    echo -e "${COLOR_BLUE}--- AALC Leakage Sensor Status Check Complete ---${COLOR_NC}"
    echo
}

# Function to check W400 sensor status
check_w400_sensor_status() {
    echo -e "${COLOR_BLUE}--- Checking Wedge400 Sensor Status ---${COLOR_NC}"
    run_remote "$W400_IP" "./cel-sensor-test -s"
    echo
}

# --- Password Helper for Block Tests ---
get_password_if_needed() {
    # If we are in password mode but the password variable is empty, prompt for it once.
    if [ "$USE_PASS_FLAG" = "true" ] && [ -z "$REMOTE_PASSWORD" ]; then
        if command_exists sshpass; then
            echo -e "${COLOR_YELLOW}Password required for block test. Please enter it once.${COLOR_NC}"
            read -s -p "Enter remote password: " temp_pass
            echo
            REMOTE_PASSWORD=$temp_pass
        else
            echo -e "${COLOR_RED}Warning: 'sshpass' is not installed. Block tests require it for password mode.${COLOR_NC}"
            echo -e "${COLOR_YELLOW}You may be prompted for a password for each individual test.${COLOR_NC}"
        fi
    fi
}

# --- One-Key Block Test Functions ---

run_all_rmc_tests() {
    get_password_if_needed
    echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
    echo -e "${COLOR_BLUE}    Running All RMC Diagnostic Tests   ${COLOR_NC}"
    echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
    run_rmc_status_check
    check_aal_rpu_ready
    check_aal_gpio_cable
    check_th6_lc_cable
    check_drip_pan_leak_sensor
    check_rmc_version
    check_rmc_fru_info
    check_rmc_sensor_status
    check_rmc_boot_slot
    echo -e "${COLOR_GREEN}All RMC tests complete.${COLOR_NC}"
}

run_all_w400_tests() {
    get_password_if_needed
    echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
    echo -e "${COLOR_BLUE}   Running All W400 Diagnostic Tests   ${COLOR_NC}"
    echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
    check_power_source
    check_psu_ishare_cable
    check_bbu_ishare_cable
    check_power_ac_loss
    check_power_shelf_version
    check_psu_bbu_versions
    check_power_fru_info
    check_allc_sensor_status
    check_w400_versions
    check_w400_fru_info
    check_w400_sensor_status
    check_aalc_leakage_sensor_status
    echo -e "${COLOR_GREEN}All W400 tests complete.${COLOR_NC}"
}

# --- Sub-Menus ---

rmc_menu() {
    while true; do
        echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
        echo -e "${COLOR_BLUE}        RMC Diagnostics Menu           ${COLOR_NC}"
        echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
        echo "1. Run Full RMC Status Check (via rmc_status_check.sh)"
        echo "2. Check AALC RPU Ready Status (i2cget)"
        echo "3. Check AALC LC GPIO Cable Detect (i2cget)"
        echo "4. Check TH6 LC Cable Detect (i2cget)"
        echo "5. Check Drip Pan Leak Sensor Presence (i2cget)"
        echo "6. Check RMC SW/FW Versions (mfg-tool)"
        echo "7. Check RMC FRU Information (mfg-tool)"
        echo "8. Check RMC Sensor Status (mfg-tool)"
        echo "9. Check RMC Boot Slot"
        echo "10. Back to Main Menu"
        echo -e "${COLOR_BLUE}---------------------------------------${COLOR_NC}"
        read -p "Enter your choice: " choice
        echo

        case $choice in
            1) run_rmc_status_check ;;
            2) check_aal_rpu_ready ;;
            3) check_aal_gpio_cable ;;
            4) check_th6_lc_cable ;;
            5) check_drip_pan_leak_sensor ;;
            6) check_rmc_version ;;
            7) check_rmc_fru_info ;;
            8) check_rmc_sensor_status ;;
            9) check_rmc_boot_slot ;;
            10) return ;;
            *) echo -e "${COLOR_RED}Invalid option. Please try again.${COLOR_NC}" ;;
        esac
        echo -e "${COLOR_YELLOW}Press Enter to continue...${COLOR_NC}"
        read -s -n 1 # Wait for any key press
    done
}

w400_menu() {
    while true; do
        echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
        echo -e "${COLOR_BLUE}      Wedge400 Diagnostics Menu        ${COLOR_NC}"
        echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
        echo "1. Power Source Detect (rackmoncli list)"
        echo "2. Check PSU Shelf Ishare Cable Status (rackmoncli)"
        echo "3. Check BBU Shelf Ishare Cable Status (rackmoncli)"
        echo "4. Check Power AC Loss Cable Detect (rackmoncli)"
        echo "5. Check Power Shelf Version (rackmoncli)"
        echo "6. Check PSU and BBU Versions (rackmoncli)"
        echo "7. Check Power FRU Info (rackmoncli)"
        echo "8. Check ALLC Sensor Status (rackmoncli)"
        echo "9. Check W400 SW/FW Versions"
        echo "10. Check W400 FRU Information"
        echo "11. Check W400 Sensor Status"
        echo "12. Check AALC Leakage Sensor Status (rackmoncli)"
        echo "13. Back to Main Menu"
        echo -e "${COLOR_BLUE}---------------------------------------${COLOR_NC}"
        read -p "Enter your choice: " choice
        echo

        case $choice in
            1) check_power_source ;;
            2) check_psu_ishare_cable ;;
            3) check_bbu_ishare_cable ;;
            4) check_power_ac_loss ;;
            5) check_power_shelf_version ;;
            6) check_psu_bbu_versions ;;
            7) check_power_fru_info ;;
            8) check_allc_sensor_status ;;
            9) check_w400_versions ;;
            10) check_w400_fru_info ;;
            11) check_w400_sensor_status ;;
            12) check_aalc_leakage_sensor_status ;;
            13) return ;;
            *) echo -e "${COLOR_RED}Invalid option. Please try again.${COLOR_NC}" ;;
        esac
        echo -e "${COLOR_YELLOW}Press Enter to continue...${COLOR_NC}"
        read -s -n 1 # Wait for any key press
    done
}

# --- Main Menu ---
main_menu() {
    echo -e "${COLOR_BLUE}--- Remote Device Configuration ---${COLOR_NC}"
    while [ -z "$RMC_IP" ]; do
        read -p "Enter the RMC device IP address: " RMC_IP
    done
    while [ -z "$W400_IP" ]; do
        read -p "Enter the Wedge400 (W400) device IP address: " W400_IP
    done
    while [ -z "$REMOTE_USER" ]; do
        read -p "Enter the remote username (e.g., root): " REMOTE_USER
    done

    USE_PASS_FLAG="false"
    # Check for a pre-configured password to enable automatic mode
    if [ -n "$CONFIGURED_PASSWORD" ]; then
        echo -e "${COLOR_YELLOW}Using pre-configured password.${COLOR_NC}"
        if ! command_exists sshpass; then
            echo -e "${COLOR_RED}Error: 'sshpass' is required for pre-configured password mode but is not installed.${COLOR_NC}"
            echo -e "${COLOR_YELLOW}Please install sshpass or clear the CONFIGURED_PASSWORD variable.${COLOR_NC}"
        else
            REMOTE_PASSWORD="$CONFIGURED_PASSWORD"
            USE_PASS_FLAG="true"
        fi
    else
        # Interactive mode if no password is pre-configured
        read -p "Use password authentication? (y/n, default: n): " use_pass
        case "$use_pass" in
            [Yy]*)
                USE_PASS_FLAG="true"
                if command_exists sshpass; then
                    read -s -p "Enter remote password (or leave blank for interactive prompt): " REMOTE_PASSWORD
                    echo
                else
                    echo -e "${COLOR_YELLOW}sshpass not found. Will use interactive password prompt if required by ssh.${COLOR_NC}"
                fi
        esac
    fi

    echo -e "${COLOR_GREEN}Configuration set.${COLOR_NC}"
    echo -e "RMC Target:   ${COLOR_YELLOW}${REMOTE_USER}@${RMC_IP}${COLOR_NC}"
    echo -e "W400 Target:  ${COLOR_YELLOW}${REMOTE_USER}@${W400_IP}${COLOR_NC}"
    echo -e "${COLOR_YELLOW}Press Enter to continue to the main menu...${COLOR_NC}"
    read -s -n 1

    while true; do
        echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
        echo -e "${COLOR_BLUE}  Rack Diagnostics & Status Check Menu ${COLOR_NC}"
        echo -e "  RMC Target:  ${COLOR_YELLOW}${REMOTE_USER}@${RMC_IP}${COLOR_NC}"
        echo -e "  W400 Target: ${COLOR_YELLOW}${REMOTE_USER}@${W400_IP}${COLOR_NC}"
        echo -e "${COLOR_BLUE}=======================================${COLOR_NC}"
        echo "1. Run All RMC Diagnostics (One-Key Test)"
        echo "2. Run All W400 Diagnostics (One-Key Test)"
        echo "3. RMC Diagnostics (Individual Tests)"
        echo "4. Wedge400 (W400) Diagnostics (Individual Tests)"
        echo "5. Change Target Device"
        echo "6. Exit"
        echo -e "${COLOR_BLUE}---------------------------------------${COLOR_NC}"
        read -p "Enter your choice: " choice
        echo

        case $choice in
            1) run_all_rmc_tests ;;
            2) run_all_w400_tests ;;
            3) rmc_menu ;;
            4) w400_menu ;;
            5) RMC_IP=""; W400_IP=""; REMOTE_USER=""; REMOTE_PASSWORD=""; USE_PASS_FLAG=""; main_menu ;; # Reset and re-run config
            6) echo -e "${COLOR_GREEN}Exiting. Goodbye!${COLOR_NC}"; exit 0 ;;
            *) echo -e "${COLOR_RED}Invalid option. Please try again.${COLOR_NC}" ;;
        esac
    done
}

# --- Execute Main Menu ---
main_menu