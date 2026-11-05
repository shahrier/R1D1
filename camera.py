"""Fresh primary-camera snapshots; no metric depth."""
import io
import json
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image

CONFIG_FILE = Path(__file__).resolve().parent / "camera-config.json"


def config():
    value = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {"primary": "picam"}
    if value.get("primary") not in {"webcam", "picam"}:
        raise ValueError("Invalid camera configuration")
    return value


def capture_photo(destination, source=None):
    destination = Path(destination)
    source = source or config()["primary"]
    if source == "webcam":
        try:
            response = requests.get("http://127.0.0.1:8080/snap", params={"after": time.monotonic()}, timeout=(2, 5))
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError("Fresh webcam capture failed: " + type(exc).__name__) from None
        try:
            age = float(response.headers["X-Frame-Age-Seconds"])
            timestamp = float(response.headers["X-Frame-Monotonic"])
        except (KeyError, ValueError):
            raise RuntimeError("Webcam service does not supply frame freshness") from None
        if not (0 <= age <= 1.5 and 0 <= time.monotonic() - timestamp <= 2):
            raise RuntimeError("Webcam frame stale; refusing to use for motion")
        if len(response.content) > 4_000_000:
            raise RuntimeError("Webcam frame exceeds size limit")
        with Image.open(io.BytesIO(response.content)) as image:
            image.load()
            image = image.convert("RGB")
            image.thumbnail((1280, 720))
            image.save(destination, "JPEG", quality=85)
    elif source == "picam":
        subprocess.run([str(Path.home() / "scout-snap"), str(destination)],
                       capture_output=True, check=True, timeout=15)
        with Image.open(destination) as image:
            image.load()
        timestamp = time.monotonic()
    else:
        raise ValueError("Unknown camera")
    return {"source": source, "captured_monotonic": timestamp,
            "depth_capability": "uncalibrated RGB; no metric depth"}
