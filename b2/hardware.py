"""Hardware registry orchestration; model output never reaches hardware directly."""

import threading

from .hardware_protocol import HardwareProtocolError
from .hardware_registry import HardwareValidationError


class HardwareService:
    def __init__(self, registry, protocol=None):
        self.registry = registry
        self.protocol = protocol
        self._last_readings = {}
        self._lock = threading.RLock()
        self.registry.ensure_schema()

    def provision(self):
        devices = self.registry.list(enabled_only=True)
        if self.protocol is None:
            for device in devices:
                self.registry.update_status(device["device_id"], "unavailable")
            return {"configured": 0, "unavailable": len(devices)}
        configured = unavailable = 0
        try:
            self.protocol.reset()
        except (OSError, HardwareProtocolError):
            for device in devices:
                self.registry.update_status(device["device_id"], "unavailable")
            return {"configured": 0, "unavailable": len(devices)}
        for device in devices:
            try:
                self.protocol.add(device)
                self.registry.update_status(device["device_id"], "configured")
                configured += 1
            except (OSError, HardwareProtocolError):
                self.registry.update_status(device["device_id"], "unavailable")
                unavailable += 1
        return {"configured": configured, "unavailable": unavailable}

    def add(self, candidate):
        device = self.registry.validate(candidate)
        if self.protocol is not None:
            self.protocol.add(device)  # Persist only after firmware accepted it.
            device["last_status"] = "configured"
        else:
            device["last_status"] = "unavailable"
        return self.registry.add(device)

    def remove(self, name):
        device = self.registry.get(name)
        if not device:
            raise HardwareValidationError(f"unknown hardware {name}")
        if self.protocol is not None:
            self.protocol.remove(device["friendly_name"])
        return self.registry.remove(name)

    def scan_i2c(self):
        if self.protocol is None:
            raise HardwareProtocolError("Arduino is unavailable")
        found = self.protocol.scan_i2c()
        registered = {d["i2c_address"]: d for d in self.registry.list() if d["i2c_address"] is not None}
        for address, device in registered.items():
            self.registry.update_status(
                device["device_id"], "detected" if address in found else "unavailable"
            )
        return {
            "detected": found,
            "known": [registered[a]["friendly_name"] for a in found if a in registered],
            "unknown": [a for a in found if a not in registered],
            "unavailable": [d["friendly_name"] for a, d in registered.items() if a not in found],
        }

    def read(self, name, test=False):
        device = self.registry.get(name)
        if not device:
            raise HardwareValidationError(f"unknown hardware {name}")
        if self.protocol is None:
            self.registry.update_status(name, "unavailable")
            raise HardwareProtocolError("Arduino is unavailable")
        result = self.protocol.test(name) if test else self.protocol.read(name)
        ok = result.get("kind") == "reading" or result.get("status") == "ok"
        self.registry.update_status(name, "responding" if ok else result.get("status", "unverified"), ok and test)
        if result.get("kind") == "reading":
            with self._lock:
                self._last_readings[device["friendly_name"]] = {
                    "value": result["value"], "unit": result["unit"]
                }
        return result

    def context(self):
        devices = self.registry.list()
        resources = self.registry.resources()
        warnings = [d["config"].get("warning") for d in devices if d["config"].get("warning")]
        with self._lock:
            readings = dict(self._last_readings)
        summaries = []
        for device in devices:
            summary = f"{device['friendly_name']}: {device['last_status']}"
            if device["friendly_name"] in readings:
                reading = readings[device["friendly_name"]]
                summary += f", {reading['value']:g} {reading['unit']}"
            summaries.append(summary)
        return {
            "devices": summaries,
            "drive_controller": "online (fixed, watchdog protected)",
            "free_native_pins": resources["free_native"],
            "warnings": warnings or ["none"],
        }
