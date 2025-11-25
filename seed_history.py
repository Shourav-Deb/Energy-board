"""
seed_history.py

One-shot synthetic history seeding for demo purposes.

How it works:
- When imported, it checks a 'meta' collection in MongoDB.
- If seeding has not been done, it generates 5 days of realistic readings
  for the given DEVICE_ID and inserts them into readings_<DEVICE_ID>.
- Then it writes a flag so it will NOT run again on future imports.

SAFE to leave in the repo; after first run it does nothing.
"""

import os
from datetime import datetime, timedelta
import random

from dotenv import load_dotenv
from pymongo import MongoClient

# -------------------------------------------------------
# CONFIG — CHANGE THESE VALUES
# -------------------------------------------------------

# Your real Tuya device ID (must match devices.json)
DEVICE_ID = "YOUR_TUYA_DEVICE_ID_1"          # <-- put your real device ID here
DEVICE_NAME = "FUB 401 - Lab Plug"           # friendly label for the device

# Number of past days to simulate (excluding today)
PAST_DAYS = 5

# Time step between readings (minutes)
STEP_MINUTES = 5

# Typical line voltage in your building (Volts)
BASE_VOLTAGE = 230.0

# -------------------------------------------------------
# MONGODB CONNECTION
# -------------------------------------------------------

load_dotenv()  # for local dev; on Streamlit Cloud it just ignores if no .env

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB = os.getenv("MONGODB_DB", "tuya_energy")

if not MONGODB_URI:
    # On Streamlit Cloud this will show in logs if secrets not set.
    print("[seed_history] MONGODB_URI not set; skipping seeding.")
    SEED_OK = False
else:
    client = MongoClient(MONGODB_URI, tls=True)
    db = client[MONGODB_DB]
    readings_coll = db[f"readings_{DEVICE_ID}"]
    meta_coll = db["meta"]
    SEED_OK = True


def _already_seeded() -> bool:
    """Check meta collection for 'history_seed_done' flag."""
    if not SEED_OK:
        return True
    doc = meta_coll.find_one({"_id": "history_seed_done"})
    return bool(doc and doc.get("done"))


def _mark_seeded():
    """Set flag so we don't reseed on every import."""
    if not SEED_OK:
        return
    meta_coll.update_one(
        {"_id": "history_seed_done"},
        {"$set": {"done": True, "at": datetime.utcnow()}},
        upsert=True,
    )


def power_profile_for_minute(minute_of_day: int) -> float:
    """
    Return a realistic power value (W) based on time of day.

    minute_of_day: 0..1439 (0 = 00:00, 1439 = 23:59)
    """
    hour = minute_of_day // 60

    # Base profiles:
    if 0 <= hour < 6:
        base = 8      # very low at night
    elif 6 <= hour < 9:
        base = 70     # warm-up
    elif 9 <= hour < 12:
        base = 130    # classes / lab
    elif 12 <= hour < 17:
        base = 170    # peak hours
    elif 17 <= hour < 22:
        base = 90     # evening
    else:
        base = 20     # late night

    # Random variation around base
    noise = random.uniform(-0.25, 0.25) * base
    p = max(0.0, base + noise)

    # Slight daily variation (0.9x - 1.1x)
    day_factor = 0.9 + random.random() * 0.2
    return p * day_factor


def generate_docs():
    """Generate synthetic docs for last PAST_DAYS (excluding today)."""
    now = datetime.utcnow()
    today = now.date()

    start_date = today - timedelta(days=PAST_DAYS)
    end_date = today - timedelta(days=1)

    docs = []
    energy_kwh = 0.0  # cumulative

    print(f"[seed_history] Generating synthetic data from {start_date} to {end_date}...")

    current_date = start_date
    while current_date <= end_date:
        day_start = datetime(
            current_date.year, current_date.month, current_date.day, 0, 0, 0
        )
        for step in range(0, 24 * 60, STEP_MINUTES):
            ts = day_start + timedelta(minutes=step)
            minute_of_day = step

            power = power_profile_for_minute(minute_of_day)
            voltage = BASE_VOLTAGE + random.uniform(-4.0, 4.0)
            current = power / voltage if voltage > 0 else 0.0

            hours = STEP_MINUTES / 60.0
            delta_kwh = (power * hours) / 1000.0
            energy_kwh += delta_kwh

            doc = {
                "timestamp": ts,  # naive UTC datetime; your app converts ranges correctly
                "device_id": DEVICE_ID,
                "device_name": DEVICE_NAME,
                "voltage": round(voltage, 2),
                "current": round(current, 3),
                "power": round(power, 1),
                "energy_kWh": round(energy_kwh, 4),
            }
            docs.append(doc)

        current_date += timedelta(days=1)

    return docs


def run_seed_if_needed():
    if not SEED_OK:
        print("[seed_history] Mongo not configured; skipping.")
        return

    if _already_seeded():
        print("[seed_history] History already seeded; nothing to do.")
        return

    docs = generate_docs()
    if not docs:
        print("[seed_history] No docs generated; skipping insert.")
        return

    print(f"[seed_history] Inserting {len(docs)} synthetic documents into MongoDB...")
    result = readings_coll.insert_many(docs)
    print(f"[seed_history] Inserted {len(result.inserted_ids)} docs.")
    _mark_seeded()
    print("[seed_history] Seeding complete; flag set to avoid reseeding.")


# Run automatically on import
try:
    run_seed_if_needed()
except Exception as e:
    print("[seed_history] ERROR during seeding:", e)
