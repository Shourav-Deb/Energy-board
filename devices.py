import json
from pathlib import Path

DEVICES_JSON_PATH = Path("devices.json")


def load_devices():
    """Return list of devices [{'name': ..., 'id': ...}, ...]."""
    if not DEVICES_JSON_PATH.exists():
        return []
    try:
        return json.loads(DEVICES_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_devices(devs: list):
    """Overwrite devices.json with new list."""
    DEVICES_JSON_PATH.write_text(json.dumps(devs, indent=4), encoding="utf-8")
