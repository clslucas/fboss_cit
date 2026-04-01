#!/usr/bin/env python3
import argparse
import logging
import sys
import datetime
import json
import concurrent.futures
import re
from pathlib import Path
import paramiko

# --- Configuration ---
# Configure logging for clear output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)

class SshClient:
    """A wrapper for Paramiko SSH client to simplify remote operations."""
    def __init__(self, hostname, username, password=None, key_filename=None, logger=None):
        self.hostname = hostname
        self.logger = logger or logging.getLogger() # Fallback to root logger
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.logger.info(f"Connecting to {username}@{hostname}...")
        self.client.connect(hostname, username=username, password=password, key_filename=key_filename)
        self.logger.info("Connection successful.")
        self.sftp = self.client.open_sftp()

    def execute(self, command):
        """Executes a command on the remote host and logs its output."""
        exec_msg = f"Executing command: {command}"
        self.logger.info(exec_msg)
        logging.info(f"[{self.hostname}] {exec_msg}")
        stdin, stdout, stderr = self.client.exec_command(command)
        exit_status = stdout.channel.recv_exit_status()
        
        # Log stdout and stderr for debugging
        stdout_str = stdout.read().decode().strip()
        stderr_str = stderr.read().decode().strip()
        # The detailed STDOUT/STDERR will now go to the host-specific log file.
        # We keep a summary on the main console logger.
        if stdout_str:
            self.logger.info(f"STDOUT:\n{stdout_str}")
        if stderr_str:
            self.logger.error(f"STDERR:\n{stderr_str}")

        if exit_status != 0:
            raise RuntimeError(f"Command '{command}' failed with exit status {exit_status}")
        return stdout_str

    def upload_file(self, local_path, remote_path):
        """Uploads a local file to a remote path."""
        upload_start_msg = f"Uploading '{local_path}' to '{self.hostname}:{remote_path}'..."
        self.logger.info(upload_start_msg)
        logging.info(f"[{self.hostname}] {upload_start_msg}")
        self.sftp.put(local_path, remote_path)
        upload_end_msg = "Upload complete."
        self.logger.info(upload_end_msg)
        logging.info(f"[{self.hostname}] {upload_end_msg}")

    def close(self):
        """Closes the SFTP and SSH connections."""
        if self.sftp:
            self.sftp.close()
        if self.client:
            self.client.close()
        self.logger.info("Connection closed.") # This is fine to keep in file only.

def deploy_package(ssh_client, package_config, local_tar_path, cleanup=False):
    """
    A generic function to deploy a tarball package, extract it, find the RPM, and install it.
    
    Args:
        ssh_client (SshClient): The connected SSH client.
        package_config (dict): A dictionary containing the configuration for the package.
        local_tar_path (Path): The local path to the .tar or .tar.gz file.
        cleanup (bool): If True, remove files from the client after installation.
    """
    package_name = package_config["name"]
    remote_base_dir = Path(package_config["remote_dir"])
    start_msg = f"--- Starting deployment of {package_name} ---"
    ssh_client.logger.info(start_msg)
    logging.info(f"[{ssh_client.hostname}] {start_msg}")
    
    if not local_tar_path.exists():
        raise FileNotFoundError(f"{package_name} package not found at: {local_tar_path}")

    try:
        # Run pre-install commands if they exist
        if "pre_install_cmds" in package_config:
            ssh_client.logger.info(f"Running pre-install commands for {package_name}...")
            logging.info(f"[{ssh_client.hostname}] Running pre-install commands for {package_name}...")
            for cmd in package_config["pre_install_cmds"]:
                ssh_client.execute(cmd)

        # 1. Create the remote directory
        ssh_client.execute(f"mkdir -p {remote_base_dir}")

        # 2. Upload the package
        remote_tar_path = remote_base_dir / local_tar_path.name
        ssh_client.upload_file(str(local_tar_path), str(remote_tar_path))

        # 3. Extract the package.
        # Construct the command dynamically to be more robust. This avoids issues
        # with 'cd' and hardcoded filenames. Use the correct tool for the archive type.
        if local_tar_path.suffix == '.zip':
            # Use -o to overwrite files without prompting.
            ssh_client.execute(f"unzip -o {remote_tar_path} -d {remote_base_dir}")
        else:
            ssh_client.execute(f"tar -xvf {remote_tar_path} -C {remote_base_dir}")

        # 4. Install the package based on its type
        install_type = package_config.get("install_type", "rpm") # Default to 'rpm'

        if install_type == "rpm":
            rpm_filename = package_config.get("rpm_filename")
            if rpm_filename:
                # Dynamically determine the extracted directory name from the tarball name.
                # This handles cases like 'IceTea' vs 'IceCube'.
                # It removes .tar and .tar.gz suffixes.
                extracted_dir_name = local_tar_path.name.removesuffix('.tar.gz').removesuffix('.tar')
                find_rpm_dir = Path(extracted_dir_name)
                rpm_path_str = str(remote_base_dir / find_rpm_dir / rpm_filename) # This was likely correct
                rpm_msg = f"Using specified {package_name} RPM: {rpm_path_str}"
                ssh_client.logger.info(rpm_msg)
                logging.info(f"[{ssh_client.hostname}] {rpm_msg}")
            else:
                # Fallback to finding the first RPM if not specified.
                find_rpm_dir = Path(package_config.get("find_rpm_dir", "."))
                rpm_path_str = ssh_client.execute(f"find {remote_base_dir / find_rpm_dir} -name '*.rpm' -print -quit")
                if not rpm_path_str:
                    raise FileNotFoundError(f"Could not find any RPM for {package_name} and none was specified.")
                rpm_msg = f"Found {package_name} RPM (auto-detected): {rpm_path_str}"
                ssh_client.logger.info(rpm_msg)
                logging.info(f"[{ssh_client.hostname}] {rpm_msg}")

            # Using dnf allows for dependency resolution. The '-y' flag auto-confirms.
            # Before installing, get the actual package name from the RPM file for later verification.
            rpm_name_to_verify = ssh_client.execute(f"rpm -qp --queryformat '%{{NAME}}' {rpm_path_str}")
            verify_name_msg = f"Extracted package name for verification: '{rpm_name_to_verify}'"
            ssh_client.logger.info(verify_name_msg)
            logging.info(f"[{ssh_client.hostname}] {verify_name_msg}")

            # For the BSP package, use rpm with --nodeps and --force to bypass dependency checks.
            # For all other RPMs, use the more robust 'dnf install' for dependency resolution.
            if package_config.get("name") == "bsp":
                install_cmd = f"rpm -Uvh --nodeps --force {rpm_path_str}"
                ssh_client.logger.info("Using 'rpm --nodeps --force' for BSP package.")
            else:
                install_cmd = f"dnf install -y --allowerasing {rpm_path_str}"

            ssh_client.execute(install_cmd)
            package_config["_rpm_name_for_verification"] = rpm_name_to_verify

        elif install_type == "script":
            if "install_cmds" in package_config:
                # Chain all commands to run in the same shell session, from the base directory.
                full_command = " && ".join(package_config["install_cmds"])
                ssh_client.execute(f"cd {remote_base_dir} && {full_command}")

        elif install_type == "custom_script":
            if "install_cmds" in package_config:
                ssh_client.logger.info(f"Executing custom install script for {package_name}...")
                full_command = " && ".join(package_config["install_cmds"])
                ssh_client.execute(full_command)

        elif install_type == "os_update":
            # This is a special installer for the main OS package.
            # It assumes the extracted folder name matches the tarball name without extension.
            extracted_dir_name = local_tar_path.stem.replace('.tar', '') # Handles .tar.gz as well
            os_package_root = remote_base_dir / extracted_dir_name
            
            # 1. Upload the install_os.sh script to the correct sub-directory
            install_script_name = package_config.get("install_script", "install_os.sh")
            local_install_script_path = Path(install_script_name)
            if not local_install_script_path.exists():
                raise FileNotFoundError(f"Required OS install script '{install_script_name}' not found in current directory.")
            
            remote_script_dir = os_package_root / "OS"
            ssh_client.execute(f"mkdir -p {remote_script_dir}")
            ssh_client.upload_file(str(local_install_script_path), str(remote_script_dir / install_script_name))

            # 2. Execute the installation script with the configured kernel version
            kernel_version = package_config.get("kernel_version")
            if not kernel_version:
                raise ValueError(f"Package '{package_name}' with type 'os_update' requires 'kernel_version' to be set.")
            ssh_client.execute(f"cd {remote_script_dir} && bash ./{install_script_name} {kernel_version}")

        else:
            raise ValueError(f"Unknown install_type '{install_type}' for package {package_name}")

        # 5. Verify the installation
        # Log to both the host file and the main console
        verification_msg_prefix = f"Verifying installation of {package_name}"
        ssh_client.logger.info(verification_msg_prefix + "...")
        logging.info(f"[{ssh_client.hostname}] {verification_msg_prefix}...")

        verification_performed = False

        # Check for the dynamically discovered RPM name first
        if "_rpm_name_for_verification" in package_config:
            verification_performed = True
            rpm_name_to_verify = package_config["_rpm_name_for_verification"]
            ssh_client.execute(f"rpm -q {rpm_name_to_verify}")
            success_msg = f"Verification successful: RPM '{rpm_name_to_verify}' is installed."
            ssh_client.logger.info(success_msg)
            logging.info(f"[{ssh_client.hostname}] {success_msg}")
        
        if "verify_path_exists" in package_config:
            verification_performed = True
            path_to_verify = package_config["verify_path_exists"]
            ssh_client.execute(f"test -e {path_to_verify}")
            success_msg = f"Verification successful: Path '{path_to_verify}' exists."
            ssh_client.logger.info(success_msg)
            logging.info(f"[{ssh_client.hostname}] {success_msg}")

        if "verify_cmds" in package_config:
            verification_performed = True
            ssh_client.logger.info(f"Running verification commands for {package_name}...")
            logging.info(f"[{ssh_client.hostname}] Running verification commands for {package_name}...")
            # Prepend PATH export to each command to ensure tools like rackmoncli are found.
            # Each exec_command is a new session, so the PATH must be set each time.
            for cmd in package_config["verify_cmds"]:
                full_cmd = f"export PATH=$PATH:/usr/local/bin && {cmd}"
                ssh_client.execute(full_cmd)
            success_msg = f"Verification successful: All verification commands passed for {package_name}."
            ssh_client.logger.info(success_msg)
            logging.info(f"[{ssh_client.hostname}] {success_msg}")

        if not verification_performed:
            ssh_client.logger.warning(f"No verification method defined for package {package_name}. Skipping verification.")
            # Log to main console as well for visibility
            logging.warning(f"[{ssh_client.hostname}] No verification method defined for package {package_name}. Skipping verification.")

        # Run post-install commands if they exist
        if "post_install_cmds" in package_config:
            ssh_client.logger.info(f"Running post-install commands for {package_name}...")
            logging.info(f"[{ssh_client.hostname}] Running post-install commands for {package_name}...")
            for cmd in package_config["post_install_cmds"]:
                # Also prepend PATH export here for consistency.
                full_cmd = f"export PATH=$PATH:/usr/local/bin && {cmd}"
                ssh_client.execute(full_cmd)

        # 6. Clean up remote files if requested
        if cleanup:
            cleanup_msg = f"Cleaning up remote directory: {remote_base_dir}"
            ssh_client.logger.info(cleanup_msg)
            logging.info(f"[{ssh_client.hostname}] {cleanup_msg}")
            ssh_client.execute(f"rm -rf {remote_base_dir}")

        success_deploy_msg = f"--- Successfully deployed {package_name} ---"
        ssh_client.logger.info(success_deploy_msg)
        ssh_client.logger.info("=" * 70)
        logging.info(f"[{ssh_client.hostname}] {success_deploy_msg}")
        logging.info("=" * 70)

    except Exception as e:
        # Use the host-specific logger if available
        logger = ssh_client.logger if 'ssh_client' in locals() and ssh_client else logging
        logger.error(f"!!! FAILED to deploy {package_name}: {e}")
        raise

def deploy_to_host(hostname, user, password, key_file, packages_to_deploy, packages_dir, cleanup):
    """
    Handles the entire deployment process for a single host.
    This function is designed to be run in a separate thread.
    """
    ssh = None
    try:
        # --- Per-Host Logger Setup ---
        log_dir = Path("./deploy_log")
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        log_file = log_dir / f"{hostname}-{timestamp}.log"

        host_logger = logging.getLogger(f"host_{hostname}")
        host_logger.setLevel(logging.INFO)
        # Prevent logs from propagating to the root console logger
        host_logger.propagate = False
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        host_logger.addHandler(file_handler)

        # Establish SSH connection using keyword arguments for clarity and safety.
        ssh = SshClient(hostname=hostname, username=user, password=password, key_filename=key_file, logger=host_logger)

        # --- Force NTP Sync ---
        # Newly provisioned machines often have incorrect clocks. Forcing a sync
        # prevents issues with file timestamps and certificate validation.
        logging.info(f"[{hostname}] Forcing NTP clock synchronization...")
        ssh.execute("chronyc -a makestep")
        logging.info(f"[{hostname}] NTP sync complete.")

        # Iterate through the packages and deploy each one
        for package in packages_to_deploy:
            # Use the pre-resolved path from the main thread
            local_tar_path = package["_local_tar_path"]
            deploy_package(
                ssh_client=ssh,
                package_config=package,
                local_tar_path=local_tar_path,
                cleanup=cleanup
            )

        logging.info(f"[{hostname}] All packages deployed successfully!")
        return (hostname, True, "Success")

    except Exception as e:
        error_message = f"An error occurred during deployment to {hostname}: {e}"
        logging.error(f"[{hostname}] {error_message}")
        return (hostname, False, error_message)
    finally:
        if ssh:
            ssh.close()

def find_package_file(package_config, packages_dir):
    """
    Finds the package tarball in the local packages directory based on regex.

    It constructs a regex from the package name and an optional version.
    - If `version` is specified (e.g., "1.1.0"), it looks for that exact version.
    - If `min_version` is specified (e.g., "1.4.0"), it finds the latest version that is >= 1.4.0.
    - If neither is specified, it finds the file with the highest version number.

    Args:
        package_config (dict): The package configuration dictionary.
        packages_dir (str or Path): The directory where package tarballs are stored.

    Returns:
        Path: The path to the found package file.

    Raises:
        FileNotFoundError: If no matching package file can be found.
        ValueError: If both 'version' and 'min_version' are specified for the same package.
    """
    name = package_config['name']
    version = package_config.get('version')
    min_version = package_config.get('min_version')
    packages_path = Path(packages_dir)
    filename_pattern = package_config.get('filename_pattern')

    # If a specific filename pattern is provided, use it directly.
    if filename_pattern:
        logging.info(f"Searching for package '{name}' using specific pattern: '{filename_pattern}' in '{packages_path}'...")
        found_files = list(packages_path.glob(filename_pattern))
        if not found_files:
            raise FileNotFoundError(f"Package file for '{name}' not found using pattern '{filename_pattern}' in '{packages_path}'.")
        # Return the first match for the glob pattern
        return found_files[0]

    if version and min_version:
        raise ValueError(f"Package '{name}' cannot have both 'version' and 'min_version' defined.")

    if version:
        # Match a specific version. Escape dots to treat them as literals.
        version_pattern = re.escape(version)
        pattern = re.compile(f".*[^a-zA-Z0-9]{re.escape(name)}[^a-zA-Z0-9].*{version_pattern}.*\\.(tar|tar\\.gz|zip)$", re.IGNORECASE)
        logging.info(f"Searching for package '{name}' with version '{version}' in '{packages_path}'...")
        found_files = [f for f in packages_path.glob('*') if pattern.match(f.name)]
    else:
        # Match any version number (e.g., 1.2.3, 1.0, 2024.1)
        pattern = re.compile(f".*[^a-zA-Z0-9]{re.escape(name)}[^a-zA-Z0-9].*(\\d+(\\.\\d+)*).*\\.(tar|tar\\.gz|zip)$", re.IGNORECASE)
        
        if min_version:
            logging.info(f"Searching for package '{name}' with minimum version '{min_version}' in '{packages_path}'...")
            min_version_tuple = tuple(map(int, min_version.split('.')))
            
            candidate_files = []
            for f in packages_path.glob('*'):
                match = pattern.match(f.name)
                if match:
                    file_version_str = match.group(1)
                    file_version_tuple = tuple(map(int, file_version_str.split('.')))
                    if file_version_tuple >= min_version_tuple:
                        candidate_files.append(f)
            found_files = candidate_files
        else:
            logging.info(f"Searching for the latest version of package '{name}' in '{packages_path}'...")
            found_files = [f for f in packages_path.glob('*') if pattern.match(f.name)]

    if not found_files:
        raise FileNotFoundError(f"No package file found for '{name}' with specified criteria in '{packages_path}'.")

    # If we are not matching an exact version, sort to find the latest.
    if not version:
        found_files.sort(key=lambda p: tuple(map(int, (pattern.match(p.name).group(1).split('.')))), reverse=True)
    
    return found_files[0]

def check_host_ssh(hostname, user, password, key_filename):
    """
    Performs a quick SSH connection test to a host.
    Returns (hostname, is_reachable, message).
    """
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # Add a timeout to avoid long waits for unreachable hosts
        ssh_client.connect(hostname, username=user, password=password, key_filename=key_filename, timeout=10)
        ssh_client.close()
        logging.info(f"[{hostname}] SSH pre-flight check successful.")
        return (hostname, True, "SSH check successful")
    except Exception as e:
        message = f"SSH pre-flight check failed: {e}"
        logging.error(f"[{hostname}] {message}")
        return (hostname, False, message)

def main():
    """Main function to parse arguments and orchestrate package deployment."""
    parser = argparse.ArgumentParser(
        description="Deploy custom packages (BSP, UniDiag, etc.) to one or more client machines in parallel.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("hostnames", nargs='+', help="One or more hostnames or IP addresses of the client machines.")
    parser.add_argument("-u", "--user", default="root", help="The SSH username to connect with (default: root).")
    parser.add_argument("-p", "--password", help="The SSH password. Use key-based auth if possible.")
    parser.add_argument("-k", "--key-file", help="Path to the SSH private key file for authentication.")
    parser.add_argument("-c", "--config-file", default="packages.json", help="Path to the JSON file defining packages to deploy (default: packages.json).")
    parser.add_argument("-w", "--workers", type=int, default=10, help="Maximum number of parallel deployment threads (default: 10).")
    parser.add_argument("--cleanup", action="store_true", help="Remove temporary files from the client after successful installation.")
    parser.add_argument("--packages-dir", default=".", help="Local directory where package tarballs are located (default: current directory).")
    parser.add_argument("--skip-packages", nargs='+', help="A list of package names (from the config file) to skip during deployment.")
    parser.add_argument("--only-packages", nargs='+', help="Only deploy packages from this explicit list, ignoring all others.")
    # dry-run argument, to show what would be done without making changes.
    parser.add_argument("--dry-run", action="store_true", help="Show which packages and versions would be deployed without connecting to hosts.")
    args = parser.parse_args()

    # Validate authentication method
    if not args.password and not args.key_file:
        logging.error("You must provide either a password (--password) or a key file (--key-file).")
        sys.exit(1)

    # Validate that skip-packages and only-packages are not both used
    if args.skip_packages and args.only_packages:
        logging.error("Error: --skip-packages and --only-packages cannot be used at the same time.")
        sys.exit(1)

    try:
        # Load package definitions from the JSON config file
        with open(args.config_file, 'r') as f:
            all_packages = json.load(f)
        logging.info(f"Loaded {len(all_packages)} total package definition(s) from '{args.config_file}'.")

        # Validate that all packages have a 'name'
        if any('name' not in pkg for pkg in all_packages):
            logging.error(f"Error: All entries in '{args.config_file}' must have a 'name' key.")
            sys.exit(1)

        # Filter out any packages specified to be skipped
        packages_to_deploy = all_packages
        if args.only_packages:
            only_packages_set = set(args.only_packages)
            packages_to_deploy = [
                pkg for pkg in all_packages if pkg.get('name') in only_packages_set
            ]
            logging.info(f"Deploying only {len(packages_to_deploy)} package(s): {', '.join(args.only_packages)}")
        elif args.skip_packages:
            skipped_packages_set = set(args.skip_packages)
            packages_to_deploy = [
                pkg for pkg in all_packages if pkg.get('name') not in skipped_packages_set
            ]
            skipped_names = [pkg.get('name') for pkg in all_packages if pkg.get('name') in skipped_packages_set]
            logging.info(f"Skipping {len(skipped_names)} package(s): {', '.join(skipped_names)}")
        
        # --- Resolve package file paths before deployment ---
        try:
            for pkg in packages_to_deploy:
                found_path = find_package_file(pkg, args.packages_dir)
                pkg['_local_tar_path'] = found_path # Store path for later use
                logging.info(f"Resolved package '{pkg['name']}': Found '{found_path.name}'")
        except FileNotFoundError as e:
            logging.error(f"Failed to find a required package file: {e}")
            sys.exit(1)

        logging.info(f"Found {len(packages_to_deploy)} package(s) to deploy.")

        # --- Handle Dry Run ---
        if args.dry_run:
            logging.info("\n" + "="*20 + " DRY RUN MODE " + "="*20)
            logging.info("The following actions would be performed. No remote connections will be made.")
            
            if not packages_to_deploy:
                logging.info("No packages selected for deployment.")
            else:
                for host in args.hostnames:
                    logging.info(f"\n--- Plan for Host: {host} ---")
                    for pkg in packages_to_deploy:
                        logging.info(f"  - Would deploy package '{pkg['name']}' using file '{pkg['_local_tar_path'].name}'")
            
            logging.info("\n" + "="*20 + " END DRY RUN " + "="*20)
            sys.exit(0)

        # --- Phase 1: Pre-flight SSH Checks ---
        logging.info("\n" + "="*20 + " PHASE 1: PRE-FLIGHT CHECKS " + "="*20)
        unreachable_hosts = []
        reachable_hosts = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_host = {
                executor.submit(check_host_ssh, host, args.user, args.password, args.key_file): host
                for host in args.hostnames
            }
            for future in concurrent.futures.as_completed(future_to_host):
                hostname, is_reachable, message = future.result()
                if is_reachable:
                    reachable_hosts.append(hostname)
                else:
                    unreachable_hosts.append((hostname, False, message))

        # --- Phase 2: Package Deployment ---
        deployment_results = []
        if reachable_hosts:
            logging.info("\n" + "="*20 + " PHASE 2: PACKAGE DEPLOYMENT " + "="*20)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                # Submit a deployment task for each reachable host
                future_to_host = {
                    executor.submit(
                        deploy_to_host,
                        host, args.user, args.password, args.key_file,
                        packages_to_deploy, args.packages_dir, args.cleanup
                    ): host for host in reachable_hosts
                }

                for future in concurrent.futures.as_completed(future_to_host):
                    host = future_to_host[future]
                    try:
                        deployment_results.append(future.result())
                    except Exception as exc:
                        logging.error(f"[{host}] Generated an exception: {exc}")
                        deployment_results.append((host, False, str(exc)))
        else:
            logging.warning("No reachable hosts to deploy to.")

        # --- Print Summary Report ---
        all_results = deployment_results + unreachable_hosts
        logging.info("\n" + "="*20 + " DEPLOYMENT SUMMARY " + "="*20)
        successful_hosts = [res for res in all_results if res[1]]
        failed_hosts = [res for res in all_results if not res[1]]

        logging.info(f"Total hosts: {len(all_results)}, Successful: {len(successful_hosts)}, Failed: {len(failed_hosts)}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            pass
        
        if successful_hosts:
            logging.info("\n--- Successful Deployments ---")
            # Get a list of package names for the summary
            package_names = [p.get('name', 'Unknown') for p in packages_to_deploy]
            package_names_str = ", ".join(package_names)
            for host, _, _ in successful_hosts:
                logging.info(f"  - {host}: Completed {len(packages_to_deploy)} package(s): {package_names_str}.")

        if failed_hosts:
            logging.error("\n--- Failed Deployments ---")
            for host, _, message in failed_hosts:
                logging.error(f"  - {host}: {message}")

    except FileNotFoundError as e:
        logging.error(f"Configuration or package file not found: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
