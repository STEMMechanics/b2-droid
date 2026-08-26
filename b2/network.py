"""Local network discovery and NetworkManager Wi-Fi operations."""

import hashlib
import json
import socket
import subprocess


def local_ip_addresses():
    """Return non-loopback IPv4 addresses without requiring internet access."""
    addresses = set()
    try:
        result = subprocess.run(
            ["ip", "-j", "-4", "address", "show", "up"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        for interface in json.loads(result.stdout):
            if interface.get("ifname") == "lo":
                continue
            for address in interface.get("addr_info", []):
                if address.get("scope") == "global" and address.get("local"):
                    addresses.add(address["local"])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def wifi_scan():
    """Return visible SSIDs reported by NetworkManager."""
    result = subprocess.run(
        ["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes"],
        capture_output=True, text=True, timeout=20, check=True,
    )
    return sorted({
        line.replace(r"\:", ":").strip()
        for line in result.stdout.splitlines() if line.strip()
    })


def wifi_connect(ssid, password):
    """Connect using NetworkManager, repairing incomplete WPA profiles."""
    if not ssid:
        raise ValueError("Choose a Wi-Fi network")
    command = ["nmcli", "--wait", "40", "device", "wifi", "connect", ssid]
    if password:
        command += ["password", password]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    if result.returncode and password and "key-mgmt" in (result.stderr + result.stdout):
        profile = "b2-" + hashlib.sha256(ssid.encode()).hexdigest()[:12]
        subprocess.run(
            ["nmcli", "connection", "delete", profile],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        create = subprocess.run(
            [
                "nmcli", "connection", "add", "type", "wifi", "ifname", "*",
                "con-name", profile, "ssid", ssid, "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", password,
            ],
            capture_output=True, text=True, timeout=20,
        )
        if create.returncode:
            raise RuntimeError(create.stderr.strip() or create.stdout.strip())
        result = subprocess.run(
            ["nmcli", "--wait", "40", "connection", "up", profile],
            capture_output=True, text=True, timeout=45,
        )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return {"connected": True, "network": ssid, "message": result.stdout.strip()}
