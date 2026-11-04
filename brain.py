"""Small, bounded Meta Responses API client. Never logs credentials or image bytes."""
import base64
import json
import os
import time
from pathlib import Path

import requests
from PIL import Image, ImageStat

ENDPOINT = "https://api.meta.ai/v1/responses"
MODEL = "muse-wonder-1.0"


def image_info(path):
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height,
                "brightness": round(ImageStat.Stat(image.convert("L")).mean[0], 1)}


def prepare_image(source, destination):
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.thumbnail((1280, 720))
        image.save(destination, "JPEG", quality=80)
    return image_info(destination)


class Brain:
    def __init__(self, max_calls=25, deadline=None):
        self.key = os.environ.get("META_MODEL_API_KEY", "").strip()
        if not self.key:
            self.key = (Path.home() / ".config/r1d1/meta_api_key").read_text().strip()
        if not self.key:
            raise RuntimeError("Meta API key is empty")
        self.calls = 0
        self.max_calls = max_calls
        self.deadline = deadline or time.monotonic() + 600
        self.estimated_usd = 0.0
        self.last = None

    def ask(self, instruction, state, images=(), tokens=800):
        remaining = self.deadline - time.monotonic()
        if self.calls >= self.max_calls or remaining <= 0:
            raise RuntimeError("Model call or mission time budget exhausted")
        content = [{"type": "input_text", "text": json.dumps(state)}]
        for path in images:
            if image_info(path)["width"] > 1280 or image_info(path)["height"] > 720:
                raise ValueError("Image exceeds upload bounds")
            encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + encoded})
        self.calls += 1
        started = time.monotonic()
        try:
            response = requests.post(ENDPOINT, headers={"Authorization": "Bearer " + self.key},
                json={"model": MODEL, "instructions": instruction,
                      "reasoning": {"effort": "minimal"}, "max_output_tokens": tokens,
                      "store": False, "input": [{"role": "user", "content": content}]},
                timeout=(min(5, remaining), min(45, remaining)))
        except requests.RequestException as exc:
            raise RuntimeError("Meta API network failure: " + type(exc).__name__) from None
        if not response.ok:
            # Do not expose response bodies, headers, or the credential in exceptions.
            raise RuntimeError("Meta API HTTP " + str(response.status_code) + "; no automatic retry")
        data = response.json()
        usage = data.get("usage", {})
        cached = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        cost = ((usage.get("input_tokens", 0) - cached) * 4 + cached * .20
                + usage.get("output_tokens", 0) * 20) / 1_000_000
        self.estimated_usd += cost
        raw = "".join(c.get("text", "") for o in data.get("output", [])
                      for c in o.get("content", []) if c.get("type") == "output_text")
        self.last = {"raw_reply": raw, "usage": usage, "estimated_usd": cost,
                     "latency_s": round(time.monotonic() - started, 2),
                     "status": data.get("status")}
        if time.monotonic() >= self.deadline:
            raise RuntimeError("Mission deadline expired during API request")
        if data.get("status") != "completed":
            raise RuntimeError("Model response incomplete; no action executed")
        return raw

    def preflight(self):
        return self.ask("Reply only OK.", {"test": "API access"}, tokens=128)


def parse_object(raw):
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected one JSON object")
    return value
