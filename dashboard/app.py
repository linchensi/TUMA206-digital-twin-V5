"""M4 Dashboard — Production Line Control Center"""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

# ── Streamlit Cloud secrets -> environment variables ──────────────────
# This MUST run before config.py is imported (it reads these at import time) and
# before any page runs. On Streamlit Cloud, put the keys below in
# Manage app -> Settings -> Secrets. Locally, use .streamlit/secrets.toml.
#   OPENAI_API_KEY / ANTHROPIC_API_KEY   -> M5 AI assistant
#   DASHBOARD_MODE = "remote"            -> display-only over MQTT (route B)
#   MQTT_HOST / MQTT_PORT / MQTT_USERNAME / MQTT_PASSWORD / MQTT_TLS / MQTT_TOPIC_PREFIX
for _k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_MODEL", "ANTHROPIC_MODEL",
           "DASHBOARD_MODE", "USE_MQTT", "MQTT_HOST", "MQTT_PORT",
           "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_TLS", "MQTT_TOPIC_PREFIX",
           "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
    try:
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
    except Exception:  # noqa: BLE001 - no secrets file is fine
        pass

st.set_page_config(page_title="Production Line", layout="wide", page_icon="⏣")

# ── Navigation ────────────────────────────────────────────────────────
# Explicit page definitions give full control over sidebar labels.
# Each page file lives alongside this app.py (SCHEMATIC.py) or in pages/.
pg = st.navigation(
    [
        st.Page("SCHEMATIC.py", title="SCHEMATIC", default=True),
        st.Page("pages/1_Trends.py", title="TRENDS"),
        st.Page("pages/2_Alarms.py", title="ALARMS"),
    ],
    position="sidebar",
)
pg.run()
