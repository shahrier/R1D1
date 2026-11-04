"""Original Create OI: one serial owner, bounded motion, independent worker stop.

Serial setup/send/drive/stop helpers are copied from the owner's scout-mission.
The new sensor/controller code fails closed on missing packets or any hazard.
"""
import fcntl
import math
import multiprocessing as mp
import os
import select
import signal
import struct
import termios
import time
from pathlib import Path

PORT = "/dev/ttyUSB0"


def open_port():
    fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
    a = termios.tcgetattr(fd)
    a[4] = a[5] = termios.B57600
    a[2] &= ~termios.CSIZE; a[2] |= termios.CS8
    a[2] &= ~(termios.PARENB | termios.CSTOPB)
    if hasattr(termios, "CRTSCTS"): a[2] &= ~termios.CRTSCTS
    a[2] |= (termios.CREAD | termios.CLOCAL)
    a[0] &= ~(termios.IGNBRK | termios.BRKINT | termios.ISTRIP | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON | termios.PARMRK)
    a[1] &= ~termios.OPOST
    a[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def send(fd, data): os.write(fd, bytes(data))


def drive(fd, vel):
    send(fd, [137] + list(struct.pack(">h", vel)) + [0x80, 0x00])


def stop(fd): drive(fd, 0)


def read_exact(fd, n, timeout=0.20):
    data = b""
    deadline = time.monotonic() + timeout
    while len(data) < n and time.monotonic() < deadline:
        if select.select([fd], [], [], min(.02, max(0, deadline - time.monotonic())))[0]:
            chunk = os.read(fd, n - len(data))
            if not chunk:
                raise RuntimeError("Serial device disconnected")
            data += chunk
    if len(data) != n:
        raise RuntimeError("Sensor timeout or incomplete packet")
    return data


def decode_sensors(data):
    if len(data) != 26:
        raise ValueError("Expected 26-byte OI group 0")
    if data[0] > 31 or any(x > 1 for x in data[1:7]) or data[8:10] != b"\0\0":
        raise RuntimeError("Invalid sensor framing")
    return {"bump": data[0] & 3, "wheel_drop": data[0] & 28,
            "cliff": list(data[2:6]), "virtual_wall": data[6],
            "overcurrent": data[7], "distance_mm": struct.unpack(">h", data[12:14])[0],
            "angle_degrees": struct.unpack(">h", data[14:16])[0],
            "battery_mv": struct.unpack(">H", data[17:19])[0]}


def hazard(sensors):
    return bool(sensors["bump"] or sensors["wheel_drop"] or any(sensors["cliff"])
                or sensors["virtual_wall"] or sensors["overcurrent"] & 24)


def validate_motion(action):
    if action.get("action") == "drive":
        amount = action.get("distance_mm")
        if type(amount) is not int or not 1 <= amount <= 500:
            raise ValueError("Drive must be 1..500 mm forward; reverse is disabled")
    elif action.get("action") == "turn":
        amount = action.get("degrees")
        if type(amount) is not int or not 1 <= abs(amount) <= 180:
            raise ValueError("Turn must be a nonzero integer within +/-180 degrees")
    else:
        raise ValueError("Not a motion action")
    return amount


def update_pose(pose, sensors):
    angle = math.radians(sensors["angle_degrees"])
    heading = math.radians(pose["heading_degrees"])
    pose["x_mm"] += sensors["distance_mm"] * math.cos(heading + angle / 2)
    pose["y_mm"] += sensors["distance_mm"] * math.sin(heading + angle / 2)
    pose["heading_degrees"] = (pose["heading_degrees"] + sensors["angle_degrees"]) % 360


def _worker(connection, root):
    # Spawned, not forked: parent death closes its pipe endpoint even during motion.
    fd = None
    lock = None
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        lock = (Path(root) / "robot.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = open_port()
        send(fd, [128]); time.sleep(.2)
        send(fd, [131]); time.sleep(.2)
        stop(fd)
        termios.tcflush(fd, termios.TCIFLUSH)
        def poll():
            send(fd, [142, 0])
            result = decode_sensors(read_exact(fd, 26))
            # Keep all hardware samples, including the one that causes an abort.
            import json
            with (Path(root) / "sensors.jsonl").open("a") as stream:
                stream.write(json.dumps({"time": time.time(), **result}) + "\n")
            return result
        first = poll()
        if hazard(first):
            raise RuntimeError("Initial sensor hazard; human intervention required")
        pose = {"x_mm": 0.0, "y_mm": 0.0, "heading_degrees": 0.0,
                "drift_warning": "Relative wheel odometry only; slip and drift accumulate. Not a map."}
        travelled = 0
        connection.send({"ready": True, "pose": pose, "sensors": first})
        while True:
            if (Path(root) / "STOP").exists():
                break
            if not connection.poll(.1):
                stop(fd)
                continue
            action = connection.recv()
            if action["action"] == "close":
                break
            if action["action"] in {"stop", "status"}:
                stop(fd)
                sensors = poll()
                update_pose(pose, sensors)
                travelled += abs(sensors["distance_mm"])
                send(fd, [142, 39])
                velocity = struct.unpack(">h", read_exact(fd, 2))[0]
                connection.send({"pose": dict(pose), "travelled_mm": travelled,
                                 "sensors": sensors, "reported_velocity_mm_s": velocity})
                continue
            amount = validate_motion(action)
            before = poll()
            update_pose(pose, before)
            if hazard(before):
                raise RuntimeError("Pre-motion sensor hazard")
            send(fd, [142, 35])
            if read_exact(fd, 1) != b"\x02":
                raise RuntimeError("Create is not in SAFE mode; refusing motion")
            if action["action"] == "drive":
                drive(fd, 80)
                duration = amount / 80 + 1.5
            else:
                radius = 1 if amount > 0 else -1
                send(fd, [137] + list(struct.pack(">hh", 60, radius)))
                duration = abs(amount) / 20 + 2
            deadline = time.monotonic() + min(duration, 12)
            progress = 0
            readings = []
            while True:
                if (Path(root) / "STOP").exists() or connection.poll():
                    raise RuntimeError("Emergency stop or interrupted command")
                if time.monotonic() > deadline:
                    raise RuntimeError("Motion deadline exceeded; stopped")
                sensors = poll()
                readings.append(sensors)
                update_pose(pose, sensors)
                travelled += abs(sensors["distance_mm"])
                if hazard(sensors):
                    raise RuntimeError("Motion hazard; stopped without reversing")
                progress += sensors["distance_mm"] if action["action"] == "drive" else sensors["angle_degrees"]
                signed_progress = progress if amount > 0 else -progress
                if signed_progress >= abs(amount):
                    break
                time.sleep(.03)
            stop(fd)
            after = poll()
            update_pose(pose, after)
            travelled += abs(after["distance_mm"])
            if hazard(after):
                raise RuntimeError("Post-motion sensor hazard")
            connection.send({"pose": dict(pose), "sensors_before": before, "sensors_after": after,
                             "sensor_samples": readings, "travelled_mm": travelled})
    except (Exception, KeyboardInterrupt) as exc:
        if fd is not None:
            try: stop(fd)
            except OSError: pass
        try: connection.send({"error": str(exc) or "Controller interrupted"})
        except (BrokenPipeError, EOFError, OSError): pass
    finally:
        if fd is not None:
            try: stop(fd)
            finally: os.close(fd)
        if lock is not None:
            lock.close()
        connection.close()


class Robot:
    def __init__(self, root):
        ctx = mp.get_context("spawn")
        self.connection, child = ctx.Pipe()
        self.process = ctx.Process(target=_worker, args=(child, str(root)))
        self.process.start()
        child.close()
        try:
            self.state = self.receive(5)
        except BaseException:
            self.close()
            raise

    def receive(self, timeout=15):
        if not self.connection.poll(timeout):
            self.close()
            raise RuntimeError("Robot worker timed out")
        result = self.connection.recv()
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    def execute(self, action):
        if action["action"] not in {"stop", "status"}:
            validate_motion(action)
        self.connection.send(action)
        self.state = self.receive()
        return self.state

    def close(self):
        if getattr(self, "connection", None):
            self.connection.close()
        if getattr(self, "process", None):
            self.process.join(1)
            if self.process.is_alive():
                self.process.terminate()  # worker catches SIGTERM and sends STOP
                self.process.join(1)


class FakeRobot:
    def __init__(self):
        self.state = {"pose": {"x_mm": 0.0, "y_mm": 0.0, "heading_degrees": 0.0,
                              "drift_warning": "SIMULATION; relative pose only"}, "travelled_mm": 0}
    def execute(self, action):
        if action["action"] not in {"stop", "status"}:
            amount = validate_motion(action)
            update_pose(self.state["pose"], {"distance_mm": amount if action["action"] == "drive" else 0,
                        "angle_degrees": amount if action["action"] == "turn" else 0})
            if action["action"] == "drive":
                self.state["travelled_mm"] += amount
        return json_copy(self.state)
    def close(self):
        pass


def json_copy(value):
    import json
    return json.loads(json.dumps(value))
