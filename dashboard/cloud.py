"""Cloud Monitoring Dashboard — read-only MQTT viewer.

Receives the live tag stream published by the local backend (`local_backend.py`)
over MQTT. Shows key KPIs with animated equipment icons, tank-level trend,
pasteurizer temperature trend, and recent alarms. NO control capabilities —
this is a pure display dashboard for the cloud (ISA-95 L4).

Creates its own `RemoteEngineProxy` connected to the MQTT broker — no shared
singleton needed since this is a single-page monitoring dashboard.
"""

from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from engine.remote import RemoteEngineProxy

# ── Engine: one shared MQTT client per configured broker ───────────────
# The connection key invalidates the resource when Streamlit Secrets change,
# while sharing one Paho network thread across browser sessions.
@st.cache_resource(show_spinner="Connecting to MQTT broker…")
def _get_cloud_engine(connection_key: tuple) -> RemoteEngineProxy:
    del connection_key  # used only as the Streamlit cache key
    return RemoteEngineProxy(use_mqtt=True)


_connection_key = (
    config.MQTT_HOST,
    config.MQTT_PORT,
    config.MQTT_TLS,
    config.MQTT_USERNAME,
    config.MQTT_PASSWORD,
    config.MQTT_TOPIC_PREFIX,
)
engine = _get_cloud_engine(_connection_key)

# ── Theme ──────────────────────────────────────────────────────────────
BG      = "#0d1117"
CARD    = "#161b22"
BDR     = "#30363d"
TXT     = "#c9d1d9"
TXT2    = "#b0b8c0"
ACC     = "#58a6ff"
GRN     = "#3fb950"
ORN     = "#d2991d"
RED     = "#f85149"
CYA     = "#39d2c0"
STEEL   = "#2d333b"
LIQUID  = "#3a7bd5"

st.markdown(f"""
<style>
    .stApp {{ background: {BG}; }}
    .main .block-container {{ padding-top: 0.4rem; }}
    header[data-testid="stHeader"] {{
        background: linear-gradient(90deg, {BG}, {CARD}, {BG});
        border-bottom: 1px solid {BDR};
    }}
    header[data-testid="stHeader"] * {{ color: {TXT} !important; }}
    .kpi-card {{
        background: {CARD}; border: 1px solid {BDR}; border-radius: 10px;
        padding: 14px 16px; display: flex; align-items: center; gap: 14px;
        transition: border-color 0.3s; height: 88px; box-sizing: border-box;
    }}
    .kpi-card:hover {{ border-color: {ACC}66; }}
    .kpi-icon {{ flex-shrink: 0; width: 48px; height: 48px; }}
    .kpi-body {{ flex: 1; }}
    .kpi-value {{
        font-size: 1.55rem; font-weight: 700; color: {TXT};
        line-height: 1.15; font-family: 'SF Mono','Consolas',monospace;
    }}
    .kpi-label {{
        font-size: 0.6rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.08em; color: {TXT2}; margin-top: 2px;
    }}
    .kpi-sub {{
        font-size: 0.58rem; color: {TXT2}; margin-top: 1px;
    }}
    .status-dot {{
        display: inline-block; width: 10px; height: 10px; border-radius: 50%;
        margin-right: 8px;
    }}
    .dot-ok {{ background: {GRN}; box-shadow: 0 0 8px {GRN}88; }}
    .dot-warn {{ background: {ORN}; box-shadow: 0 0 8px {ORN}88; }}
    .dot-fault {{ background: {RED}; box-shadow: 0 0 8px {RED}88; animation: pulse 1.5s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.5}} }}
    .section-label {{
        font-size: 0.62rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.1em; color: {TXT2};
        margin: 16px 0 8px 0; padding-bottom: 6px; border-bottom: 1px solid {BDR};
    }}
    .alarm-row {{
        background: {CARD}; border-left: 3px solid {RED}; border-radius: 4px;
        padding: 6px 12px; margin: 3px 0; font-size: 0.7rem; color: {TXT};
    }}
</style>
""", unsafe_allow_html=True)

# ── SVG icon builders ──────────────────────────────────────────────────
def _icon_tank(level_pct: float) -> str:
    fill_h = max(3, level_pct / 100 * 30)
    fill_y = 34 - fill_h
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<rect x="6" y="4" width="36" height="40" rx="6" fill="{STEEL}" stroke="{BDR}" stroke-width="1.5"/>'
        f'<rect x="10" y="{fill_y:.0f}" width="28" height="{fill_h:.0f}" rx="3" fill="url(#liq)"/>'
        f'<defs><linearGradient id="liq" x1="0" y1="1" x2="0" y2="0">'
        f'<stop offset="0%" stop-color="{LIQUID}" stop-opacity="0.95"/>'
        f'<stop offset="100%" stop-color="{ACC}" stop-opacity="0.45"/>'
        f'</linearGradient></defs></svg>')

def _icon_thermo(temp: float, ok: bool) -> str:
    c = GRN if ok else RED
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<circle cx="24" cy="36" r="10" fill="none" stroke="{c}" stroke-width="2.5"/>'
        f'<rect x="20" y="6" width="8" height="22" rx="4" fill="{c}" opacity="0.7"/>'
        f'<circle cx="24" cy="36" r="5" fill="{c}" opacity="0.8"/>'
        f'</svg>')

def _icon_cooler(temp: float, ok: bool) -> str:
    c = CYA if ok else ORN
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<circle cx="24" cy="26" r="12" fill="none" stroke="{c}" stroke-width="2"/>'
        f'<line x1="24" y1="10" x2="24" y2="18" stroke="{c}" stroke-width="2"/>'
        f'<line x1="24" y1="34" x2="24" y2="42" stroke="{c}" stroke-width="2"/>'
        f'<line x1="10" y1="26" x2="18" y2="26" stroke="{c}" stroke-width="2"/>'
        f'<line x1="30" y1="26" x2="38" y2="26" stroke="{c}" stroke-width="2"/>'
        f'</svg>')

def _icon_flow(active: bool) -> str:
    c = ACC if active else TXT2
    anim = '<animateTransform attributeName="transform" type="rotate" from="0 24 24" to="360 24 24" dur="0.8s" repeatCount="indefinite"/>' if active else ""
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<circle cx="24" cy="24" r="16" fill="none" stroke="{c}" stroke-width="2.5"/>'
        f'<g>{anim}'
        f'<polygon points="24,12 32,20 24,16 16,20" fill="{c}" opacity="0.8"/>'
        f'</g><g>{anim}'
        f'<polygon points="24,36 16,28 24,32 32,28" fill="{c}" opacity="0.6"/>'
        f'</g></svg>')

def _icon_buffer(buf: int, mx: int) -> str:
    frac = buf / max(mx, 1)
    c = ORN if frac > 0.85 else (GRN if frac < 0.5 else ACC)
    fw = int(frac * 34)
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<rect x="4" y="20" width="40" height="8" rx="3" fill="{STEEL}" stroke="{BDR}" stroke-width="1.5"/>'
        f'<rect x="7" y="23" width="{fw}" height="2" rx="1" fill="{c}"/>'
        f'<circle cx="10" cy="24" r="5" fill="{STEEL}" stroke="{BDR}" stroke-width="1.5"/>'
        f'<circle cx="38" cy="24" r="5" fill="{STEEL}" stroke="{BDR}" stroke-width="1.5"/>'
        f'<rect x="16" y="10" width="5" height="10" rx="2" fill="{LIQUID}" opacity="0.6"/>'
        f'<rect x="24" y="10" width="5" height="10" rx="2" fill="{LIQUID}" opacity="0.6"/>'
        f'<rect x="32" y="10" width="5" height="10" rx="2" fill="{LIQUID}" opacity="0.6"/>'
        f'</svg>')

def _icon_bottles(n: int) -> str:
    c = CYA if n > 0 else TXT2
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<rect x="18" y="10" width="12" height="28" rx="3" fill="none" stroke="{c}" stroke-width="2"/>'
        f'<rect x="20" y="14" width="8" height="6" rx="1" fill="{LIQUID}" opacity="0.6"/>'
        f'<rect x="20" y="22" width="8" height="6" rx="1" fill="{LIQUID}" opacity="0.6"/>'
        f'<rect x="21" y="7" width="6" height="4" rx="1" fill="{c}" opacity="0.5"/>'
        f'</svg>')


def _icon_plc(state: str) -> str:
    c = GRN if state == "RUNNING" else (RED if state == "FAULT" else ORN)
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<circle cx="24" cy="24" r="16" fill="none" stroke="{c}" stroke-width="3"/>'
        f'<circle cx="24" cy="24" r="8" fill="{c}" opacity="0.75"/>'
        f'</svg>')

def _icon_alarm(active: bool) -> str:
    c = RED if active else GRN
    ch = "!" if active else "&#10003;"
    return (
        f'<svg viewBox="0 0 48 48" width="48" height="48">'
        f'<polygon points="24,4 44,44 4,44" fill="none" stroke="{c}" stroke-width="2.5"/>'
        f'<text x="24" y="36" text-anchor="middle" fill="{c}" font-size="18" font-weight="900">{ch}</text>'
        f'</svg>')


def kpi_card(icon_svg: str, value: str, label: str, sub: str = "", status: str = "") -> str:
    dot_cls = {"ok": "dot-ok", "warn": "dot-warn", "fault": "dot-fault"}.get(status, "")
    dot = f'<span class="status-dot {dot_cls}"></span>' if dot_cls else ""
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-icon">{icon_svg}</div>'
        f'<div class="kpi-body">'
        f'<div class="kpi-value">{dot}{value}</div>'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-sub">{sub}</div>'
        f'</div></div>')


# ═══════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div style="background:linear-gradient(90deg,{BG},{CARD},{BG});border-radius:8px;
padding:10px 22px;margin-bottom:10px;border-bottom:1px solid {BDR};
display:flex;justify-content:space-between;align-items:center;">
<div>
  <span style="font-size:1.1rem;font-weight:700;color:#f0f6fc;letter-spacing:0.06em;">BEVERAGE LINE</span>
  <span style="font-size:0.58rem;color:{TXT2};margin-left:12px;letter-spacing:0.05em;">LIVE MONITOR — MQTT</span>
</div>
<div style="font-size:0.62rem;color:{TXT2};text-align:right;" id="header-right">
</div>
</div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# LIVE VIEW
# ═══════════════════════════════════════════════════════════════════════
# ── MQTT diagnostics ───────────────────────────────────────────────────
bus_kind = type(engine.bus).__name__
if bus_kind == "MqttBus" and getattr(engine.bus, "connected", False):
    mqtt_info = f"MQTT connected → {config.MQTT_HOST}:{config.MQTT_PORT}"
elif bus_kind == "MqttBus":
    mqtt_info = f"MQTT connecting → {config.MQTT_HOST}:{config.MQTT_PORT}"
else:
    mqtt_info = f"WARNING: Using {bus_kind} — MQTT broker unreachable. Check credentials in Streamlit Secrets."

st.caption(mqtt_info)

@st.fragment(run_every="2s")
def monitor_view():
    latest = engine.latest()

    # ── Data-freshness / MQTT status ──────────────────────────────────
    if not latest:
        st.error("No data received. Check: 1) local_backend.py is running  2) MQTT credentials match  3) topic prefix matches")
        with st.expander("Diagnostics"):
            st.write(f"Bus type: {type(engine.bus).__name__}")
            st.write(f"Broker: {config.MQTT_HOST}:{config.MQTT_PORT}")
            st.write(f"Topic: {config.MQTT_TOPIC_TAGS}")
            st.write(f"TLS: {config.MQTT_TLS}")
            st.write(f"Username: {'set' if config.MQTT_USERNAME else 'NOT SET'}")
        return

    # Show MQTT status — check when the last snapshot arrived
    last_ts = latest.get("ts", 0)
    age = time.time() - last_ts if last_ts else 999
    if age < 5:
        mqtt_status = f'<span class="status-dot dot-ok"></span>MQTT live · updated {age:.0f}s ago'
    elif age < 15:
        mqtt_status = f'<span class="status-dot dot-warn"></span>MQTT stale · last update {age:.0f}s ago'
    else:
        mqtt_status = f'<span class="status-dot dot-fault"></span>MQTT disconnected · {age:.0f}s since last data'

    alarm_code = int(latest.get("alarm_code", 0))
    plc = latest.get("plc_state", "IDLE")
    temp = float(latest.get("pasteur_temp", 0))
    cool = float(latest.get("cooler_temp", 0))
    flow = float(latest.get("flow_rate", 0))
    level = float(latest.get("tank_level", 0))
    buf = int(latest.get("conveyor_queue", 0))
    buf_max = int(latest.get("conveyor_max", config.CONVEYOR_MAX_BOTTLES))
    completed = int(latest.get("bottles_completed", 0))
    heater = float(latest.get("heater_power_cmd", 0))
    cool_v = float(latest.get("cooling_valve_cmd", 0))
    conv = float(latest.get("conveyor_cmd", 0))
    phase = int(latest.get("startup_phase", 2))

    t_ok = config.PASTEUR_SAFE_MIN <= temp <= config.PASTEUR_SAFE_MAX
    c_ok = cool <= config.COOLER_MAX_BOTTLING
    l_ok = config.TANK_LEVEL_LOW <= level <= config.TANK_LEVEL_HIGH

    # Top status bar
    plc_dot = {"RUNNING": "dot-ok", "STARTING": "dot-warn", "FAULT": "dot-fault"}.get(plc, "")
    alarm_label = config.ALARM_LABELS.get(alarm_code, "None")
    alarm_dot = "" if alarm_code == 0 else "dot-fault"
    plc_phase = {0: "HEAT", 1: "PRIME", 2: plc}.get(phase, plc)

    st.markdown(
        f'<div style="display:flex;gap:24px;align-items:center;font-size:0.72rem;color:{TXT2};padding:4px 0 8px 0;">'
        f'<span>{mqtt_status}</span>'
        f'<span>PLC: <b style="color:{TXT}">{plc_phase}</b></span>'
        f'<span>Alarm: <b style="color:{RED if alarm_code else GRN}">{alarm_label}</b></span>'
        f'<span>Tick: <b style="color:{TXT}">{latest.get("tick", 0)}</b></span>'
        f'</div>', unsafe_allow_html=True)

    # ── KPI Cards Row 1 ───────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(kpi_card(
            _icon_thermo(temp, t_ok), f"{temp:.1f}°C", "PASTEURIZER",
            f"Heater {heater:.0f}% · SP {config.PASTEUR_SETPOINT:.0f}°C · {config.PASTEUR_SAFE_MIN:.0f}–{config.PASTEUR_SAFE_MAX:.0f}°C",
            "ok" if t_ok else "fault"), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_card(
            _icon_cooler(cool, c_ok), f"{cool:.1f}°C", "COOLER",
            f"Valve {cool_v:.0f}% · Limit {config.COOLER_MAX_BOTTLING:.0f}°C",
            "ok" if c_ok else "warn"), unsafe_allow_html=True)
    with c3:
        st.markdown(kpi_card(
            _icon_flow(flow > 1), f"{flow:.1f} L/min", "FLOW RATE",
            f"{'FLOWING' if flow > 1 else 'IDLE'}",
            "ok" if flow > 1 else ""), unsafe_allow_html=True)
    with c4:
        st.markdown(kpi_card(
            _icon_bottles(completed), f"{completed}", "COMPLETED",
            f"Buffer: {buf}/{buf_max}  ·  Belt {conv:.0f}%",
            "ok" if completed > 0 else ""), unsafe_allow_html=True)

    # ── KPI Cards Row 2 ───────────────────────────────────────────────
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.markdown(kpi_card(
            _icon_tank(level), f"{level:.1f}%", "RAW TANK",
            f"Target {config.TANK_LEVEL_TARGET:.0f}% · Range {config.TANK_LEVEL_LOW:.0f}–{config.TANK_LEVEL_HIGH:.0f}%",
            "ok" if l_ok else "warn"), unsafe_allow_html=True)
    with c6:
        st.markdown(kpi_card(
            _icon_buffer(buf, buf_max), f"{buf}/{buf_max}", "CONVEYOR BUFFER",
            f"{'CRITICAL' if buf > buf_max*0.85 else 'NORMAL'}",
            "warn" if buf > buf_max * 0.85 else "ok"), unsafe_allow_html=True)
    with c7:
        plc_label = {"HEAT": "WARMING UP", "PRIME": "PRIMING", "RUNNING": "RUNNING",
                     "IDLE": "IDLE", "FAULT": "FAULT", "STOPPING": "STOPPING"}.get(plc_phase, plc)
        st.markdown(kpi_card(
            _icon_plc(plc), plc_label, "PLC STATE",
            f"Phase {phase}" if plc == "STARTING" else "Automated",
            "ok" if plc == "RUNNING" else ("fault" if plc == "FAULT" else "warn")), unsafe_allow_html=True)
    with c8:
        st.markdown(kpi_card(
            _icon_alarm(alarm_code != 0),
            alarm_label if alarm_code else "NORMAL", "STATUS",
            "Active alarm" if alarm_code else "No active alarms",
            "" if alarm_code == 0 else "fault"), unsafe_allow_html=True)

    # ── Trend Charts ───────────────────────────────────────────────────
    st.markdown('<div class="section-label">Process Trends</div>', unsafe_allow_html=True)
    history = engine.historian.recent(window_s=300)
    if history:
        df = pd.DataFrame(history)
        df["time"] = pd.to_datetime(df["ts"], unit="s")
        if "plc_state" in df.columns:
            df = df[df["plc_state"] != "IDLE"]

        left, right = st.columns(2)

        with left:
            fig_tank = go.Figure()
            if "tank_level" in df.columns:
                fig_tank.add_trace(go.Scatter(
                    x=df["time"], y=df["tank_level"], name="Tank Level",
                    fill="tozeroy", line=dict(color=ACC, width=2, shape="spline"),
                    fillcolor="rgba(88,166,255,0.12)",
                    hovertemplate="%{y:.1f}%<extra></extra>"))
            for y, lbl, clr in [(config.TANK_LEVEL_TARGET, f"Target {config.TANK_LEVEL_TARGET:.0f}%", ORN),
                                 (config.TANK_LEVEL_LOW, "", RED), (config.TANK_LEVEL_HIGH, "", RED)]:
                fig_tank.add_hline(y=y, line_dash="dot", line_color=f"rgba({248 if clr==RED else 210},{153 if clr==ORN else 81},{73 if clr==RED else 29},0.4)",
                                   annotation_text=lbl)
            fig_tank.update_layout(
                title="Tank Level", plot_bgcolor=CARD, paper_bgcolor=BG,
                font=dict(color=TXT, size=10), height=280,
                margin=dict(t=35, b=10, l=45, r=10),
                xaxis=dict(gridcolor=BDR, zeroline=False),
                yaxis=dict(gridcolor=BDR, zeroline=False, range=[0, 105]),
                showlegend=False, uirevision="cloud_tank")
            st.plotly_chart(fig_tank, width="stretch", key="cld_tank")

        with right:
            fig_temp = go.Figure()
            if "pasteur_temp" in df.columns:
                fig_temp.add_trace(go.Scatter(
                    x=df["time"], y=df["pasteur_temp"], name="Pasteur Temp",
                    line=dict(color=RED, width=2, shape="spline"),
                    hovertemplate="%{y:.1f}°C<extra></extra>"))
            for y, lbl in [(config.PASTEUR_SAFE_MAX, "78°C"), (config.PASTEUR_SAFE_MIN, "68°C")]:
                fig_temp.add_hline(y=y, line_dash="dot", line_color="rgba(248,81,73,0.45)",
                                   annotation_text=lbl)
            fig_temp.add_hline(y=config.PASTEUR_SETPOINT, line_dash="dash",
                               line_color="rgba(210,153,29,0.45)",
                               annotation_text=f"SP {config.PASTEUR_SETPOINT:.0f}°C")
            fig_temp.update_layout(
                title="Pasteurizer Temperature", plot_bgcolor=CARD, paper_bgcolor=BG,
                font=dict(color=TXT, size=10), height=280,
                margin=dict(t=35, b=10, l=45, r=10),
                xaxis=dict(gridcolor=BDR, zeroline=False),
                yaxis=dict(gridcolor=BDR, zeroline=False, range=[60, 82]),
                showlegend=False, uirevision="cloud_temp")
            st.plotly_chart(fig_temp, width="stretch", key="cld_temp")
    else:
        st.caption("Waiting for trend data from MQTT…")

    # ── Recent Alarms ──────────────────────────────────────────────────
    st.markdown('<div class="section-label">Recent Alarms</div>', unsafe_allow_html=True)
    alarms = engine.historian.recent_alarms(20)
    if alarms:
        adf = pd.DataFrame(alarms)
        adf["time"] = pd.to_datetime(adf["ts"], unit="s")
        adf = adf.sort_values("time", ascending=False)
        for _, row in adf.head(5).iterrows():
            atime = row["time"].strftime("%H:%M:%S")
            st.markdown(
                f'<div class="alarm-row"><b>{atime}</b> &nbsp;{row.get("label","?")} &mdash; {row.get("description","")[:140]}</div>',
                unsafe_allow_html=True)
    else:
        st.caption("No alarms recorded.")


monitor_view()

st.markdown(f"""
<div style="text-align:center;padding:12px 0 4px 0;font-size:0.55rem;color:{TXT2};">
BEVERAGE LINE MONITOR &bull; TUMA206 Group 1 &bull; MQTT topic: {config.MQTT_TOPIC_TAGS}
</div>""", unsafe_allow_html=True)
