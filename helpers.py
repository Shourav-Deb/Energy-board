import json
import os
from datetime import datetime, timedelta, timezone

import streamlit as st

# Dhaka timezone
dhaka_tz = timezone(timedelta(hours=6))

DEVICE_FILE = "devices.json"


def parse_metrics(status_json: dict):
    """
    Extract voltage, current, power and estimated energy_kWh from Tuya status JSON.
    Assumes DP codes: cur_voltage, cur_power, cur_current.
    Adjust if your device uses different codes.
    """
    result = status_json.get("result", [])
    m = {x.get("code"): x.get("value") for x in result}

    voltage = (m.get("cur_voltage") or 0) / 10.0   # deciV → V
    power = (m.get("cur_power") or 0) / 10.0       # W
    current = (m.get("cur_current") or 0) / 1000.0 # mA → A

    # Approx energy for ~5s interval: W * (5/3600) / 1000 → kWh
    energy_kwh = power * (5.0 / 3600.0) / 1000.0
    return voltage, current, power, energy_kwh


def build_doc(device_id: str, device_name: str, v: float, c: float, p: float, e: float):
    return {
        "timestamp": datetime.now(dhaka_tz),
        "device_id": device_id,
        "device_name": device_name or "",
        "voltage": v,
        "current": c,
        "power": p,
        "energy_kWh": e,
    }


def load_devices_local():
    if not os.path.exists(DEVICE_FILE):
        return []
    with open(DEVICE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_devices_local(devices):
    with open(DEVICE_FILE, "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=4)


def go_home():
    st.session_state.page = "home"
