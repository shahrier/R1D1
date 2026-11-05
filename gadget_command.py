"""JSON stdin/stdout adapter for Muse Gadget drop-in commands. No shell execution."""
import json
import os
import sys
from pathlib import Path

from inspect_demo import Store, acknowledge, inspect


def _check_target(target):
    if not isinstance(target, str) or not 1 <= len(target) <= 150:
        raise ValueError("Target must be short text")
    return target


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
        result = inspect(store, target=_check_target(target), send=True)
    elif command == "acknowledge":
        result = acknowledge(store, params["event_id"], params["owner_note"])
    elif command == "status":
        with store.locked() as state:
            result = state["scopes"].get("bedroom-demo", {})
    elif command == "stop":
        (store.root / "STOP").touch()
        result = {"stop_requested": True, "latched": True,
                  "message": "Local controller will stop; physical stop is required if unresponsive"}
    elif command == "memory":
        from memory_command import run
        result = run(mode=params.get("mode", "recognize"), send=True)
    else:
        raise ValueError("Unknown command")
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "Command failed; check local mission log"}))
        raise SystemExit(1)
