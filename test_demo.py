import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from inspect_demo import Store, acknowledge, inspect, should_suppress, validate_observation
from oi import decode_sensors, hazard, FakeRobot, _worker


class DemoTests(unittest.TestCase):


    def test_observation_acknowledgment_reinspection(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            first = inspect(store, fake=True, send=True)
            self.assertFalse(first["suppressed"])
            acknowledge(store, first["event_id"], "That's mine; ignore it for this demo")
            second = inspect(store, fake=True, send=True)
            self.assertTrue(second["suppressed"])
            third = inspect(store, scope="another-room", fake=True)
            self.assertFalse(third["suppressed"])
            with self.assertRaises(ValueError):
                acknowledge(store, first["event_id"], "Stale acknowledgment")
            rows = [json.loads(line) for line in (Path(folder) / "inspection.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 4)

    def test_changed_uncertain_dark_expired_and_different_targets_alert(self):
        observation = {"target_present": True, "lighting": "good", "acknowledged_comparison": "same"}
        ack = {"target": "suitcase", "scope": "bedroom-demo", "expires_at": time.time() + 60}
        self.assertTrue(should_suppress(observation, ack, "suitcase", "bedroom-demo", 80))
        for comparison in ("changed", "uncertain", "unavailable"):
            self.assertFalse(should_suppress({**observation, "acknowledged_comparison": comparison}, ack,
                                            "suitcase", "bedroom-demo", 80))
        self.assertFalse(should_suppress(observation, ack, "box", "bedroom-demo", 80))
        self.assertFalse(should_suppress(observation, ack, "suitcase", "bedroom-demo", 4))
        self.assertFalse(should_suppress({**observation, "lighting": "dim"}, ack,
                                        "suitcase", "bedroom-demo", 80))
        self.assertFalse(should_suppress(observation, {**ack, "expires_at": 0},
                                        "suitcase", "bedroom-demo", 80))

    def test_invalid_observation_rejected(self):
        with self.assertRaises(ValueError):
            validate_observation({"target_present": "yes"})


    def test_sensor_decoding_and_hazards(self):
        data = bytearray(26)
        data[12:14] = (100).to_bytes(2, "big", signed=True)
        data[14:16] = (-20).to_bytes(2, "big", signed=True)
        sensors = decode_sensors(data)
        self.assertEqual(sensors["distance_mm"], 100)
        self.assertEqual(sensors["angle_degrees"], -20)
        self.assertFalse(hazard(sensors))
        for index, value in [(0, 1), (0, 4), (2, 1), (5, 1), (6, 1), (7, 16)]:
            fault = bytearray(data)
            fault[index] = value
            self.assertTrue(hazard(decode_sensors(fault)))
        with self.assertRaises(ValueError):
            decode_sensors(b"short")

    def test_simulated_pose_accumulates_signed_turns(self):
        robot = FakeRobot()
        robot.execute({"action": "turn", "degrees": 90})
        result = robot.execute({"action": "drive", "distance_mm": 100})
        self.assertAlmostEqual(result["pose"]["x_mm"], 0)
        self.assertAlmostEqual(result["pose"]["y_mm"], 100)
        self.assertEqual(result["travelled_mm"], 100)

    def test_worker_stops_on_hazard_and_sensor_timeout(self):
        class Connection:
            def __init__(self):
                self.commands = [{"action": "drive", "distance_mm": 100}]
                self.sent = []
            def poll(self, timeout=None):
                return bool(self.commands) if timeout is not None else False
            def recv(self):
                return self.commands.pop(0)
            def send(self, value):
                self.sent.append(value)
            def close(self):
                pass
        clear = bytes(26)
        dropped = bytes([4]) + bytes(25)
        for failure in (dropped, RuntimeError("Sensor timeout")):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as folder:
                connection = Connection()
                with patch("oi.open_port", return_value=123), patch("oi.os.close"), \
                     patch("oi.termios.tcflush"), patch("oi.time.sleep"), \
                     patch("oi.signal.signal"), patch("oi.send") as send, \
                     patch("oi.read_exact", side_effect=[clear, clear, b"\x02", failure]):
                    _worker(connection, folder)
                    self.assertIn("error", connection.sent[-1])
                    self.assertEqual(send.call_args_list[-1].args, (123, [137, 0, 0, 128, 0]))
                    self.assertFalse(any(call.args[1][:3] == [137, 255, 176] for call in send.call_args_list))


if __name__ == "__main__":
    unittest.main()
