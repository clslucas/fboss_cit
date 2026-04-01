import paramiko
import time
import subprocess
import json
import re
import os
import glob
import argparse

# ================= Helper Functions: Version Parsing & Comparison =================
def parse_bmc_version(ver_str):
    """
    Parse BMC version string into a tuple for comparison.
    E.g., 'ventura-v2025.41.2' -> (2025, 41, 2)
    """
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', str(ver_str))
    if match:
        return tuple(map(int, match.groups()))
    return (0, 0, 0)

def parse_cpld_version(ver_str):
    """
    Parse CPLD version string into an integer.
    Handles both hex formats with or without '0x'.
    """
    try:
        return int(str(ver_str), 16)
    except:
        return 0

# ================= Helper Functions: Dynamic Image Finding =================
def find_image_and_version(directory, file_pattern, version_regex):
    """
    Find the image file dynamically using a wildcard pattern,
    and extract its version number using a regular expression.
    """
    search_path = os.path.join(directory, file_pattern)
    matched_files = glob.glob(search_path)
    
    if not matched_files:
        raise FileNotFoundError(f"No image files matching '{file_pattern}' found in '{directory}'!")
    
    # Sort and pick the last one if multiple exist (usually the latest version)
    matched_files.sort()
    if len(matched_files) > 1:
        print(f"[!] Warning: Found multiple files matching '{file_pattern}'. Using the latest one: {os.path.basename(matched_files[-1])}")
        
    target_filepath = matched_files[-1]
    filename = os.path.basename(target_filepath)
    
    # Extract version number
    match = re.search(version_regex, filename)
    if not match:
        raise ValueError(f"Failed to extract version number from filename '{filename}'! (Regex: {version_regex})")
    
    version_str = match.group(1)
    return target_filepath, version_str
# ==============================================================================

class FirmwareUpdater:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ssh = None

    def connect(self):
        """Establish SSH connection and bypass known_hosts check."""
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.ssh.connect(self.host, port=self.port, username=self.username, password=self.password, timeout=10)
            print(f"[+] Successfully connected to device {self.host}")
        except Exception as e:
            print(f"[-] Connection failed: {e}")
            raise

    def disconnect(self):
        """Close the SSH connection."""
        if self.ssh:
            self.ssh.close()

    def execute_cmd(self, cmd, ignore_error=False, quiet=False):
        """Execute a remote command and return the output."""
        if not quiet:
            print(f"[*] Executing command: {cmd}")
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        
        # Do not wait for response if rebooting
        if cmd.strip() == "reboot":
            return ""

        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8').strip()
        err = stderr.read().decode('utf-8').strip()
        
        if exit_status != 0 and not ignore_error:
            print(f"[-] Command execution failed (Exit Code {exit_status}): {err}")
        elif out and not quiet:
            print(f"[+] Output: \n{out}")
            
        return out

    def upload_file(self, local_path, remote_path):
        """Upload an image file via SFTP."""
        print(f"[*] Uploading file {local_path} to {remote_path}...")
        sftp = self.ssh.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
        print(f"[+] File upload completed!")

    def wait_for_reboot(self, initial_wait=60):
        """Reboot waiting logic: ping detection with dynamic backoff."""
        self.disconnect()
        print(f"[*] Device is rebooting. Initial wait of {initial_wait} seconds...")
        time.sleep(initial_wait)

        interval = 10  
        max_retries = 15
        retries = 0

        while retries < max_retries:
            retries += 1
            print(f"[*] Attempting to ping device (Try {retries})...")
            response = subprocess.call(['ping', '-c', '1', '-W', '2', self.host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if response == 0:
                print("[+] Ping successful! Waiting 10s for SSH service to initialize...")
                time.sleep(10)
                try:
                    self.connect()
                    print("[+] Device has successfully rebooted and SSH connection restored!")
                    return True
                except:
                    print("[-] SSH is not ready yet, continuing to wait...")
            else:
                print(f"[-] Ping failed, retrying in {interval} seconds...")
                
            time.sleep(interval)
            interval = min(interval + 5, 30) 

        print("[-] Timeout waiting for device reboot!")
        return False

    def check_bmc_partition(self):
        """Check and return the mtd mappings for Primary and Alternate partitions."""
        out = self.execute_cmd("cat /run/media/slot").strip()
        if out == "0" or "0: Primary" in out:
            print("[+] Currently on Primary partition (0). Mapping: Current->/dev/mtd0, Alternate->/dev/mtd6")
            return "/dev/mtd0", "/dev/mtd6"
        elif out == "1" or "1: Alternate" in out:
            print("[+] Currently on Alternate partition (1). Mapping: Current->/dev/mtd6, Alternate->/dev/mtd0")
            return "/dev/mtd6", "/dev/mtd0"
        else:
            raise Exception(f"Unrecognized BMC partition status. Actual output: '{out}'")

    def update_bmc_partition(self, image_path, mtd_device):
        """Update the specified BMC partition."""
        print(f"[*] Starting update for BMC partition {mtd_device}...")
        self.execute_cmd("echo 0 > /proc/sys/kernel/hung_task_panic")
        self.execute_cmd(f"flashcp -v {image_path} {mtd_device}")
        print(f"[+] BMC partition {mtd_device} update completed!")

    def check_versions(self):
        """Execute version reading command and parse the JSON output."""
        print("\n[*] Reading current system version information...")
        out = self.execute_cmd("mfg-tool version-display", quiet=True)
        
        parsed_versions = {
            "bmc": "N/A",
            "rmc_cfg0": "N/A",
            "scm_cpld": "N/A"
        }

        try:
            start_idx = out.find('{')
            end_idx = out.rfind('}') + 1
            if start_idx != -1 and end_idx != 0:
                json_str = out[start_idx:end_idx]
                ver_data = json.loads(json_str)
                
                parsed_versions["bmc"] = ver_data.get("bmc", "N/A")
                chassis = ver_data.get("chassis", {})
                parsed_versions["rmc_cfg0"] = chassis.get("Ventura_RMC_cpld_cfg0", "N/A")
                parsed_versions["scm_cpld"] = chassis.get("Ventura_SCM_cpld", "N/A")
            else:
                print("[-] Could not find valid JSON data in the output.")
        except json.JSONDecodeError as e:
            print(f"[-] JSON parsing failed: {e}")

        return parsed_versions


def main():
    # Setup command-line arguments parsing
    parser = argparse.ArgumentParser(description="Automated Firmware Update Script for RMC, BMC, and SCM CPLD.")
    
    # Required Arguments
    parser.add_argument(
        "-i", "--ip", 
        dest="device_ip", 
        required=True, 
        help="IP address of the target device"
    )
    parser.add_argument(
        "-d", "--dir", 
        dest="image_dir", 
        required=True, 
        help="Path to the directory containing firmware images"
    )
    
    # Optional Arguments (with Defaults)
    parser.add_argument(
        "-u", "--user", 
        dest="ssh_user", 
        default="root", 
        help="SSH username (default: root)"
    )
    parser.add_argument(
        "-p", "--password", 
        dest="ssh_pass", 
        default="0penBmc", 
        help="SSH password (default: 0penBmc)"
    )
    
    args = parser.parse_args()

    # ================= Configuration =================
    DEVICE_IP = args.device_ip
    IMAGE_DIR = args.image_dir
    SSH_USER = args.ssh_user      # Extracted from CLI (defaults to 'root')
    SSH_PASS = args.ssh_pass      # Extracted from CLI (defaults to '0penBmc')
    
    REMOTE_DIR = "/tmp"
    # =================================================

    print("--- Step 0: Dynamically find and parse target image files ---")
    try:
        LOCAL_RMC_CPLD, TARGET_VER_RMC = find_image_and_version(
            IMAGE_DIR, "RMC_CPLD_*_impl_a.jed", r"RMC_CPLD_([0-9a-fA-F]+)_impl_a\.jed"
        )
        LOCAL_BMC_IMG, TARGET_VER_BMC = find_image_and_version(
            IMAGE_DIR, "ventura-v*.mtd", r"ventura-v([0-9\.]+)\.mtd"
        )
        LOCAL_SCM_CPLD, TARGET_VER_SCM = find_image_and_version(
            IMAGE_DIR, "scmfpga_top_rmc_*_cfm0_auto.rpd", r"scmfpga_top_rmc_\d+_([0-9a-fA-F]+)_cfm0_auto\.rpd"
        )
    except Exception as e:
        print(f"[-] Failed to load image files: {e}")
        return

    print(f"[+] Found RMC CPLD image: {os.path.basename(LOCAL_RMC_CPLD)} (Extracted Version: {TARGET_VER_RMC})")
    print(f"[+] Found BMC image:      {os.path.basename(LOCAL_BMC_IMG)} (Extracted Version: {TARGET_VER_BMC})")
    print(f"[+] Found SCM CPLD image: {os.path.basename(LOCAL_SCM_CPLD)} (Extracted Version: {TARGET_VER_SCM})")

    # Define remote paths
    REMOTE_RMC_CPLD = f"{REMOTE_DIR}/RMC_CPLD.jed"
    REMOTE_BMC_IMG = f"{REMOTE_DIR}/bmc.mtd"
    REMOTE_SCM_CPLD = f"{REMOTE_DIR}/SCM_CPLD.rpd"

    updater = FirmwareUpdater(DEVICE_IP, 22, SSH_USER, SSH_PASS)
    
    try:
        updater.connect()

        # --- Prep Phase: Version Retrieval and Comparison ---
        curr_vers = updater.check_versions()

        print("\n================ Version Comparison ==================")
        print(f"  Component | Current Version       | Target Version")
        print(f"  ----------|-----------------------|-------------")
        print(f"  BMC       | {curr_vers['bmc']:<21} | {TARGET_VER_BMC}")
        print(f"  RMC CPLD  | {curr_vers['rmc_cfg0']:<21} | {TARGET_VER_RMC}")
        print(f"  SCM CPLD  | {curr_vers['scm_cpld']:<21} | {TARGET_VER_SCM}")
        print("======================================================")

        curr_bmc_val = parse_bmc_version(curr_vers["bmc"])
        tgt_bmc_val  = parse_bmc_version(TARGET_VER_BMC)

        curr_rmc_val = parse_cpld_version(curr_vers["rmc_cfg0"])
        tgt_rmc_val  = parse_cpld_version(TARGET_VER_RMC)

        curr_scm_val = parse_cpld_version(curr_vers["scm_cpld"])
        tgt_scm_val  = parse_cpld_version(TARGET_VER_SCM)

        # 1. Check matching versions to skip
        need_update_bmc = curr_bmc_val != tgt_bmc_val
        need_update_rmc = curr_rmc_val != tgt_rmc_val
        need_update_scm = curr_scm_val != tgt_scm_val

        print("\n--- Evaluation Results ---")
        if not need_update_bmc: print("[*] BMC version matches. Update will be skipped.")
        if not need_update_rmc: print("[*] RMC CPLD version matches. Update will be skipped.")
        if not need_update_scm: print("[*] SCM CPLD version matches. Update will be skipped.")

        if not any([need_update_bmc, need_update_rmc, need_update_scm]):
            print("\n[+] All components are already at the target version. No updates required! Exiting.")
            return

        # 2. Check for downgrades among the components that DO need an update
        downgrade_warnings = []
        if need_update_bmc and curr_bmc_val > tgt_bmc_val and curr_bmc_val != (0,0,0): downgrade_warnings.append("BMC")
        if need_update_rmc and curr_rmc_val > tgt_rmc_val and curr_rmc_val != 0: downgrade_warnings.append("RMC CPLD")
        if need_update_scm and curr_scm_val > tgt_scm_val and curr_scm_val != 0: downgrade_warnings.append("SCM CPLD")

        if downgrade_warnings:
            print(f"\n[!] WARNING: A DOWNGRADE is detected for the following component(s): {', '.join(downgrade_warnings)}")
            user_input = input("[?] Are you sure you want to force a downgrade? (Enter 'y' to continue, any other key to abort): ")
            if user_input.strip().lower() != 'y':
                print("[-] Update process aborted by user.")
                return
        else:
            print("[+] No downgrades detected. Proceeding with required upgrades.")

        # --- Phase 1: Pre-Reboot Sequence (RMC & BMC Current) ---
        if need_update_rmc or need_update_bmc:
            print("\n--- Phase 1: Uploading necessary images ---")
            if need_update_rmc: updater.upload_file(LOCAL_RMC_CPLD, REMOTE_RMC_CPLD)
            if need_update_bmc: updater.upload_file(LOCAL_BMC_IMG, REMOTE_BMC_IMG)

            if need_update_rmc:
                print("\n--- Updating RMC CPLD (CFG0 and CFG1) ---")
                updater.execute_cmd(f"cpld-fw-handler update --chip LCMXO3D-9400 --interface i2c --bus 14 --addr 0x40 --target CFG0 --path {REMOTE_RMC_CPLD}")
                updater.execute_cmd(f"cpld-fw-handler update --chip LCMXO3D-9400 --interface i2c --bus 14 --addr 0x40 --target CFG1 --path {REMOTE_RMC_CPLD}")

            if need_update_bmc:
                print("\n--- Updating current BMC partition ---")
                current_mtd, _ = updater.check_bmc_partition()
                updater.update_bmc_partition(REMOTE_BMC_IMG, current_mtd)

            print("\n--- Rebooting device (End of Phase 1) ---")
            updater.execute_cmd("reboot")
            # Wait for 60 seconds initially before polling
            if not updater.wait_for_reboot(initial_wait=60):
                print("[-] Device failed to come online. Process terminated!")
                return
            
            # Verify Phase 1 updates
            updater.check_versions()

        # --- Phase 2: Post-Reboot Sequence (SCM & BMC Alternate) ---
        if need_update_scm or need_update_bmc:
            print("\n--- Phase 2: Uploading necessary images ---")
            if need_update_scm: updater.upload_file(LOCAL_SCM_CPLD, REMOTE_SCM_CPLD)
            # Re-upload BMC image since /tmp is wiped upon reboot
            if need_update_bmc: updater.upload_file(LOCAL_BMC_IMG, REMOTE_BMC_IMG)

            if need_update_scm:
                print("\n--- Updating RMC SCM CPLD ---")
                updater.execute_cmd(f"fw-util scm --update cpld {REMOTE_SCM_CPLD}")

            if need_update_bmc:
                print("\n--- Updating alternate BMC partition ---")
                # Re-check partition mappings after reboot to be perfectly safe
                _, alternate_mtd = updater.check_bmc_partition()
                updater.update_bmc_partition(REMOTE_BMC_IMG, alternate_mtd)
            
            print("\n--- Rebooting device (End of Phase 2) ---")
            updater.execute_cmd("reboot")
            if not updater.wait_for_reboot(initial_wait=60):
                print("[-] Device failed to come online. Process terminated!")
                return
            
            # Final verification
            updater.check_versions()

        print("\n[+] The selective update process has been successfully completed!")

    except Exception as e:
        print(f"\n[-] An error occurred during the update process: {e}")
    finally:
        updater.disconnect()

if __name__ == "__main__":
    main()