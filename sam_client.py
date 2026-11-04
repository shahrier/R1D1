"""SAM 3.1 segmentation, official mask decoding, and measurable framing advice."""
import base64
import json
import math
import time
from dataclasses import asdict
from pathlib import Path

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from brain import Brain, ENDPOINT, image_info


def decode_response(data, size):
    from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format
    if data.get("status") != "completed":
        raise ValueError("SAM response incomplete")
    raw = "".join(c.get("text", "") for o in data.get("output", [])
                  for c in o.get("content", []) if c.get("type") == "output_text")
    parser = image_segmentation_format().create_parser()
    parser.push(raw)
    result = parser.finish(CompletedOutcome()).result
    if result.diagnostics:
        raise ValueError("SAM parsing diagnostics; refusing to use partial geometry")
    width, height = size
    boxes, masks = {}, {}
    for record in result.records:
        if record.kind == "box":
            coords = (record.left, record.top, record.right, record.bottom)
            if not all(math.isfinite(x) for x in coords):
                raise ValueError("Non-finite SAM box")
            left, top, right, bottom = coords
            if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                raise ValueError("SAM box outside image bounds")
            boxes[record.object_id] = {"object_id": record.object_id,
                "box": list(coords), "confidence": record.confidence}
        elif record.kind == "mask":
            if not (0 < record.mask.width <= width and 0 < record.mask.height <= height):
                raise ValueError("SAM mask dimensions exceed image bounds")
            raster = decode_mask_to_raster(record.mask)
            bounds = record.bounds
            if not (0 <= bounds.left < bounds.right <= width and
                    0 <= bounds.top < bounds.bottom <= height):
                raise ValueError("SAM mask outside image bounds")
            masks[record.object_id] = {"raster": raster,
                "size": (record.mask.width, record.mask.height), "bounds": asdict(bounds)}
    if set(boxes) != set(masks):
        raise ValueError("SAM boxes and masks do not match")
    return boxes, masks


def framing_advice(detections, width, minimum_confidence=.7):
    candidates = [d for d in detections if isinstance(d.get("confidence"), (int, float))
                  and math.isfinite(d["confidence"]) and d["confidence"] >= minimum_confidence]
    if not candidates:
        return {"status": "not_found", "turn_degrees": 0}
    if len(candidates) != 1:
        return {"status": "ambiguous", "turn_degrees": 0, "candidates": len(candidates)}
    candidate = candidates[0]
    left, _, right, _ = candidate["box"]
    error = ((left + right) / 2 - width / 2) / width
    # Right in image requires clockwise (negative). This is bounded feedback,
    # not a claimed camera calibration or physical-distance estimate.
    turn = 0 if abs(error) <= .10 else (-10 if error > 0 else 10)
    clipped = left <= 1 or right >= width - 1
    status = "partial" if turn == 0 and clipped else ("centered" if turn == 0 else "adjust")
    return {"status": status,
            "turn_degrees": turn, "horizontal_error_fraction": round(error, 4),
            "object_id": candidate["object_id"], "confidence": candidate["confidence"],
            "edge_clipped": clipped}


def render_overlay(photo, boxes, masks, destination, concept):
    with Image.open(photo) as source:
        image = source.convert("RGB")
    for identity, detection in boxes.items():
        mask = masks[identity]
        bounds = mask["bounds"]
        left, top, right, bottom = [int(bounds[k]) for k in ("left", "top", "right", "bottom")]
        raster = Image.frombytes("L", mask["size"], bytes(x * 255 for x in mask["raster"]))
        raster = raster.resize((right - left, bottom - top), Image.Resampling.NEAREST)
        full_mask = Image.new("L", image.size)
        full_mask.paste(raster, (left, top))
        alpha = full_mask.point(lambda value: 60 if value else 0)
        image = Image.composite(Image.new("RGB", image.size, "#22dd99"), image, alpha)
        edge = ImageChops.subtract(full_mask.filter(ImageFilter.MaxFilter(3)),
                                   full_mask.filter(ImageFilter.MinFilter(3)))
        image.paste("#22ffaa", mask=edge)
        draw = ImageDraw.Draw(image)
        x1, y1, x2, y2 = detection["box"]
        draw.rectangle((x1, y1, x2 - 1, y2 - 1), outline="#ffcc33", width=3)
        score = detection["confidence"]
        draw.text((x1 + 5, max(24, y1 + 5)), f"{concept}: model score {score:.2f}" if score is not None else concept,
                  fill="#ffdd44", stroke_width=1, stroke_fill="black")
    draw = ImageDraw.Draw(image)
    draw.line((image.width // 2, 0, image.width // 2, image.height), fill="#ffffff", width=2)
    draw.rectangle((0, 0, image.width, 22), fill="black")
    draw.text((8, 5), "SAM 3.1 candidate outline | center line | not distance or safe-path evidence", fill="white")
    image.save(destination, "JPEG", quality=85)


def segment(photo, concept, output_prefix, saved_response=None):
    prefix = Path(output_prefix)
    info = image_info(photo)
    if info["width"] > 1280 or info["height"] > 720:
        raise ValueError("Image exceeds upload size limit")
    started = time.monotonic()
    if saved_response:
        data = saved_response
    else:
        key = Brain(max_calls=1).key
        encoded = base64.b64encode(Path(photo).read_bytes()).decode("ascii")
        try:
            response = requests.post(ENDPOINT, headers={"Authorization": "Bearer " + key},
                json={"model": "sam-3.1", "store": False,
                      "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
                      "input": [{"role": "user", "content": [
                          {"type": "input_text", "text": concept},
                          {"type": "input_image", "image_url": "data:image/jpeg;base64," + encoded}]}]},
                timeout=(5, 35))
        except requests.RequestException as exc:
            raise RuntimeError("SAM network failure: " + type(exc).__name__) from None
        if not response.ok:
            raise RuntimeError("SAM HTTP " + str(response.status_code) + "; no automatic retry")
        data = response.json()
    prefix.with_suffix(".response.json").write_text(json.dumps(data))
    boxes, masks = decode_response(data, (info["width"], info["height"]))
    overlay = str(prefix.with_suffix(".overlay.jpg"))
    render_overlay(photo, boxes, masks, overlay, concept)
    detections = list(boxes.values())
    result = {"concept": concept, "source_photo": str(photo), "overlay": overlay,
              "image_info": info, "detections": detections,
              "framing": framing_advice(detections, info["width"]),
              "latency_s": round(time.monotonic() - started, 2),
              "estimated_usd": 0 if saved_response else .0025,
              "response_reused": saved_response is not None}
    prefix.with_suffix(".json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    import argparse
    import os
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", help="Render a saved probe without another API request")
    parser.add_argument("--photo")
    parser.add_argument("--concept", default="black suitcase")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.probe:
        probe = json.loads(Path(args.probe).read_text())
        print(json.dumps(segment(probe["source_photo"], probe["concept"], args.output, probe["response"])))
    elif args.photo:
        print(json.dumps(segment(args.photo, args.concept, args.output)))
    else:
        parser.error("Provide --probe or --photo")
