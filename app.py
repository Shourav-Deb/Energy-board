from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import plotly.express as px

from devices import load_devices, save_devices
from get_power_data import fetch_and_log_once
from tuya_api import control_device, get_token
from tuya_api_mongo import latest_docs, range_docs
from billing import (
    daily_monthly_for,
    aggregate_totals_all_devices,
    aggregate_timeseries_24h,
)

# ------------------------------------------------------------------------------------
# Page setup

st.set_page_config(page_title="Smart Energy Dashboard", layout="wide")
DATA_DIR = Path("data")

# Session state defaults
if "page" not in st.session_state:
    st.session_state.page = "home"
if "current_device_id" not in st.session_state:
    st.session_state.current_device_id = None
if "current_device_name" not in st.session_state:
    st.session_state.current_device_name = None


def go(page: str):
    st.session_state.page = page


def go_device(device_id: str, device_name: str):
    st.session_state.current_device_id = device_id
    st.session_state.current_device_name = device_name
    st.session_state.page = "device_detail"


# ------------------------------------------------------------------------------------
# Pages

def home_page():
    st.title("💡 Smart Energy Dashboard")

    devices = load_devices()
    if not devices:
        st.info("No devices yet. Go to **Add Device** from the sidebar.")
        return

    # Quick actions
    st.markdown("#### Quick actions")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📂 My Devices"):
            go("devices")
    with col2:
        if st.button("➕ Add Device"):
            go("add_device")
    with col3:
        if st.button("📈 Range Reports"):
            go("reports")

    st.markdown("---")

    # Totals
    (
        total_power_now,
        present_voltage,
        today_kwh,
        today_bill,
        month_kwh,
        month_bill,
    ) = aggregate_totals_all_devices(devices)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("⚡ Total Power (now)", f"{total_power_now:.2f} W")
        st.metric("🔌 Voltage (max)", f"{present_voltage:.1f} V")
    with c2:
        st.metric("📅 Today – Energy", f"{today_kwh:.3f} kWh")
        st.metric("📅 Today – Bill", f"{today_bill:.2f} ৳")
    with c3:
        st.metric("🗓 Month – Energy", f"{month_kwh:.3f} kWh")
        st.metric("🗓 Month – Bill", f"{month_bill:.2f} ৳")

    st.markdown("### Last 24h — Power & Voltage (all devices)")

    ts = aggregate_timeseries_24h(devices, resample_rule="5T")
    if ts.empty:
        st.info("No data available yet. Open a device page or run data_collector.py.")
        return

    fig = px.line(
        ts,
        x="timestamp",
        y=["power_sum_W", "voltage_avg_V"],
        labels={"value": "Value", "variable": "Metric"},
    )
    st.plotly_chart(fig, use_container_width=True)


def devices_page():
    st.title("📂 My Devices")
    devs = load_devices()
    if not devs:
        st.info("No devices found. Add one from **Add Device**.")
        return

    for d in devs:
        col1, col2, col3 = st.columns([3, 3, 1])
        with col1:
            st.write(f"**{d.get('name','(no name)')}**")
            st.caption(d.get("id"))
        with col2:
            if st.button("View", key=f"view_{d['id']}"):
                go_device(d["id"], d.get("name", "Device"))
                st.experimental_rerun()
        with col3:
            pass


def add_device_page():
    st.title("➕ Add Device")

    with st.form("add_device_form"):
        name = st.text_input("Device name")
        device_id = st.text_input("Tuya Device ID")
        submitted = st.form_submit_button("Add")

    if submitted:
        if not device_id.strip():
            st.error("Device ID is required.")
        else:
            devs = load_devices()
            devs.append({"name": name or device_id, "id": device_id.strip()})
            save_devices(devs)
            st.success("Device added.")
            st.button("Back to devices", on_click=lambda: go("devices"))


def manage_devices_page():
    st.title("⚙️ Manage Devices")
    devs = load_devices()
    if not devs:
        st.info("No devices to manage.")
        return

    to_keep = []
    for d in devs:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.write(f"**{d.get('name','(no name)')}** – {d.get('id')}")
        with col2:
            keep = not st.checkbox("Delete", key=f"del_{d['id']}")
        if keep:
            to_keep.append(d)

    if st.button("Save changes"):
        save_devices(to_keep)
        st.success("Device list updated.")


def device_detail_page():
    dev_id = st.session_state.current_device_id
    dev_name = st.session_state.current_device_name or dev_id

    if not dev_id:
        st.warning("No device selected.")
        return

    # Auto refresh every 30s
    st_autorefresh(interval=30_000, key="device_autorefresh")

    st.title(f"🔎 Device: {dev_name}")
    st.caption(dev_id)

    # Fetch and log one reading on every load/refresh
    try:
        fetch_and_log_once(dev_id, dev_name)
    except Exception as e:
        st.error(f"Tuya API error while logging data: {e}")

    # Control section
    st.markdown("### 🔘 Control")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Turn ON"):
            token = get_token()
            res = control_device(dev_id, token, "switch_1", True)
            st.write(res)
    with c2:
        if st.button("Turn OFF"):
            token = get_token()
            res = control_device(dev_id, token, "switch_1", False)
            st.write(res)

    # Recent power
    st.markdown("### ⚡ Recent Power (last 50 samples)")
    df_recent = latest_docs(dev_id, n=50)
    if not df_recent.empty:
        fig = px.line(df_recent, x="timestamp", y="power", title="Power (W)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data yet. Wait a few refresh cycles.")

    # Billing
    st.markdown("### 💰 Bill Estimate")
    d_units, d_cost, m_units, m_cost = daily_monthly_for(dev_id)
    b1, b2 = st.columns(2)
    with b1:
        st.metric("📅 Today kWh", f"{d_units:.3f}")
        st.metric("💸 Today BDT", f"{d_cost:.2f}")
    with b2:
        st.metric("🗓 Month kWh", f"{m_units:.3f}")
        st.metric("💰 Month BDT", f"{m_cost:.2f}")

    # Historical
    st.markdown("### 🕰️ Historical Data")
    c1, c2, c3 = st.columns(3)
    with c1:
        start_date = st.date_input(
            "Start", value=datetime.now().date() - timedelta(days=1)
        )
    with c2:
        end_date = st.date_input("End", value=datetime.now().date())
    with c3:
        agg = st.selectbox("Aggregation", ["raw", "1-min", "5-min", "15-min"], index=1)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    df = range_docs(dev_id, start_dt, end_dt)

    if not df.empty:
        df = df.sort_values("timestamp").set_index("timestamp")
        if agg != "raw":
            rule = {"1-min": "1T", "5-min": "5T", "15-min": "15T"}[agg]
            df = df.resample(rule).mean(numeric_only=True).dropna()

        plot_df = df.reset_index()
        fig = px.line(
            plot_df,
            x="timestamp",
            y="power",
            title=f"Power over time ({agg})",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(plot_df.tail(200))
    else:
        st.info("No data in the selected range.")


def reports_page():
    st.title("📈 Range Reports (all devices)")
    st.info("For now, you can use each device's historical chart. "
            "You can extend this page later with advanced filters.")


# ------------------------------------------------------------------------------------
# Sidebar navigation

choice = st.sidebar.radio(
    "Navigate",
    ["Home", "My Devices", "Add Device", "Manage Devices", "Range Reports"],
    index=["home", "devices", "add_device", "manage_devices", "reports"].index(
        st.session_state.page
        if st.session_state.page in ["home", "devices", "add_device", "manage_devices", "reports"]
        else "home"
    ),
)

mapping = {
    "Home": "home",
    "My Devices": "devices",
    "Add Device": "add_device",
    "Manage Devices": "manage_devices",
    "Range Reports": "reports",
}
st.session_state.page = mapping[choice]

st.sidebar.markdown("---")
st.sidebar.caption("Auto-logging via data_collector.py or this page.")

# ------------------------------------------------------------------------------------
# Router

if st.session_state.page == "home":
    home_page()
elif st.session_state.page == "devices":
    devices_page()
elif st.session_state.page == "add_device":
    add_device_page()
elif st.session_state.page == "manage_devices":
    manage_devices_page()
elif st.session_state.page == "device_detail":
    device_detail_page()
elif st.session_state.page == "reports":
    reports_page()
else:
    home_page()
