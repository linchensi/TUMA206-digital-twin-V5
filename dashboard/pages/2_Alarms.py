"""ALARMS — AI operator assistant + alarm event log"""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

import config
from shared import get_engine, get_assistant

BG = "#0d1117"
CARD_BG = "#161b22"
BORDER = "#30363d"
TEXT = "#c9d1d9"
TEXT_DIM = "#b0b8c0"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
ORANGE = "#d2991d"
RED = "#f85149"

# ══════════════════════════════════════════════════════════════════════
# CSS — dark industrial theme
# ══════════════════════════════════════════════════════════════════════
st.markdown(f"""
<style>
    .stApp {{ background: {BG}; }}
    header[data-testid="stHeader"] {{
        background: linear-gradient(90deg, {BG}, {CARD_BG}, {BG});
        border-bottom: 1px solid {BORDER};
    }}
    header[data-testid="stHeader"] * {{ color: {TEXT} !important; }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {BG}, #010409);
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
    .section-label {{
        font-size: 0.65rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.1em; color: {TEXT_DIM};
        margin: 14px 0 8px 0; padding-bottom: 6px;
        border-bottom: 1px solid {BORDER};
    }}
    .sidebar-section {{
        font-size: 0.55rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.1em; color: {ACCENT}; margin-top: 10px; margin-bottom: 4px;
    }}
    .diagnosis-panel {{
        background: {CARD_BG}; border-radius: 8px;
        border: 1px solid {BORDER}; border-left: 4px solid {ACCENT};
        padding: 14px 18px; margin: 8px 0;
    }}
    .chat-user {{
        background: #1c2128; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 8px 14px; margin: 4px 0; color: {TEXT}; font-size: 0.82rem;
    }}
    .chat-ai {{
        background: {CARD_BG}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT};
        border-radius: 8px; padding: 10px 14px; margin: 4px 0;
        color: {TEXT}; font-size: 0.85rem; line-height: 1.6;
    }}
    .confidence-high {{
        background: {GREEN}33; color: {GREEN}; padding: 2px 10px;
        border-radius: 10px; font-size: 0.7rem; font-weight: 700;
    }}
    .confidence-medium {{
        background: {ORANGE}33; color: {ORANGE}; padding: 2px 10px;
        border-radius: 10px; font-size: 0.7rem; font-weight: 700;
    }}
    .confidence-model {{
        background: {ACCENT}33; color: {ACCENT}; padding: 2px 10px;
        border-radius: 10px; font-size: 0.7rem; font-weight: 700;
    }}
    [data-testid="stMetricLabel"] {{ color: {TEXT_DIM} !important; }}
    [data-testid="stMetricValue"] {{ color: {TEXT} !important; }}
    [data-testid="stMetricDelta"] {{ color: {GREEN} !important; }}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SHARED SINGLETONS
# ══════════════════════════════════════════════════════════════════════
engine = get_engine()
assistant = get_assistant()

for k, v in [("refresh_s", 3), ("window_s", config.HISTORY_WINDOW_S),
             ("chat_history", []), ("ai_cache", {}),
             ("forced_diag", False)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(f"""
    <div style="text-align:center;padding:8px 0;">
        <div style="font-size:1rem;font-weight:700;color:{TEXT};letter-spacing:0.06em;">ALARMS</div>
        <div style="font-size:0.52rem;color:{ACCENT};letter-spacing:0.1em;">AI DIAGNOSTICS</div>
    </div>""", unsafe_allow_html=True)
    st.divider()

    # ── API key ──────────────────────────────────────────────────────
    st.markdown('<div class="sidebar-section">AI Configuration</div>', unsafe_allow_html=True)
    saved_key = st.session_state.get("ai_api_key", assistant.api_key)
    new_key = st.text_input(
        "API Key (OpenAI or Anthropic)", value=saved_key, type="password",
        placeholder="sk-proj-… (OpenAI) or sk-ant-… (Claude)", label_visibility="collapsed",
    )
    if new_key != saved_key:
        st.session_state["ai_api_key"] = new_key
        assistant.update_api_key(new_key)
        st.session_state["ai_cache"] = {}
    using = assistant.using_llm
    if using:
        st.caption(f"Engine: :green[{assistant.provider_label}] (connected)")
    else:
        st.caption("Engine: Rule-based")
    # Surface the exact reason the LLM is not active so it can be fixed.
    if assistant.init_error:
        st.caption(f":red[{assistant.init_error}]")
    if assistant.last_error:
        st.caption(f":orange[Last API call failed → {assistant.last_error}]")

    st.divider()
    st.markdown('<div class="sidebar-section">Actions</div>', unsafe_allow_html=True)

    if st.button("Force Analysis", use_container_width=True):
        st.session_state["ai_cache"] = {}
        st.session_state["forced_diag"] = True
        st.rerun()

    if st.button("Clear Chat", use_container_width=True):
        st.session_state["chat_history"] = []
        st.session_state["ai_cache"] = {}
        st.rerun()

    st.divider()
    st.session_state["refresh_s"] = st.slider("Refresh (s)", 1, 10, st.session_state["refresh_s"])
    st.session_state["window_s"] = st.slider("History (s)", 30, 600, st.session_state["window_s"], 30)

# ══════════════════════════════════════════════════════════════════════
# PAGE HEADER
# ══════════════════════════════════════════════════════════════════════
st.markdown(f"""
<div style="background:linear-gradient(90deg,{BG},{CARD_BG},{BG});border-radius:8px;
padding:10px 22px;margin-bottom:6px;border-bottom:1px solid {BORDER};">
<div style="font-size:1.1rem;font-weight:700;color:#f0f6fc;letter-spacing:0.06em;">ALARMS</div>
<div style="font-size:0.62rem;color:{TEXT_DIM};letter-spacing:0.05em;">FAULT DIAGNOSIS &bull; AI CONSULTATION &bull; EVENT HISTORY</div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# HELPER: send a question to AI and append to chat
# ══════════════════════════════════════════════════════════════════════
def _ask(display_label: str, ai_prompt: str, latest: dict, history: list) -> None:
    """Append a clean user label to chat, send the full prompt to AI."""
    st.session_state["chat_history"].append({"role": "user", "content": display_label})
    with st.spinner("AI analyzing..."):
        answer = assistant.consult(ai_prompt, latest, history)
    st.session_state["chat_history"].append({"role": "ai", "content": answer})


# ══════════════════════════════════════════════════════════════════════
# LIVE VIEW (auto-refreshing fragment — status + auto-diagnosis only)
# ══════════════════════════════════════════════════════════════════════
@st.fragment(run_every=f"{st.session_state['refresh_s']}s")
def alarms_view():
    latest = engine.latest()
    alarm_code = int(latest.get("alarm_code", config.ALARM_NONE))
    history = engine.historian.recent(window_s=st.session_state["window_s"])

    # ── Status row ───────────────────────────────────────────────────
    plc_state = latest.get("plc_state", "IDLE")
    alarm_label = config.ALARM_LABELS.get(alarm_code, "None")
    fault_label = config.FAULT_LABELS.get(int(latest.get("fault_status", 0)), "Normal")
    c1, c2, c3 = st.columns(3)
    c1.metric("PLC State", plc_state)
    c2.metric("Active Alarm", alarm_label, delta="ACTIVE" if alarm_code else "CLEAR")
    c3.metric("Fault Status", fault_label)

    # Inline sensor strip
    t = float(latest.get("pasteur_temp", 0))
    lv = float(latest.get("tank_level", 0))
    fl = float(latest.get("flow_rate", 0))
    buf = int(latest.get("conveyor_queue", 0))
    co = float(latest.get("cooler_temp", 0))
    t_ok = config.PASTEUR_SAFE_MIN <= t <= config.PASTEUR_SAFE_MAX
    lv_ok = config.TANK_LEVEL_LOW <= lv <= config.TANK_LEVEL_HIGH
    tc = GREEN if t_ok else RED
    lc = GREEN if lv_ok else ORANGE
    st.markdown(
        f'<div style="display:flex;gap:20px;font-size:0.72rem;color:{TEXT_DIM};padding:4px 0 2px 0;">'
        f'<span>Pasteur <b style="color:{tc}">{t:.1f}°C</b></span>'
        f'<span>Tank <b style="color:{lc}">{lv:.1f}%</b></span>'
        f'<span>Flow <b style="color:{TEXT}">{fl:.1f} L/min</b></span>'
        f'<span>Cooler <b style="color:{TEXT}">{co:.1f}°C</b></span>'
        f'<span>Buffer <b style="color:{TEXT}">{buf} btl</b></span>'
        f'</div>', unsafe_allow_html=True)

    st.divider()

    # ── Auto-Diagnosis ───────────────────────────────────────────────
    st.markdown('<div class="section-label">Diagnosis</div>', unsafe_allow_html=True)

    forced = st.session_state.get("forced_diag", False)
    if forced:
        st.session_state["forced_diag"] = False

    if alarm_code:
        # Active alarm → auto-diagnose
        cache = st.session_state["ai_cache"]
        sensor_fp = f"{t:.0f}_{lv:.0f}_{fl:.0f}"
        cache_key = f"diag_{alarm_code}_{sensor_fp}"
        if cache_key not in cache:
            with st.spinner("Analyzing alarm..."):
                cache[cache_key] = assistant.diagnose(latest, alarm_code, history)
        result = cache.get(cache_key, {})
        conf = result.get("confidence_level", "unknown")
        conf_class = {"high": "confidence-high", "medium": "confidence-medium"}.get(conf, "confidence-model")
        st.markdown(f"""
        <div class="diagnosis-panel">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                <span style="font-size:0.95rem;font-weight:700;color:{RED};">&#9888; {result.get('diagnosis_label','')}</span>
                <span class="{conf_class}">{conf.upper()}</span>
                <span style="font-size:0.62rem;color:{TEXT_DIM};">via {result.get('engine','')}</span>
            </div>
            <div style="color:{TEXT};line-height:1.65;font-size:0.87rem;">
                {result.get('recommendation_text','')}
            </div>
        </div>""", unsafe_allow_html=True)

    elif forced:
        # No alarm but operator clicked "Force Analysis" → run health check
        cache_key = f"health_{t:.0f}_{lv:.0f}_{fl:.0f}"
        cache = st.session_state["ai_cache"]
        if cache_key not in cache:
            prompt = (
                f"Run a system health check. PLC={plc_state}, "
                f"Pasteurizer={t:.1f}°C (band 68-78), Cooler={co:.1f}°C (limit 28), "
                f"Tank={lv:.0f}% (target 55, range 30-80), Flow={fl:.1f} L/min, "
                f"Buffer={buf}/60 bottles. Completed={latest.get('bottles_completed',0)}."
            )
            with st.spinner("Running health check..."):
                answer = assistant.consult(prompt, latest, history)
            cache[cache_key] = answer
        health = cache.get(cache_key, "")
        st.markdown(f"""
        <div class="diagnosis-panel">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                <span style="font-size:0.95rem;font-weight:700;color:{ACCENT};">System Health Check</span>
                <span style="font-size:0.62rem;color:{TEXT_DIM};">on demand</span>
            </div>
            <div style="color:{TEXT};line-height:1.65;font-size:0.87rem;">{health.replace(chr(10), '<br>')}</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div style="color:{TEXT_DIM};font-size:0.85rem;padding:8px 0 4px 0;">'
            f'No active alarm. Press <b>Force Analysis</b> for a system health check, '
            f'or use the consultation panel below.</div>', unsafe_allow_html=True)

    st.divider()

    # ── Alarm Event Log ───────────────────────────────────────────────
    st.markdown('<div class="section-label">Alarm Event Log</div>', unsafe_allow_html=True)
    alarms = engine.historian.recent_alarms(100)
    if alarms:
        adf = pd.DataFrame(alarms)
        adf["time"] = pd.to_datetime(adf["ts"], unit="s")
        adf = adf.sort_values("time", ascending=False)
        total = len(adf)
        unique = adf["label"].nunique() if "label" in adf.columns else 0
        st.caption(f"{total} events · {unique} types")
        display_cols = [c for c in ["time", "label", "description"] if c in adf.columns]
        if display_cols:
            st.dataframe(adf[display_cols], use_container_width=True, hide_index=True, height=220)
        if "label" in adf.columns and total > 1:
            dist = adf["label"].value_counts()
            dcols = st.columns(min(len(dist), 6))
            for i, (lbl, cnt) in enumerate(dist.items()):
                dcols[i % len(dcols)].metric(lbl, cnt)
    else:
        st.info("No alarm events yet. Start the line and inject faults to see alarms here.")


alarms_view()

# ══════════════════════════════════════════════════════════════════════
# AI CONSULTATION (outside fragment — stable across auto-refreshes)
# ══════════════════════════════════════════════════════════════════════
st.divider()
st.markdown('<div class="section-label">AI Consultation</div>', unsafe_allow_html=True)

# Quick-action buttons
latest = engine.latest()
alarm_code = int(latest.get("alarm_code", 0))
alarm_label = config.ALARM_LABELS.get(alarm_code, "None")
t = float(latest.get("pasteur_temp", 0))
lv = float(latest.get("tank_level", 0))
fl = float(latest.get("flow_rate", 0))
co = float(latest.get("cooler_temp", 0))
buf = int(latest.get("conveyor_queue", 0))
plc_state = latest.get("plc_state", "IDLE")
state_ctx = (
    f"PLC={plc_state}, Pasteur={t:.1f}°C (68-78), Cooler={co:.1f}°C (<28), "
    f"Tank={lv:.0f}% (target 55), Flow={fl:.1f} L/min, Buffer={buf}/60"
)

quick_actions = [
    ("Diagnose Alarm", "Alarm Analysis",
     f"Active alarm: {alarm_label}. Diagnose root cause and recommend immediate actions. {state_ctx}"),
    ("Analyze State", "Process Analysis",
     f"Analyze overall process state. Identify any risks or abnormal readings. {state_ctx}"),
    ("Recovery Steps", "Recovery Plan",
     f"Active alarm: {alarm_label}. Provide step-by-step recovery to restore normal production. {state_ctx}"),
    ("Risk Check", "Risk Assessment",
     f"Assess potential failure risks in the next 5 minutes based on current trends. {state_ctx}"),
]

history = engine.historian.recent(window_s=st.session_state["window_s"])
qcols = st.columns(len(quick_actions))
for col, (label, display, prompt) in zip(qcols, quick_actions):
    if col.button(label, use_container_width=True, key=f"qbtn_{label}"):
        _ask(f"Requested: {display}", prompt, latest, history)
        st.rerun()

# Chat history
chat = st.session_state.get("chat_history", [])
if chat:
    chat_html = ""
    for msg in chat[-20:]:  # show last 20 messages
        if msg["role"] == "user":
            chat_html += f'<div class="chat-user"><b style="color:{ACCENT};">Operator</b><br>{msg["content"]}</div>'
        else:
            content = msg["content"].replace("\n", "<br>")
            chat_html += f'<div class="chat-ai"><b style="color:{GREEN};">AI Assistant</b><br>{content}</div>'
    st.markdown(
        f'<div style="max-height:360px;overflow-y:auto;padding:2px 0;">{chat_html}</div>',
        unsafe_allow_html=True)
else:
    st.caption("Ask a question or use a quick-action button above to consult the AI assistant.")

# Free-form input (OUTSIDE fragment — won't reset on auto-refresh)
inp_col, btn_col = st.columns([5, 1])
with inp_col:
    user_q = st.text_input(
        "Ask the AI assistant",
        placeholder="Type a question about the process, alarms, or recovery steps...",
        label_visibility="collapsed", key="chat_free_input",
    )
with btn_col:
    if st.button("Ask", use_container_width=True, key="chat_send_btn"):
        if user_q.strip():
            _ask(user_q.strip(), user_q.strip(), latest, history)
            st.rerun()
