"""Machine-parseable, line-oriented Arduino hardware protocol."""

import re


class HardwareProtocolError(RuntimeError):
    pass


def parse_response(line):
    text = line.decode("ascii", "replace").strip() if isinstance(line, bytes) else str(line).strip()
    if text == "ACK" or text.startswith("ACK:"):
        return {"kind": "ack", "detail": text[4:] if text.startswith("ACK:") else ""}
    match = re.fullmatch(r"ERR:([A-Z0-9_]+):(.*)", text)
    if match:
        return {"kind": "error", "code": match.group(1), "message": match.group(2)}
    match = re.fullmatch(r"I2C:0x([0-9A-Fa-f]{2})", text)
    if match:
        return {"kind": "i2c", "address": int(match.group(1), 16)}
    match = re.fullmatch(r"DEVICE:([a-z][a-z0-9_]*):(OK|UNAVAILABLE|UNVERIFIED)(?::(.*))?", text)
    if match:
        return {"kind": "device", "device": match.group(1), "status": match.group(2).lower(), "value": match.group(3)}
    match = re.fullmatch(r"READ:([a-z][a-z0-9_]*):([A-Z_]+):(-?[0-9]+(?:\.[0-9]+)?)", text)
    if match:
        return {"kind": "reading", "device": match.group(1), "unit": match.group(2).lower(), "value": float(match.group(3))}
    raise HardwareProtocolError(f"malformed Arduino response: {text!r}")


def encode_device(device):
    fields = [device["friendly_name"], device["device_type"]]
    fields.extend(f"{role}={pin}" for role, pin in sorted(device["pins"].items()))
    if device.get("i2c_address") is not None:
        fields.append(f"address=0x{device['i2c_address']:02X}")
    return "HW:ADD:" + ":".join(fields)


class ArduinoHardwareProtocol:
    def __init__(self, serial_port, lock, timeout_lines=40):
        self.serial = serial_port
        self.lock = lock
        self.timeout_lines = timeout_lines

    def request(self, command, terminal=("ack", "error")):
        responses = []
        with self.lock:
            self.serial.write((command + "\n").encode("ascii"))
            self.serial.flush()
            for _ in range(self.timeout_lines):
                raw = self.serial.readline()
                if not raw:
                    break
                try:
                    parsed = parse_response(raw)
                except HardwareProtocolError:
                    continue  # Ignore legacy speed/status chatter.
                responses.append(parsed)
                if parsed["kind"] in terminal:
                    break
        if not responses or responses[-1]["kind"] not in terminal:
            raise HardwareProtocolError(f"Arduino did not acknowledge {command}")
        if responses[-1]["kind"] == "error":
            error = responses[-1]
            raise HardwareProtocolError(f"{error['code']}: {error['message']}")
        return responses

    def reset(self):
        return self.request("HW:RESET")

    def add(self, device):
        return self.request(encode_device(device))

    def remove(self, name):
        return self.request(f"HW:REMOVE:{name}")

    def scan_i2c(self):
        return [r["address"] for r in self.request("HW:I2C_SCAN") if r["kind"] == "i2c"]

    def read(self, name):
        responses = self.request(f"HW:READ:{name}")
        return next((r for r in responses if r["kind"] in {"reading", "device"}), responses[-1])

    def test(self, name):
        responses = self.request(f"HW:TEST:{name}")
        return next((r for r in responses if r["kind"] in {"reading", "device"}), responses[-1])
