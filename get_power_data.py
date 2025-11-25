from tuya_api import get_token, get_device_status
from tuya_api_mongo import insert_reading
from helpers import parse_metrics, build_doc


def fetch_and_log_once(device_id: str, device_name: str = ""):
    """Fetch one reading from Tuya and store in MongoDB."""
    token = get_token()
    raw = get_device_status(device_id, token)

    # DEBUG: see what Tuya really sends
    print("RAW TUYA STATUS:", raw)

    if not raw.get("success"):
        return {"error": raw}

    v, c, p, e = parse_metrics(raw)
    print("PARSED:", v, c, p, e)  # DEBUG

    doc = build_doc(device_id, device_name, v, c, p, e)
    insert_reading(device_id, doc)
    return {"ok": True, "row": doc, "raw": raw}
