"""SCHEMATIC - Process Flow Diagram + Stage Details + KPIs"""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

import config
from shared import get_engine
from svg_pid import build_pid_svg

# Theme: Industrial Dark
BG = "#0d1117"
CARD_BG = "#161b22"
BORDER = "#30363d"
TEXT = "#c9d1d9"
TEXT_DIM = "#b0b8c0"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
ORANGE = "#d2991d"
RED = "#f85149"
CYAN = "#39d2c0"

st.markdown(f"""
<style>
    .stApp {{ background: {BG}; }}
    .main .block-container {{ padding-top: 0.6rem; }}
    header[data-testid="stHeader"] {{
        background: linear-gradient(90deg, #0d1117, #161b22, #0d1117);
        border-bottom: 1px solid {BORDER};
    }}
    header[data-testid="stHeader"] * {{ color: {TEXT} !important; }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #0d1117, #010409);
        border-right: 1px solid {BORDER};
    }}
    [data-testid="stSidebar"] * {{ color: {TEXT_DIM} !important; }}
    [data-testid="stSidebar"] .stButton > button {{
        background: #21262d !important; color: {TEXT} !important;
        border: 1px solid {BORDER} !important; border-radius: 6px !important;
        font-weight: 600 !important; letter-spacing: 0.03em !important;
        text-transform: uppercase !important; font-size: 0.75rem !important;
        transition: all 0.15s !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: #30363d !important; border-color: {ACCENT} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:active {{
        transform: scale(0.97) !important; background: {ACCENT}22 !important;
    }}
    [data-testid="stSidebar"] hr {{ border-color: {BORDER} !important; }}

    .banner-ok {{
        background: linear-gradient(90deg, #0d3320, #1a4028);
        color: {GREEN}; border: 1px solid {GREEN}44;
        border-radius: 6px; padding: 8px 18px; font-weight: 600;
        font-size: 0.82rem; margin: 6px 0; letter-spacing: 0.02em;
    }}
    .banner-alarm {{
        background: linear-gradient(90deg, #3d1212, #4d1818);
        color: {RED}; border: 1px solid {RED}44;
        border-radius: 6px; padding: 8px 18px; font-weight: 600;
        font-size: 0.82rem; margin: 6px 0;
        animation: alarm-pulse 1.8s infinite; letter-spacing: 0.02em;
    }}
    .banner-frozen {{
        background: linear-gradient(90deg, #1a1a1a, #252525);
        color: #888; border: 1px solid #444;
        border-radius: 6px; padding: 8px 18px; font-weight: 600;
        font-size: 0.82rem; margin: 6px 0; letter-spacing: 0.02em;
    }}
    @keyframes alarm-pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.82}} }}

    .section-label {{
        font-size: 0.65rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.1em; color: {TEXT_DIM};
        margin: 14px 0 8px 0; padding-bottom: 6px;
        border-bottom: 1px solid {BORDER};
    }}

    /* Equipment card in flow diagram */
    .eq-card {{
        background: {CARD_BG}; border: 1px solid {BORDER};
        border-radius: 8px; padding: 12px 10px; text-align: center;
        min-height: 110px; display: flex; flex-direction: column;
        justify-content: center; align-items: center;
        transition: all 0.3s; position: relative;
    }}
    .eq-card.active {{ border-color: {GREEN}88; box-shadow: 0 0 12px {GREEN}18; }}
    .eq-card.warn  {{ border-color: {ORANGE}88; box-shadow: 0 0 12px {ORANGE}18; }}
    .eq-card.fault {{ border-color: {RED}88; box-shadow: 0 0 12px {RED}18; }}
    .eq-card.idle  {{ border-color: {BORDER}; }}
    .eq-card .eq-name {{
        font-size: 0.6rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.06em; color: {TEXT_DIM}; margin-bottom: 4px;
    }}
    .eq-card .eq-value {{
        font-size: 1.25rem; font-weight: 700; color: {TEXT};
        margin: 2px 0; font-family: 'SF Mono', 'Consolas', monospace;
    }}
    .eq-card .eq-sub {{
        font-size: 0.58rem; color: {TEXT_DIM}; margin-top: 2px;
    }}
    .eq-card .eq-status {{
        position: absolute; top: 6px; right: 8px; width: 8px; height: 8px;
        border-radius: 50%;
    }}
    .eq-card .man-badge {{
        position: absolute; top: 50%; left: -4px; transform: translateY(-50%);
        background: {ORANGE}; color: #000; font-size: 0.5rem; font-weight: 800;
        padding: 2px 5px; border-radius: 3px; letter-spacing: 0.05em;
    }}

    /* Pipe connector between equipment */
    .pipe-connector {{
        display: flex; align-items: center; justify-content: center;
        min-width: 40px; height: 100%;
    }}
    .pipe-arrow {{
        font-size: 1.2rem; color: {ACCENT}; opacity: 0.7;
    }}
    .pipe-arrow.idle {{ color: {BORDER}; }}

    /* Tank fill bar (inside eq-card) */
    .tank-fill-container {{
        width: 100%; height: 28px; background: #0d1117;
        border: 1px solid {BORDER}; border-radius: 4px;
        margin: 4px 0; position: relative; overflow: hidden;
    }}
    .tank-fill {{
        position: absolute; bottom: 0; left: 0; right: 0;
        background: linear-gradient(0deg, {ACCENT}88, {ACCENT}44);
        transition: height 0.5s ease;
    }}

    .stage-card {{
        background: {CARD_BG}; border-radius: 8px; padding: 0;
        border: 1px solid {BORDER}; overflow: hidden; transition: all 0.2s;
    }}
    .stage-card:hover {{ border-color: {ACCENT}66; }}
    .stage-card-header {{
        padding: 7px 12px; font-weight: 700; font-size: 0.72rem;
        letter-spacing: 0.04em; color: #fff; display: flex;
        justify-content: space-between; align-items: center;
    }}
    .stage-card-body {{ padding: 8px 12px; }}
    .stage-data-row {{
        display: flex; justify-content: space-between; align-items: baseline;
        padding: 2px 0; border-bottom: 1px solid {BORDER}44;
        font-size: 0.68rem;
    }}
    .stage-data-label {{ color: {TEXT_DIM}; }}
    .stage-data-value {{ color: {TEXT}; font-weight: 600; }}
    .stage-requirement {{
        font-size: 0.58rem; color: {TEXT_DIM}; margin-top: 4px; font-style: italic;
    }}
    .status-badge {{
        display: inline-block; padding: 1px 8px; border-radius: 3px;
        font-size: 0.58rem; font-weight: 700; letter-spacing: 0.05em;
        text-transform: uppercase;
    }}
    .sidebar-section {{
        font-size: 0.55rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.1em; color: {ACCENT}; margin-top: 10px; margin-bottom: 4px;
    }}
    .kpi-card {{
        background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 6px;
        padding: 8px 12px; margin: 2px 0; min-height: 72px;
    }}
    .kpi-label {{
        font-size: 0.55rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.08em; margin-bottom: 2px;
    }}
    .kpi-value {{
        font-size: 1.35rem; font-weight: 700; color: {TEXT}; line-height: 1.2;
    }}
    .kpi-unit {{ font-size: 0.7rem; font-weight: 400; color: {TEXT_DIM}; }}
    .kpi-sub {{ font-size: 0.56rem; color: {TEXT_DIM}; margin-top: 1px; }}
</style>
""", unsafe_allow_html=True)

# Engine
engine = get_engine()

# Session
ACTUATORS = ["pump_cmd", "inlet_valve_cmd", "heater_power_cmd", "cooling_valve_cmd", "conveyor_cmd"]
for a in ACTUATORS:
    if f"man_{a}" not in st.session_state:
        st.session_state[f"man_{a}"] = False
    if f"val_{a}" not in st.session_state:
        st.session_state[f"val_{a}"] = 0 if a == "heater_power_cmd" else 0
if "refresh_s" not in st.session_state:
    st.session_state["refresh_s"] = 3

def apply_manual(act_name, is_manual, value):
    st.session_state[f"man_{act_name}"] = is_manual
    st.session_state[f"val_{act_name}"] = value
    if is_manual:
        engine.set_manual_actuator(act_name, value)
    else:
        engine.clear_manual_actuator(act_name)

# ══════════════════════════════════════════════════════════════════════
# PROCESS FLOW — Equipment Cards
# ══════════════════════════════════════════════════════════════════════
def eq_card(name, value, sub, cls="active", man=False):
    dot = {"active": GREEN, "warn": ORANGE, "fault": RED, "idle": TEXT_DIM}.get(cls, TEXT_DIM)
    man_html = '<div class="man-badge">M</div>' if man else ""
    return (f'<div class="eq-card {cls}">'
            f'{man_html}'
            f'<div class="eq-status" style="background:{dot};"></div>'
            f'<div class="eq-name">{name}</div>'
            f'<div class="eq-value">{value}</div>'
            f'<div class="eq-sub">{sub}</div></div>')

def eq_tank(name, value, level_pct, sub, cls="active", man=False):
    dot = {"active": GREEN, "warn": ORANGE, "fault": RED, "idle": TEXT_DIM}.get(cls, TEXT_DIM)
    man_html = '<div class="man-badge">M</div>' if man else ""
    return (f'<div class="eq-card {cls}">'
            f'{man_html}'
            f'<div class="eq-status" style="background:{dot};"></div>'
            f'<div class="eq-name">{name}</div>'
            f'<div class="tank-fill-container">'
            f'<div class="tank-fill" style="height:{max(0,min(100,level_pct))}%;"></div>'
            f'</div>'
            f'<div class="eq-value">{value}</div>'
            f'<div class="eq-sub">{sub}</div></div>')

def pipe(cls="active"):
    c = ACCENT if cls == "active" else BORDER
    return f'<div class="pipe-connector"><span style="color:{c};font-size:1.4rem;">→</span></div>'


# ══════════════════════════════════════════════════════════════════════
# STAGE & KPI
# ══════════════════════════════════════════════════════════════════════
def stage_card(stage_id, name, status, color, rows, requirement=""):
    badge = f'<span class="status-badge" style="background:{color}22;color:{color};">{status}</span>'
    rows_html = "".join(
        f'<div class="stage-data-row"><span class="stage-data-label">{l}</span><span class="stage-data-value">{v}</span></div>'
        for l, v in rows)
    req_html = f'<div class="stage-requirement">{requirement}</div>' if requirement else ""
    return (f'<div class="stage-card">'
            f'<div class="stage-card-header" style="background:{color}33;border-bottom:2px solid {color}55;">'
            f'<span>{stage_id}: {name}</span>{badge}</div>'
            f'<div class="stage-card-body">{rows_html}{req_html}</div></div>')

def kpi_card(label, value, unit, color, sub=""):
    return (f'<div class="kpi-card">'
            f'<div class="kpi-label" style="color:{color};">{label}</div>'
            f'<div class="kpi-value">{value}<span class="kpi-unit"> {unit}</span></div>'
            f'<div class="kpi-sub">{sub}</div></div>')


# ══════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(f"""
    <div style="text-align:center;padding:8px 0;">
        <div style="font-size:1rem;font-weight:700;color:{TEXT};letter-spacing:0.06em;">SCHEMATIC</div>
        <div style="font-size:0.52rem;color:{ACCENT};letter-spacing:0.1em;">LINE SUPERVISOR</div>
    </div>""", unsafe_allow_html=True)
    st.divider()
    st.markdown('<div class="sidebar-section">Line</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("START", use_container_width=True):
        for a in ACTUATORS:
            st.session_state[f"man_{a}"] = False; engine.clear_manual_actuator(a)
        engine.start_line()
        st.toast("Line started", icon=":material/play_arrow:")
    if c2.button("STOP", use_container_width=True):
        engine.stop_line()
        for a in ACTUATORS:
            st.session_state[f"man_{a}"] = False; engine.clear_manual_actuator(a)
        st.toast("Line stopped", icon=":material/stop:")
    if st.button("HARD RESET", use_container_width=True, type="secondary"):
        engine.hard_reset()
        for a in ACTUATORS:
            st.session_state[f"man_{a}"] = False
            st.session_state[f"val_{a}"] = 0 if a == "heater_power_cmd" else 0
        for k in ["_init_inlet", "_init_pump", "_init_heater", "_init_cool", "_init_conv"]:
            st.session_state.pop(k, None)
        st.session_state["ai_cache"] = {}
        st.session_state["chat_history"] = []
        st.session_state["freeze_sensors"] = False
        st.session_state["freeze_actuators"] = False
        st.session_state["frozen_sensor_df"] = None
        st.session_state["frozen_actuator_df"] = None
        st.toast("System fully reset", icon=":material/restart_alt:")
    st.divider()
    st.markdown('<div class="sidebar-section">Manual Override</div>', unsafe_allow_html=True)

    live = engine.latest()  # snapshot current engine state for slider init

    man_inlet = st.checkbox("Inlet Valve", key="cb_inlet")
    if man_inlet:
        if not st.session_state.get("_init_inlet", False):
            st.session_state["val_inlet_valve_cmd"] = float(live.get("inlet_valve_cmd", 50))
            st.session_state["_init_inlet"] = True
        v = st.slider("Inlet %", 0, 100, int(st.session_state.get("val_inlet_valve_cmd", 50)), key="sl_inlet", label_visibility="collapsed")
        apply_manual("inlet_valve_cmd", True, float(v))
    else:
        st.session_state["_init_inlet"] = False
        apply_manual("inlet_valve_cmd", False, 0.0)

    man_pump = st.checkbox("Feed Pump", key="cb_pump")
    if man_pump:
        if not st.session_state.get("_init_pump", False):
            st.session_state["val_pump_cmd"] = float(live.get("pump_cmd", 50))
            st.session_state["_init_pump"] = True
        v = st.slider("Speed %", 0, 100, int(st.session_state.get("val_pump_cmd", 50)), key="sl_pump", label_visibility="collapsed")
        apply_manual("pump_cmd", True, float(v))
    else:
        st.session_state["_init_pump"] = False
        apply_manual("pump_cmd", False, 0.0)

    man_heater = st.checkbox("Heater", key="cb_heater")
    if man_heater:
        if not st.session_state.get("_init_heater", False):
            st.session_state["val_heater_power_cmd"] = float(live.get("heater_power_cmd", 50))
            st.session_state["_init_heater"] = True
        v = st.slider("Power %", 0, 100, int(st.session_state.get("val_heater_power_cmd", 50)), 5, key="sl_heater", label_visibility="collapsed")
        apply_manual("heater_power_cmd", True, float(v))
    else:
        st.session_state["_init_heater"] = False
        apply_manual("heater_power_cmd", False, 0.0)

    man_cool = st.checkbox("Cooler", key="cb_cool")
    if man_cool:
        if not st.session_state.get("_init_cool", False):
            st.session_state["val_cooling_valve_cmd"] = float(live.get("cooling_valve_cmd", 30))
            st.session_state["_init_cool"] = True
        v = st.slider("Cooler %", 0, 100, int(st.session_state.get("val_cooling_valve_cmd", 30)), key="sl_cool", label_visibility="collapsed")
        apply_manual("cooling_valve_cmd", True, float(v))
    else:
        st.session_state["_init_cool"] = False
        apply_manual("cooling_valve_cmd", False, 0.0)

    man_conv = st.checkbox("Conveyor", key="cb_conv")
    if man_conv:
        if not st.session_state.get("_init_conv", False):
            st.session_state["val_conveyor_cmd"] = float(live.get("conveyor_cmd", 50))
            st.session_state["_init_conv"] = True
        v = st.slider("Speed %", 0, 100, int(st.session_state.get("val_conveyor_cmd", 50)), key="sl_conv", label_visibility="collapsed")
        apply_manual("conveyor_cmd", True, float(v))
    else:
        st.session_state["_init_conv"] = False
        apply_manual("conveyor_cmd", False, 0.0)

    st.divider()
    st.markdown('<div class="sidebar-section">Fault Injection</div>', unsafe_allow_html=True)
    fc = st.selectbox("Type", options=list(config.FAULT_LABELS.keys()),
                      format_func=lambda c: config.FAULT_LABELS[c], label_visibility="collapsed")
    c3, c4 = st.columns(2)
    if c3.button("INJECT", use_container_width=True):
        engine.inject_fault(fc); st.toast(f"Injected: {config.FAULT_LABELS[fc]}", icon=":material/warning:")
    if c4.button("RESET", use_container_width=True):
        engine.reset_fault(); st.toast("Fault cleared", icon=":material/refresh:")
    st.divider()
    st.session_state["refresh_s"] = st.slider("Refresh", 1, 10, st.session_state["refresh_s"])
    st.caption(f"Manual: {len(engine.manual_overrides)} active")


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div style="background:linear-gradient(90deg,#0d1117,#161b22,#0d1117);border-radius:8px;
padding:10px 22px;margin-bottom:6px;border-bottom:1px solid {BORDER};">
<div style="font-size:1.1rem;font-weight:700;color:#f0f6fc;letter-spacing:0.06em;">SCHEMATIC</div>
<div style="font-size:0.62rem;color:{TEXT_DIM};letter-spacing:0.05em;">PROCESS FLOW DIAGRAM &bull; STAGE DETAILS &bull; PRODUCTION KPIs</div>
</div>""", unsafe_allow_html=True)


@st.fragment(run_every=f"{st.session_state['refresh_s']}s")
def live_view():
    latest = engine.latest()
    alarm_code = int(latest.get("alarm_code", 0))
    plc_state = latest.get("plc_state", config.PLC_IDLE)
    frozen = alarm_code == config.ALARM_DATA_STALE

    sp = int(latest.get("startup_phase", 2))
    if frozen:
        st.markdown(f'<div class="banner-frozen">DATA LINK FROZEN &mdash; PLC: {plc_state}</div>', unsafe_allow_html=True)
    elif alarm_code:
        st.markdown(f'<div class="banner-alarm">ALARM [{config.ALARM_LABELS.get(alarm_code)}] &mdash; '
                    f'{config.ALARM_DESCRIPTIONS.get(alarm_code)}</div>', unsafe_allow_html=True)
    elif plc_state == "STARTING" and sp == 0:
        st.markdown(f'<div class="banner-ok">WARMING UP &mdash; Heating pasteurizer &amp; cooler, filling tank…</div>', unsafe_allow_html=True)
    elif plc_state == "STARTING" and sp == 1:
        st.markdown(f'<div class="banner-ok">PRIMING PUMP &mdash; Establishing flow, stabilizing temperature…</div>', unsafe_allow_html=True)
    else:
        n_man = len(engine.manual_overrides)
        st.markdown(f'<div class="banner-ok">NORMAL &mdash; PLC: {plc_state}'
                    f'{f" &mdash; {n_man} manual" if n_man else ""}</div>', unsafe_allow_html=True)

    # ── Data ──
    level = float(latest.get("tank_level", 0))
    temp  = float(latest.get("pasteur_temp", 0))
    cool  = float(latest.get("cooler_temp", 0))
    flow  = float(latest.get("flow_rate", 0))
    bc    = int(latest.get("bottle_count", 0))
    belt  = int(latest.get("conveyor_queue", 0))
    belt_max = int(latest.get("conveyor_max", config.CONVEYOR_MAX_BOTTLES))
    bp    = int(latest.get("bottle_present", 0))
    hc    = float(latest.get("heater_power_cmd", 0))
    pc    = float(latest.get("pump_cmd", 0))
    ic    = float(latest.get("inlet_valve_cmd", 0))
    cc    = float(latest.get("cooling_valve_cmd", 0))
    fc    = int(latest.get("fill_valve_cmd", 0))
    cvc   = float(latest.get("conveyor_cmd", 0))
    pf    = int(latest.get("pump_feedback", 0))
    fcode = int(latest.get("fault_status", 0))
    flow_ok = (plc_state in ("RUNNING", "STARTING")) and pc > 0 and pf == 1 and not frozen
    man = set(engine.manual_overrides or {})

    s1_ok = config.TANK_LEVEL_LOW <= level <= config.TANK_LEVEL_HIGH
    s2_ok = config.PASTEUR_SAFE_MIN <= temp <= config.PASTEUR_SAFE_MAX
    s3_ok = cool <= config.COOLER_MAX_BOTTLING
    s4_ok = fc and bp
    s5_ok = cvc > 0

    # ── Process Flow (SVG P&ID) ──
    st.markdown('<div class="section-label">Process Flow</div>', unsafe_allow_html=True)
    # Inject _manuals key so svg_pid can draw manual badges
    latest["_manuals"] = list(engine.manual_overrides or {})
    svg_html = build_pid_svg(latest)
    st.markdown(svg_html, unsafe_allow_html=True)

    # ── Filler Nozzle Status ──
    nozzle_status = latest.get("nozzle_status", [0]*4)
    fill_phase = latest.get("fill_phase", "INDEX")
    fill_prog = float(latest.get("fill_progress", 0.0))
    prog_pct = int(fill_prog * 100)
    prog_bar_filled = int(fill_prog * 16)
    prog_bar = "█" * prog_bar_filled + "░" * (16 - prog_bar_filled)
    lane_html = '<div style="display:flex;gap:16px;align-items:center;margin:4px 0 10px 0;">'
    lane_html += '<span style="font-size:0.65rem;color:#b0b8c0;font-weight:600;">NOZZLES:</span>'
    for i, ns in enumerate(nozzle_status):
        if ns == 2: dot, label = "#3fb950", f"N{i+1} FULL"
        elif ns == 1: dot, label = "#58a6ff", f"N{i+1} FILL"
        else: dot, label = "#30363d", f"N{i+1} IDLE"
        lane_html += (f'<span style="display:flex;align-items:center;gap:4px;font-size:0.6rem;color:#c9d1d9;">'
                      f'<span style="width:8px;height:8px;border-radius:50%;background:{dot};display:inline-block;"></span>'
                      f'{label}</span>')
    phase_color = ACCENT if fill_phase == "FILL" else TEXT_DIM
    lane_html += (f'<span style="margin-left:12px;font-size:0.6rem;color:{phase_color};font-weight:600;">'
                  f'{fill_phase} {prog_bar} {prog_pct}%</span>')
    lane_html += '</div>'
    st.markdown(lane_html, unsafe_allow_html=True)

    # ── Stage Cards ──
    st.markdown('<div class="section-label">Stage Details</div>', unsafe_allow_html=True)
    sc = st.columns(5)
    cards = [
        ("S1", "RAW TANK", "NORMAL" if s1_ok else ("LOW" if level<config.TANK_LEVEL_LOW else "HIGH"),
         GREEN if s1_ok else ORANGE,
         [("Level", f"{level:.1f} %"), ("Inlet Valve", f"{ic:.0f}%"),
          ("Feed Pump", f"{pc:.0f}%"), ("Flow", f"{flow:.1f} L/min")],
         f"Target {config.TANK_LEVEL_TARGET:.0f}% &middot; Range {config.TANK_LEVEL_LOW:.0f}-{config.TANK_LEVEL_HIGH:.0f}%"),
        ("S2", "PASTEURIZER", "NORMAL" if s2_ok else ("LOW" if temp<config.PASTEUR_SAFE_MIN else "HIGH"),
         GREEN if s2_ok else RED,
         [("Temp", f"{temp:.1f} °C"), ("Heater", f"{hc:.0f}%"),
          ("Safe Band", f"{config.PASTEUR_SAFE_MIN:.0f}-{config.PASTEUR_SAFE_MAX:.0f}°C"),
          ("Status", "At SP" if abs(temp-config.PASTEUR_SETPOINT)<2 else ("Heating" if temp<config.PASTEUR_SETPOINT else "Hot"))],
         f"Setpoint {config.PASTEUR_SETPOINT:.0f}°C &middot; PI control"),
        ("S3", "COOLER", "READY" if s3_ok else "COOLING",
         CYAN if s3_ok else ORANGE,
         [("Temp", f"{cool:.1f} °C"), ("Cooler", f"{cc:.0f}%"),
          ("Target", f"{config.COOLER_SETPOINT:.0f}°C"), ("Limit", f"{config.COOLER_MAX_BOTTLING:.0f}°C")],
         f"PI control &middot; Opens >{config.COOLER_OPEN_ABOVE:.0f}°C"),
        ("S4", "FILLER", "FILLING" if s4_ok else ("WAITING" if bp else "IDLE"),
         GREEN if s4_ok else (ORANGE if bp else TEXT_DIM),
         [("Flow Rate", f"{flow:.1f} L/min"), ("Fill Valve", "ON" if fc else "OFF"),
          ("Phase", latest.get("fill_phase", "INDEX")),
          ("Progress", f"{int(float(latest.get('fill_progress',0))*100)}%")],
         f"4-nozzle inline monoblock &middot; all heads fill in lockstep &middot; {sum(1 for n in latest.get('nozzle_status',[0]*4) if n>0)}/4 active"),
        ("S5", "CAPPER", "RUNNING" if s5_ok else "STOPPED",
         GREEN if s5_ok else TEXT_DIM,
         [("On Belt", f"{belt}/{belt_max}"), ("Completed", str(latest.get("bottles_completed",0))),
          ("Conveyor", f"{cvc:.0f}%"), ("Buffer Tgt", f"{config.CONVEYOR_TARGET_BUFFER} bottles")],
         f"Belt capacity: {belt_max} &middot; P-ctrl: {config.CONVEYOR_BOTTLES_PER_TICK_AT_100:.1f} bott/tick @100%"),
    ]
    for col, (sid, nm, stt, clr, rows, req) in zip(sc, cards):
        col.markdown(stage_card(sid, nm, stt, clr, rows, req), unsafe_allow_html=True)

    # ── KPIs ──
    st.markdown('<div class="section-label">Production Summary</div>', unsafe_allow_html=True)
    kc = st.columns(6)
    kc[0].markdown(kpi_card("LEVEL", f"{level:.1f}", "%", GREEN if s1_ok else ORANGE, f"Tgt {config.TANK_LEVEL_TARGET:.0f}%"), unsafe_allow_html=True)
    kc[1].markdown(kpi_card("PASTEUR", f"{temp:.1f}", "°C", GREEN if s2_ok else RED, f"SP {config.PASTEUR_SETPOINT:.0f}°C"), unsafe_allow_html=True)
    kc[2].markdown(kpi_card("COOLER", f"{cool:.1f}", "°C", CYAN if s3_ok else ORANGE, f"Tgt {config.COOLER_SETPOINT:.0f}°C"), unsafe_allow_html=True)
    kc[3].markdown(kpi_card("FLOW", f"{flow:.1f}", "L/min", GREEN if flow>0 else TEXT_DIM, f"Pump {pc:.0f}%"), unsafe_allow_html=True)
    kc[4].markdown(kpi_card("COMPLETED", str(latest.get("bottles_completed",0)), "", CYAN if latest.get("bottles_completed",0)>0 else TEXT_DIM, f"In Queue: {belt}"), unsafe_allow_html=True)
    kc[5].markdown(kpi_card("PLC", plc_state, "", GREEN if plc_state=="RUNNING" else (RED if plc_state=="FAULT" else ORANGE), f"Tick {latest.get('tick',0)}"), unsafe_allow_html=True)


live_view()
