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

### 2. Systemd Service File

This `systemd` unit file will manage the Python API, ensuring it starts on boot and restarts automatically if it fails.

I'll create this as a new file at `/etc/systemd/system/pxe-control.service`.

```diff
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

After creating these files, you would typically run the following commands to enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pxe-control.service
sudo systemctl status pxe-control.service
