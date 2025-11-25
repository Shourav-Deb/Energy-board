from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import plotly.express as px

from devices import load_devices, save_devices
from get_power_data import fetch_and_log_once
from tuya_api import control_device, get_token
from tuya_api_mongo import latest_docs, range_docs, get_client, MONGODB_URI
from billing import (
    daily_monthly_for,
    aggregate_totals_all_devices,
    aggregate_timeseries_24h,
)

# ------------------------------------------------------------------------------------
# Page setup

st.set_page_config(page_title="FUB Smart Energy Board", layout="wide")
DATA_DIR = Path("data")

# Global styles (premium-ish)
st.markdown(
    """
    <style>
    .main .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1.5rem;
        max-width: 1200px;
    }
    .big-title {
        font-size: 2.3rem;
        font-weight: 750;
        margin-bottom: 0.1rem;
    }
    .subtitle {
        color: #9ca3af;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    .card {
        padding: 1rem 1.2rem;
        border-radius: 0.85rem;
        background: #020617;
        border: 1px solid #1f2937;
    }
    .card h3 {
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #9ca3af;
        margin-bottom: 0.35rem;
    }
    .card .value {
        font-size: 1.3rem;
        font-weight: 650;
    }
    .pill {
        display: inline-flex;
        align-items: center;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        border: 1px solid #1f2937;
        font-size: 0.76rem;
        color: #9ca3af;
        gap: 0.4rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
# Sidebar: navigation + Mongo status

# Mongo health check
try:
    _client = get_client()
    mongo_ok = _client is not None
except Exception as _e:
    mongo_ok = False
    mongo_err = str(_e)
else:
    mongo_err = ""

with st.sidebar:
    st.markdown("### 🧭 Navigation")

    options = ["🏠 Overview", "📂 Devices", "➕ Add Device", "⚙️ Manage Devices", "📈 Reports"]
    label_to_page = {
        "🛖 Overview": "home",
        "🕼 Devices": "devices",
        "➕ Add Device": "add_device",
        "⚙🪹 Manage Devices": "manage_devices",
        "🗏 Reports": "reports",
    }
    page_to_label = {v: k for k, v in label_to_page.items()}

    # Decide which label should appear selected in the radio
    current_page = st.session_state.page
    if current_page in page_to_label:
        default_label = page_to_label[current_page]
    else:
        default_label = "🏠 Overview"

    choice = st.radio(
        "",
        options,
        index=options.index(default_label),
        key="nav_choice",
    )

    # IMPORTANT: do NOT override when we are already on the device detail view
    if st.session_state.page != "device_detail":
        st.session_state.page = label_to_page[choice]

    st.markdown("---")
    st.markdown("### 🛢 Data Backend Status")
    st.write("Mongo URI:", bool(MONGODB_URI))
    st.write("Connected:", mongo_ok)
    if not mongo_ok:
        st.caption("Check MONGODB_URI in secrets / .env")
    st.markdown("---")
    st.caption("Powered by Shourav Deb")



# ------------------------------------------------------------------------------------
# Pages

def home_page():
    devices = load_devices()

    st.markdown('<div class="big-title">Dev IoT Analyzer</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Live view of energy for the FUB building, '
        'Trail Version.</div>',
        unsafe_allow_html=True,
    )

    if not devices:
        st.info("No devices yet. Use **Add Device** from the left sidebar to register at least one Tuya plug.")
        return

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
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("<h3>Instant Load</h3>", unsafe_allow_html=True)
        st.markdown(f'<div class="value">{total_power_now:.1f} W</div>', unsafe_allow_html=True)
        st.caption("Total active power drawn across all connected plugs.")
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("<h3>Today (kWh & Bill)</h3>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="value">{today_kwh:.3f} kWh</div>', unsafe_allow_html=True
        )
        st.caption(f"Estimated cost: **{today_bill:.2f} BDT**")
        st.markdown("</div>", unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("<h3>This Month</h3>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="value">{month_kwh:.3f} kWh</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"Projected bill so far: **{month_bill:.2f} BDT**")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("")
    col_l, col_r = st.columns([3, 1])
    with col_l:
        st.markdown("#### Last 24 hours Power & Voltage")
        ts = aggregate_timeseries_24h(devices, resample_rule="5T")
        if ts.empty:
            st.info(
                "No historical data in MongoDB yet.\n\n"
                "- Open a device page and wait a few refreshes"
            )
        else:
            fig = px.line(
                ts,
                x="timestamp",
                y=["power_sum_W", "voltage_avg_V"],
                labels={"value": "Value", "variable": "Metric"},
            )
            fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.markdown("#### Quick actions")
        if st.button("📡 Open devices list"):
            go("devices")
            st.rerun()
        if st.button("➕ Add new plug"):
            go("add_device")
            st.rerun()
        st.markdown("---")
        st.markdown(
            '<span class="pill">Devices online: '
            f'{len(devices)}</span>',
            unsafe_allow_html=True,
        )


def devices_page():
    st.markdown('<div class="big-title">All Connected Devices</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Each tile represents a Tuya smart plug mapped to a load in the FUB building.</div>',
        unsafe_allow_html=True,
    )

    devs = load_devices()
    if not devs:
        st.info("No devices found. Add one from **Add Device** in the sidebar.")
        return

    for d in devs:
        with st.container():
            col1, col2, col3 = st.columns([4, 3, 2])
            with col1:
                st.markdown(
                    f"**{d.get('name','(no name)')}**  \n"
                    f"`{d.get('id')}`",
                )
            with col2:
                # Show latest instant power if available
                df_recent = latest_docs(d["id"], n=1)
                if not df_recent.empty:
                    row = df_recent.iloc[-1]
                    st.caption(
                        f"Last: {row.get('power', 0):.1f} W @ "
                        f"{row.get('voltage', 0):.1f} V"
                    )
                else:
                    st.caption("No readings stored yet.")
            with col3:
                if st.button("Open dashboard", key=f"view_{d['id']}"):
                    go_device(d["id"], d.get("name", "Device"))
                    st.rerun()
        st.markdown("---")


def add_device_page():
    st.markdown('<div class="big-title">Add a New FUB Device</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Register a Tuya plug by its device ID from the Tuya IoT Cloud console.</div>',
        unsafe_allow_html=True,
    )

    with st.form("add_device_form"):
        name = st.text_input("Friendly Name (e.g., FUB Lab Plug 1)")
        device_id = st.text_input("Tuya Device ID")
        submitted = st.form_submit_button("Add device")

    if submitted:
        if not device_id.strip():
            st.error("Device ID is required.")
        else:
            devs = load_devices()
            devs.append({"name": name or device_id, "id": device_id.strip()})
            save_devices(devs)
            st.success("Device added successfully.")
            st.info("Now open the **Devices** page and click into the device to start logging data.")


def manage_devices_page():
    st.markdown('<div class="big-title">Manage Devices</div>', unsafe_allow_html=True)
    devs = load_devices()
    if not devs:
        st.info("No devices to manage yet.")
        return

    to_keep = []
    for d in devs:
        col1, col2 = st.columns([5, 1])
        with col1:
            st.write(f"**{d.get('name','(no name)')}** – `{d.get('id')}`")
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
        st.warning("No device selected. Open **Devices** and choose one.")
        return

    # Auto refresh every 30s
    st_autorefresh(interval=30_000, key="device_autorefresh")

    st.markdown(
        f'<div class="big-title">Device: {dev_name}</div>',
        unsafe_allow_html=True,
    )
    st.caption(dev_id)

    # Fetch and log one reading on every load/refresh
    try:
        fetch_and_log_once(dev_id, dev_name)
    except Exception as e:
        st.error(f"Tuya API error while logging data: {e}")

    # Layout: top cards + control + charts
    top1, top2 = st.columns([2, 1])

    with top1:
        st.markdown("#### Live snapshot")
        df_recent = latest_docs(dev_id, n=20)
        if not df_recent.empty:
            last = df_recent.iloc[-1]
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Power", f"{float(last.get('power', 0)):.1f} W")
            with c2:
                st.metric("Voltage", f"{float(last.get('voltage', 0)):.1f} V")
            with c3:
                st.metric("Current", f"{float(last.get('current', 0)):.3f} A")
        else:
            st.info("No readings stored yet for this device.")

    with top2:
        st.markdown("#### Control")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Turn ON"):
                token = get_token()
                res = control_device(dev_id, token, "switch_1", True)
                st.json(res)
        with c2:
            if st.button("Turn OFF"):
                token = get_token()
                res = control_device(dev_id, token, "switch_1", False)
                st.json(res)

    # Recent power chart
    st.markdown("### Recent Power (last 50 samples)")
    df_recent = latest_docs(dev_id, n=50)
    if not df_recent.empty:
        fig = px.line(df_recent, x="timestamp", y="power", title="")
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data yet. Leave this page open for a few refresh cycles.")

    # Billing
    st.markdown("### Billing Estimate")
    d_units, d_cost, m_units, m_cost = daily_monthly_for(dev_id)
    b1, b2 = st.columns(2)
    with b1:
        st.metric("Today (kWh)", f"{d_units:.3f}")
        st.metric("Today (BDT)", f"{d_cost:.2f}")
    with b2:
        st.metric("This month (kWh)", f"{m_units:.3f}")
        st.metric("This month (BDT)", f"{m_cost:.2f}")

    # Historical
    st.markdown("### Historical Analysis")
    c1, c2, c3 = st.columns(3)
    with c1:
        start_date = st.date_input(
            "Start date", value=datetime.now().date() - timedelta(days=1)
        )
    with c2:
        end_date = st.date_input("End date", value=datetime.now().date())
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
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.expander("Raw data (tail)").dataframe(plot_df.tail(200))
    else:
        st.info("No data in the selected range.")


def reports_page():
    st.markdown('<div class="big-title">Reports & Aggregations</div>', unsafe_allow_html=True)
    st.info(
        "This service is down for maintenance right now. We'll be back online soon. Thanks for your patience."
    )


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
