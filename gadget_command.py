"""JSON stdin/stdout adapter for Muse Gadget drop-in commands. No shell execution."""
import json
import os
import sys
from pathlib import Path

from inspect_demo import Store, acknowledge, inspect


def main():
    os.umask(0o077)
    params = json.load(sys.stdin)
    if not isinstance(params, dict):
        raise ValueError("Expected command parameter object")
    store = Store(Path(__file__).parent / "runtime")
    command = sys.argv[1]
    if command == "inspect":
        target = params.get("target")
        if target is None:
            with store.locked() as state:
                event_id = state["scopes"].get("bedroom-demo", {}).get("latest_event")
                target = state["events"].get(event_id, {}).get("target", "suitcase")
        if not isinstance(target, str) or not 1 <= len(target) <= 150:
            raise ValueError("Target must be short text")
        # Return directly to the requesting Muse conversation; don't send a duplicate message.
        result = inspect(store, target=target, send=True)
    elif command == "acknowledge":
        result = acknowledge(store, params["event_id"], params["owner_note"])
    elif command == "status":
        with store.locked() as state:
            result = state["scopes"].get("bedroom-demo", {})
    elif command == "locate":
        from frame_target import run
        concept = params.get("target", "black suitcase")
        if not isinstance(concept, str) or not 1 <= len(concept) <= 150:
            raise ValueError("Target must be short text")
        result = run(concept=concept, allow_motion=False, send=True)
        result.pop("history", None)
    elif command == "stop":
        (store.root / "STOP").touch()
        result = {"stop_requested": True, "latched": True,
                  "message": "Local controller will stop; physical stop is required if unresponsive"}
    else:
        raise ValueError("Unknown command")
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Error messages may contain model-generated text; return only exception type.
        print(json.dumps({"error": type(exc).__name__, "message": "Command failed; check local mission log"}))
        raise SystemExit(1)
