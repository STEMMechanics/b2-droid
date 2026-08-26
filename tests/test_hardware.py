"""Hardware registry, protocol, provisioning, and intent safety contracts."""

import tempfile
import threading
import unittest
from pathlib import Path

from b2.commands import parse_hardware_intent, validate_hardware_candidate
from b2.hardware import HardwareService
from b2.hardware_protocol import ArduinoHardwareProtocol, HardwareProtocolError, parse_response
from b2.hardware_registry import HardwareRegistry, HardwareValidationError, parse_i2c_address
from b2.storage import DatabaseService


class FakeSerial:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.writes = []

    def write(self, data):
        self.writes.append(data.decode().strip())

    def flush(self):
        pass

    def readline(self):
        return self.responses.pop(0) if self.responses else b""


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = DatabaseService(Path(self.temporary.name) / "b2.sqlite3")
        self.registry = HardwareRegistry(self.database.connection)
        self.registry.ensure_schema()

    def tearDown(self):
        self.temporary.cleanup()

    def test_fixed_and_dynamic_pin_conflicts(self):
        with self.assertRaisesRegex(HardwareValidationError, "D7 already controls"):
            self.registry.add({
                "friendly_name": "bad_sonar", "device_type": "ultrasonic",
                "pins": {"trigger": "D4", "echo": "D7"},
            })
        self.registry.add({
            "friendly_name": "front_sonar", "device_type": "ultrasonic",
            "pins": {"trigger": "A1", "echo": "A2"},
        })
        with self.assertRaisesRegex(HardwareValidationError, "already allocated"):
            self.registry.add({
                "friendly_name": "other_sonar", "device_type": "ultrasonic",
                "pins": {"trigger": "D4", "echo": "A2"},
            })

    def test_analogue_pwm_and_interrupt_capabilities(self):
        with self.assertRaisesRegex(HardwareValidationError, "analogue"):
            self.registry.add({
                "friendly_name": "front_ir", "device_type": "ir_distance",
                "pins": {"analogue": "D4"},
            })
        with self.assertRaisesRegex(HardwareValidationError, "PWM"):
            self.registry.add({
                "friendly_name": "motor_2", "device_type": "l298n",
                "pins": {"in1": "D2", "in2": "D4", "in3": "D12", "in4": "A0", "ena": "A1"},
            })
        with self.assertRaisesRegex(HardwareValidationError, "interrupt-capable"):
            self.registry.add({
                "friendly_name": "wheel_hall", "device_type": "hall_sensor",
                "pins": {"input": "D4"}, "config": {"require_interrupt": True},
            })
        hall = self.registry.add({
            "friendly_name": "wheel_hall", "device_type": "hall_sensor",
            "pins": {"input": "D2"},
        })
        self.assertNotIn("warning", hall["config"])

    def test_i2c_address_and_bus_validation(self):
        self.assertEqual(parse_i2c_address("0x20"), 32)
        self.assertEqual(parse_i2c_address("64"), 64)
        with self.assertRaises(HardwareValidationError):
            parse_i2c_address("0x78")
        with self.assertRaisesRegex(HardwareValidationError, "I2C bus"):
            self.registry.add({
                "friendly_name": "compass", "device_type": "compass",
                "pins": {"sda": "D6", "scl": "D7"},
            })
        self.registry.add({
            "friendly_name": "io", "device_type": "mcp23008", "pins": {},
            "i2c_address": "0x20",
        })
        with self.assertRaisesRegex(HardwareValidationError, "already registered"):
            self.registry.add({
                "friendly_name": "compass", "device_type": "compass", "pins": {},
                "i2c_address": "0x20",
            })

    def test_expander_allocation_and_parent_removal(self):
        with self.assertRaisesRegex(HardwareValidationError, "does not exist"):
            self.registry.add({
                "friendly_name": "motor_2", "device_type": "l298n",
                "pins": {f"in{i + 1}": f"io:GP{i}" for i in range(4)},
            })
        self.registry.add({"friendly_name": "io", "device_type": "mcp23008", "pins": {}, "i2c_address": 32})
        self.registry.add({
            "friendly_name": "motor_2", "device_type": "l298n",
            "pins": {f"in{i + 1}": f"io:GP{i}" for i in range(4)},
        })
        self.assertEqual(self.registry.resources()["free_child_resources"]["io"], [f"io:GP{i}" for i in range(4, 8)])
        with self.assertRaisesRegex(HardwareValidationError, "dependent"):
            self.registry.remove("io")

    def test_add_remove_and_persistence_reload(self):
        saved = self.registry.add({
            "friendly_name": "front_ir", "device_type": "ir_distance",
            "pins": {"analogue": "A0"},
        })
        restored = HardwareRegistry(self.database.connection).get(saved["device_id"])
        self.assertEqual(restored["pins"], {"analogue": "A0"})
        self.registry.remove("front_ir")
        self.assertIsNone(self.registry.get("front_ir"))

    def test_protocol_parsing(self):
        self.assertEqual(parse_response("I2C:0x20")["address"], 32)
        self.assertEqual(parse_response("READ:front_sonar:CM:84.2")["value"], 84.2)
        self.assertEqual(parse_response("DEVICE:compass:OK")["status"], "ok")
        with self.assertRaises(HardwareProtocolError):
            parse_response("friendly but unstructured")

    def test_startup_reprovisioning_and_unavailable_arduino(self):
        self.registry.add({
            "friendly_name": "front_ir", "device_type": "ir_distance",
            "pins": {"analogue": "A0"},
        })
        serial = FakeSerial([b"ACK:RESET\n", b"ACK:ADD:front_ir\n"])
        service = HardwareService(self.registry, ArduinoHardwareProtocol(serial, threading.Lock()))
        self.assertEqual(service.provision(), {"configured": 1, "unavailable": 0})
        self.assertEqual(serial.writes[0], "HW:RESET")
        self.assertTrue(serial.writes[1].startswith("HW:ADD:front_ir:ir_distance"))
        unavailable = HardwareService(self.registry, None).provision()
        self.assertEqual(unavailable["unavailable"], 1)
        self.assertEqual(self.registry.get("front_ir")["last_status"], "unavailable")

    def test_intents_and_malformed_model_output(self):
        intent = parse_hardware_intent(
            "I've connected a front ultrasonic sensor with trigger on A1 and echo on A2."
        )
        self.assertEqual(intent["candidate"]["friendly_name"], "front_sonar")
        self.assertEqual(parse_hardware_intent("What pins do you still have free?")["action"], "resources")
        self.assertEqual(parse_hardware_intent("What hardware do you currently have connected?")["action"], "list")
        self.assertEqual(parse_hardware_intent("Scan your I2C bus.")["action"], "scan_i2c")
        motor = parse_hardware_intent(
            "I connected another L298N using MCP23008 pins 0 through 3."
        )
        self.assertEqual(motor["candidate"]["pins"]["in4"], "mcp23008_1:GP3")
        with self.assertRaises(ValueError):
            validate_hardware_candidate({"action": "add", "candidate": "do anything"})

    def test_firmware_keeps_motor_and_host_watchdogs(self):
        firmware = (Path(__file__).parents[1] / "arduino.ino").read_text(encoding="utf-8")
        self.assertIn("MOTOR_WATCHDOG_MS", firmware)
        self.assertIn("HOST_WATCHDOG_MS", firmware)
        self.assertIn("updateMotorWatchdog();", firmware)
        self.assertIn("updateHostWatchdog();", firmware)
        self.assertIn('if (command.startsWith("HW:"))', firmware)


if __name__ == "__main__":
    unittest.main()
