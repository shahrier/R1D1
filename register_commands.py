"""Register only inspection, acknowledgment, status and stop with Muse Gadget."""
import json
import subprocess
import tempfile
from pathlib import Path


def definitions(root):
    base = ["/usr/bin/python3", str(root / "gadget_command.py")]
    return {
        "r1d1.locate": {"description": "Look for a target in the stationary camera view using SAM 3.1, confirm a candidate with Wonder, and send an outlined photo to the owner. Reports image centering only, never distance or navigability. Does not move the robot.",
            "exec": [str(root / ".venv/bin/python"), str(root / "gadget_command.py"), "locate"],
            "optional": {"target": {"type": "string", "description": "Short object phrase, e.g. black suitcase"}}, "timeout_ms": 120000},
        "r1d1.inspect": {"description": "Take a stationary R1D1 camera observation and look for a target. Sends a photo report to the owner unless the same observation was explicitly acknowledged. Does not move the robot.",
            "exec": base + ["inspect"], "optional": {"target": {"type": "string", "description": "Visible object to inspect, e.g. suitcase"}}, "timeout_ms": 120000},
        "r1d1.acknowledge": {"description": "Record an explicit owner acknowledgment of the latest target observation for one hour. Call only after the human owner says to ignore or acknowledge that specific observation. Never infer consent, acknowledge on the robot's behalf, or suppress changed/uncertain scenes.",
            "exec": base + ["acknowledge"], "required": {
                "event_id": {"type": "string", "description": "Latest observation event identifier from r1d1.inspect"},
                "owner_note": {"type": "string", "description": "The owner's explicit acknowledgment, e.g. That's mine; ignore it for this demo"}}, "timeout_ms": 10000},
        "r1d1.status": {"description": "Read the bedroom demo's latest observation and acknowledgment state.",
            "exec": base + ["status"], "timeout_ms": 10000},
        "r1d1.stop": {"description": "Latch a stop request for R1D1's local mission controller. Does not clear itself. If the robot is unresponsive use its physical power cutoff.",
            "exec": base + ["stop"], "timeout_ms": 10000},
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    destination = "/etc/musegadget/commands.d"
    subprocess.run(["sudo", "-n", "install", "-d", "-m", "755", destination], check=True)
    with tempfile.TemporaryDirectory() as folder:
        for name, definition in definitions(root).items():
            source = Path(folder) / (name + ".json")
            source.write_text(json.dumps(definition, indent=2))
            subprocess.run(["sudo", "-n", "install", "-m", "644", str(source), destination + "/" + source.name], check=True)
    subprocess.run(["sudo", "-n", "systemctl", "restart", "musegadget"], check=True)
    print("Registered R1D1 locate, inspect, acknowledge, status and stop. No motion commands exposed.")
