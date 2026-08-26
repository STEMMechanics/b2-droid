"""Persistent hardware inventory and deterministic resource validation."""

import json
import re
import uuid
from datetime import datetime, timezone


class HardwareValidationError(ValueError):
    """A candidate configuration is unsafe, conflicting, or malformed."""


NATIVE_PINS = tuple([f"D{i}" for i in range(14)] + [f"A{i}" for i in range(6)])
FIXED_ALLOCATIONS = {
    "D0": "USB serial RX", "D1": "USB serial TX",
    "D3": "drive controller left PWM", "D5": "drive controller left direction",
    "D6": "drive controller left direction", "D7": "drive controller right direction",
    "D8": "drive controller right direction", "D9": "drive controller right PWM",
    "D10": "MAX7219 chip select", "D11": "MAX7219 data",
    "D13": "MAX7219 clock", "A4": "I2C SDA", "A5": "I2C SCL",
}
ANALOGUE_PINS = {f"A{i}" for i in range(6)}
PWM_PINS = {"D3", "D5", "D6", "D9", "D10", "D11"}
INTERRUPT_PINS = {"D2", "D3"}
I2C_TYPES = {"compass", "mcp23008", "pca9685"}
SUPPORTED_TYPES = {
    "ultrasonic", "ir_distance", "hall_sensor", "compass", "mcp23008",
    "l298n", "servo", "pca9685",
}

DESCRIPTORS = {
    "ultrasonic": {"required": ("trigger", "echo"), "kinds": {"trigger": "gpio", "echo": "gpio"}},
    "ir_distance": {"required": ("analogue",), "kinds": {"analogue": "analogue"}},
    "hall_sensor": {"required": ("input",), "kinds": {"input": "gpio"}},
    "compass": {"required": (), "connection": "i2c"},
    "mcp23008": {"required": (), "connection": "i2c"},
    "pca9685": {"required": (), "connection": "i2c"},
    # Arduino's Servo timer can generate pulses on an ordinary native GPIO.
    # Future controller channels are represented through the same signal role.
    "servo": {"required": ("signal",), "kinds": {"signal": "output"}},
    "l298n": {"required": ("in1", "in2", "in3", "in4"), "kinds": {
        "in1": "output", "in2": "output", "in3": "output", "in4": "output",
        "ena": "pwm", "enb": "pwm",
    }},
}


def normalize_pin(value):
    if not isinstance(value, str):
        raise HardwareValidationError("pin names must be strings")
    pin = value.strip().upper()
    match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*:\s*(?:GP|GPIO)([0-7])", pin)
    if match:
        return f"{match.group(1).lower()}:GP{match.group(2)}"
    if re.fullmatch(r"(?:D(?:[0-9]|1[0-3])|A[0-5])", pin):
        return pin
    match = re.fullmatch(r"PCA9685_([A-Z0-9_]+):CH(?:ANNEL)?(1[0-5]|[0-9])", pin)
    if match:
        return f"pca9685_{match.group(1).lower()}:CH{match.group(2)}"
    raise HardwareValidationError(f"unknown pin or resource {value!r}")


def parse_i2c_address(value):
    if isinstance(value, bool):
        raise HardwareValidationError("invalid I2C address")
    try:
        address = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise HardwareValidationError(f"invalid I2C address {value!r}")
    if not 0x08 <= address <= 0x77:
        raise HardwareValidationError("I2C address must be between 0x08 and 0x77")
    return address


class HardwareRegistry:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def ensure_schema(self):
        with self.connection_factory() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS hardware_devices(
                device_id TEXT PRIMARY KEY, friendly_name TEXT NOT NULL UNIQUE,
                device_type TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                connection_type TEXT NOT NULL, pins_json TEXT NOT NULL DEFAULT '{}',
                i2c_address INTEGER, parent_device TEXT,
                config_json TEXT NOT NULL DEFAULT '{}', last_status TEXT NOT NULL DEFAULT 'configured',
                last_test_at TEXT, FOREIGN KEY(parent_device) REFERENCES hardware_devices(friendly_name)
            )""")

    def list(self, enabled_only=False):
        self.ensure_schema()
        query = "SELECT * FROM hardware_devices"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY friendly_name"
        with self.connection_factory() as db:
            rows = db.execute(query).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, name_or_id):
        self.ensure_schema()
        with self.connection_factory() as db:
            row = db.execute(
                "SELECT * FROM hardware_devices WHERE friendly_name=? OR device_id=?",
                (name_or_id, name_or_id),
            ).fetchone()
        return self._decode(row) if row else None

    @staticmethod
    def _decode(row):
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["pins"] = json.loads(item.pop("pins_json"))
        item["config"] = json.loads(item.pop("config_json"))
        return item

    def validate(self, candidate, replacing=None):
        if not isinstance(candidate, dict):
            raise HardwareValidationError("hardware configuration must be an object")
        kind = candidate.get("device_type")
        name = candidate.get("friendly_name")
        if kind not in SUPPORTED_TYPES:
            raise HardwareValidationError(f"unsupported device type {kind!r}")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name):
            raise HardwareValidationError("friendly name must use lowercase letters, digits, and underscores")
        descriptor = DESCRIPTORS[kind]
        raw_pins = candidate.get("pins", {})
        if not isinstance(raw_pins, dict):
            raise HardwareValidationError("pins must be an object")
        pins = {str(role).lower(): normalize_pin(pin) for role, pin in raw_pins.items()}
        missing = [role for role in descriptor["required"] if role not in pins]
        if missing:
            raise HardwareValidationError("missing pin assignments: " + ", ".join(missing))
        if len(set(pins.values())) != len(pins):
            raise HardwareValidationError("one resource cannot fill multiple roles on the same device")

        i2c_address = candidate.get("i2c_address")
        if kind in I2C_TYPES:
            if pins:
                raise HardwareValidationError(f"{kind} uses the I2C bus on A4/A5, not ordinary GPIO pins")
            if i2c_address is not None:
                i2c_address = parse_i2c_address(i2c_address)
        elif i2c_address is not None:
            raise HardwareValidationError(f"{kind} does not use an I2C address")

        existing = [d for d in self.list() if d["friendly_name"] != replacing]
        if any(d["friendly_name"] == name for d in existing):
            raise HardwareValidationError(f"hardware named {name} already exists")
        allocated = {pin: d["friendly_name"] for d in existing if d["enabled"] for pin in d["pins"].values()}
        by_name = {d["friendly_name"]: d for d in existing}
        for role, pin in pins.items():
            if pin in FIXED_ALLOCATIONS:
                raise HardwareValidationError(f"{pin} already controls {FIXED_ALLOCATIONS[pin]}")
            if pin in allocated:
                raise HardwareValidationError(f"{pin} is already allocated to {allocated[pin]}")
            if ":GP" in pin:
                parent = pin.split(":", 1)[0]
                device = by_name.get(parent)
                if not device or device["device_type"] != "mcp23008" or not device["enabled"]:
                    raise HardwareValidationError(f"parent MCP23008 {parent} does not exist or is disabled")
                if descriptor.get("kinds", {}).get(role) in {"analogue", "pwm"}:
                    raise HardwareValidationError(f"{pin} cannot provide analogue input or hardware PWM")
            elif ":CH" in pin:
                parent = pin.split(":", 1)[0]
                device = by_name.get(parent)
                if not device or device["device_type"] != "pca9685" or not device["enabled"]:
                    raise HardwareValidationError(f"parent PCA9685 {parent} does not exist or is disabled")
            else:
                requirement = descriptor.get("kinds", {}).get(role)
                if requirement == "analogue" and pin not in ANALOGUE_PINS:
                    raise HardwareValidationError(f"{role} requires an analogue pin")
                if requirement == "pwm" and pin not in PWM_PINS:
                    raise HardwareValidationError(f"{role} requires a PWM-capable pin")
        config = candidate.get("config", {})
        if not isinstance(config, dict):
            raise HardwareValidationError("config must be an object")
        if kind == "hall_sensor" and config.get("pulse_counting", True):
            pin = pins["input"]
            if pin not in INTERRUPT_PINS and config.get("require_interrupt", False):
                raise HardwareValidationError(f"{pin} is not interrupt-capable; use D2")
            if pin not in INTERRUPT_PINS:
                config = dict(config, warning="pulse counting is polled; D2 is recommended")
        if i2c_address is not None:
            for device in existing:
                if device["enabled"] and device["i2c_address"] == i2c_address:
                    raise HardwareValidationError(
                        f"I2C address 0x{i2c_address:02X} is already registered to {device['friendly_name']}"
                    )
        connection = descriptor.get("connection") or (
            "expander" if any(":" in p for p in pins.values()) else
            "analogue" if kind == "ir_distance" else "gpio"
        )
        parent = candidate.get("parent_device")
        inferred = {pin.split(":", 1)[0] for pin in pins.values() if ":" in pin}
        if len(inferred) > 1:
            raise HardwareValidationError("one device cannot span multiple parent controllers")
        parent = next(iter(inferred), parent)
        return {
            "device_id": candidate.get("device_id") or uuid.uuid4().hex,
            "friendly_name": name, "device_type": kind,
            "enabled": bool(candidate.get("enabled", True)),
            "connection_type": connection, "pins": pins,
            "i2c_address": i2c_address, "parent_device": parent,
            "config": config, "last_status": candidate.get("last_status", "configured"),
            "last_test_at": candidate.get("last_test_at"),
        }

    def add(self, candidate):
        device = self.validate(candidate)
        self.ensure_schema()
        with self.connection_factory() as db:
            db.execute("""INSERT INTO hardware_devices VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
                device["device_id"], device["friendly_name"], device["device_type"],
                int(device["enabled"]), device["connection_type"], json.dumps(device["pins"], sort_keys=True),
                device["i2c_address"], device["parent_device"], json.dumps(device["config"], sort_keys=True),
                device["last_status"], device["last_test_at"],
            ))
        return device

    def remove(self, name_or_id):
        device = self.get(name_or_id)
        if not device:
            raise HardwareValidationError(f"unknown hardware {name_or_id}")
        dependants = [d["friendly_name"] for d in self.list() if d["parent_device"] == device["friendly_name"]]
        if dependants:
            raise HardwareValidationError("remove dependent hardware first: " + ", ".join(dependants))
        with self.connection_factory() as db:
            db.execute("DELETE FROM hardware_devices WHERE device_id=?", (device["device_id"],))
        return device

    def update_status(self, name_or_id, status, successful_test=False):
        tested = datetime.now(timezone.utc).isoformat() if successful_test else None
        with self.connection_factory() as db:
            if successful_test:
                db.execute("UPDATE hardware_devices SET last_status=?,last_test_at=? WHERE friendly_name=? OR device_id=?",
                           (status, tested, name_or_id, name_or_id))
            else:
                db.execute("UPDATE hardware_devices SET last_status=? WHERE friendly_name=? OR device_id=?",
                           (status, name_or_id, name_or_id))

    def resources(self):
        allocated = dict(FIXED_ALLOCATIONS)
        expanders = {}
        devices = [device for device in self.list() if device["enabled"]]
        for device in devices:
            for pin in device["pins"].values():
                allocated[pin] = device["friendly_name"]
        for device in devices:
            if device["device_type"] == "mcp23008":
                expanders[device["friendly_name"]] = [
                    f"{device['friendly_name']}:GP{i}" for i in range(8)
                    if f"{device['friendly_name']}:GP{i}" not in allocated
                ]
            if device["device_type"] == "pca9685":
                expanders[device["friendly_name"]] = [
                    f"{device['friendly_name']}:CH{i}" for i in range(16)
                    if f"{device['friendly_name']}:CH{i}" not in allocated
                ]
        return {
            "allocated": allocated,
            "free_native": [pin for pin in NATIVE_PINS if pin not in allocated],
            "free_child_resources": expanders,
        }
