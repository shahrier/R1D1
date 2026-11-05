"""Fixed small hardware checks, never model-selected movement."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from inspect_demo import Store, now
from oi import Robot


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test", choices=["sensors", "drive", "turn", "stop"])
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / "runtime"
    store = Store(root)
    robot = None
    with store.locked():
        if (root / "STOP").exists():
            raise RuntimeError("STOP latch is set; inspect before clearing")
        try:
            robot = Robot(root)
            result = {"test": args.test, "timestamp": now(), "initial": json.loads(json.dumps(robot.state))}
            if args.test == "drive":
                result["motion"] = robot.execute({"action": "drive", "distance_mm": 100})
            elif args.test == "turn":
                result["motion"] = robot.execute({"action": "turn", "degrees": 15})
            elif args.test == "stop":
                started = time.monotonic()
                subprocess.run(["/usr/bin/python3", str(root.parent / "gadget_command.py"), "stop"],
                               input="{}", text=True, check=True, capture_output=True, timeout=5)
                robot.process.join(2)
                result.update({"worker_exited": not robot.process.is_alive(),
                               "elapsed_s": round(time.monotonic() - started, 3),
                               "stop_latched": (root / "STOP").exists()})
                if robot.process.is_alive():
                    raise RuntimeError("Stop adapter did not end controller promptly")
            if args.test != "stop":
                result["final"] = robot.execute({"action": "status"})
                if result["final"]["reported_velocity_mm_s"] != 0:
                    raise RuntimeError("Robot does not report zero commanded velocity")
            with (root / "hardware-checks.jsonl").open("a") as stream:
                stream.write(json.dumps(result) + "\n")
            print(json.dumps(result))
        finally:
            if robot:
                robot.close()


if __name__ == "__main__":
    main()
