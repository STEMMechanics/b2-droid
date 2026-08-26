"""Privileged, bootloader-style removable-media update watcher."""

import json
import os
import subprocess
import sys
import termios
import time
from pathlib import Path

from .updater import apply_update, find_update
from .runtime_config import apply_pending_request

MOUNT_POINT = Path("/run/b2-update-media")
SUPPORTED_FILESYSTEMS = {"vfat", "exfat", "ext2", "ext3", "ext4", "ntfs", "ntfs3"}


def show_updating():
    """Ask current firmware for its long-timeout update animation."""
    port = os.environ.get("B2_SERIAL_PORT", "/dev/ttyACM0")
    descriptor = None
    try:
        descriptor = os.open(port, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        settings = termios.tcgetattr(descriptor)
        settings[4] = termios.B115200
        settings[5] = termios.B115200
        termios.tcsetattr(descriptor, termios.TCSANOW, settings)
        os.write(descriptor, b"updating\n")
    except OSError as error:
        print(f"Could not show update animation: {error}", flush=True)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _removable_filesystems():
    """Return unmounted removable partitions without guessing /dev/sdX names."""
    commands = (
        ["lsblk", "--json", "--paths", "--output",
         "PATH,TYPE,RM,TRAN,FSTYPE,MOUNTPOINTS,LABEL"],
        ["lsblk", "--json", "--paths", "--output",
         "PATH,TYPE,RM,TRAN,FSTYPE,MOUNTPOINT,LABEL"],
    )
    payload = None
    last_error = None
    for command in commands:
        try:
            payload = json.loads(subprocess.run(
                command, capture_output=True, text=True, check=True,
            ).stdout)
            break
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            last_error = error
    if payload is None:
        print(f"Removable-media discovery unavailable: {last_error}", flush=True)
        return []

    candidates = []

    def visit(item, parent_removable=False, parent_transport=None):
        transport = item.get("tran") or parent_transport
        removable = bool(item.get("rm")) or parent_removable or transport == "usb"
        filesystem = (item.get("fstype") or "").lower()
        mountpoints = item.get("mountpoints") or item.get("mountpoint") or []
        if isinstance(mountpoints, str):
            mountpoints = [mountpoints]
        mounted = any(mountpoints)
        if (
            removable and not mounted and filesystem in SUPPORTED_FILESYSTEMS
            and item.get("type") in {"part", "disk"} and item.get("path")
        ):
            priority = 0 if item.get("label") == "B2UPDATE" else 1
            candidates.append((priority, item["path"]))
        for child in item.get("children") or []:
            visit(child, removable, transport)

    for block in payload.get("blockdevices") or []:
        visit(block)
    return [path for _, path in sorted(candidates)]


def mount_removable_media(skip_until):
    """Mount one eligible USB/SD filesystem read-only for marker inspection."""
    MOUNT_POINT.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["mountpoint", "-q", str(MOUNT_POINT)], check=False
    )
    if result.returncode == 0:
        return None
    now = time.monotonic()
    for device in _removable_filesystems():
        if now < skip_until.get(device, 0):
            continue
        try:
            subprocess.run(
                ["mount", "-o", "ro,nosuid,nodev,noexec", device, str(MOUNT_POINT)],
                check=True,
            )
            return device
        except subprocess.SubprocessError as error:
            print(f"Could not inspect {device}: {error}", flush=True)
            skip_until[device] = now + 30
    return None


def main():
    print("B2 update watcher online; waiting for marked removable media.", flush=True)
    skip_until = {}
    while True:
        mounted_device = None
        reload_after_update = False
        try:
            if apply_pending_request():
                print("Applying dashboard configuration and restarting B2.", flush=True)
                subprocess.run(["systemctl", "restart", "b2-droid.service"], check=False)
            mounted_device = mount_removable_media(skip_until)
            manifest = find_update()
            if manifest:
                print(f"Applying B2 update from {manifest}", flush=True)
                show_updating()
                changed = apply_update(manifest)
                print("B2 update installed." if changed else "Version already installed.", flush=True)
                reload_after_update = changed
            elif mounted_device:
                skip_until[mounted_device] = time.monotonic() + 30
        except Exception as error:
            print(f"Update ignored: {error}", flush=True)
        finally:
            if mounted_device:
                subprocess.run(["umount", str(MOUNT_POINT)], check=False)
        if reload_after_update:
            os.execv(sys.executable, [sys.executable, "-m", "b2.updater_daemon"])
        time.sleep(3)


if __name__ == "__main__":
    main()
