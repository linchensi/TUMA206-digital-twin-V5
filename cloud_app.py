"""Cloud Monitoring Dashboard — deploy this on Streamlit Cloud.

Data flow:  local_backend.py  --MQTT-->  HiveMQ Cloud  --MQTT-->  this app
           (your laptop)                (cloud broker)           (Streamlit Cloud)

How to deploy (one-time setup):
  1. Go to https://streamlit.io/cloud → New app
  2. Select your GitHub repo, set Main file path = "cloud_app.py"
  3. In Manage App → Settings → Secrets, add:
       DASHBOARD_MODE = "remote"
       MQTT_HOST = "<your-cluster>.s1.eu.hivemq.cloud"
       MQTT_PORT = "8883"
       MQTT_TLS = "1"
       MQTT_USERNAME = "<your-username>"
       MQTT_PASSWORD = "<your-password>"
       MQTT_TOPIC_PREFIX = "<your-topic-prefix>"
  4. Save → Reboot app. Open the URL — live data appears when local_backend.py is running.

Local testing:  DASHBOARD_MODE=remote streamlit run cloud_app.py
"""
import os, runpy, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

# Community Cloud requires page configuration before cached resources or
# visible elements are created.  Keeping this first prevents a blank app shell.
st.set_page_config(
    page_title="Beverage Line Monitor",
    layout="wide",
    page_icon="🏭",
)

# Load .env for local testing
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Load Streamlit Cloud secrets
try:
    for key in ["MQTT_HOST", "MQTT_PORT", "MQTT_TLS", "MQTT_USERNAME",
                "MQTT_PASSWORD", "MQTT_TOPIC_PREFIX",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DASHBOARD_MODE"]:
        try:
            val = st.secrets.get(key)
            if val is not None and key not in os.environ:
                os.environ[key] = str(val)
        except Exception:
            pass
except Exception:
    pass

os.environ.setdefault("DASHBOARD_MODE", "remote")

# Do not import the page only for its side effects: Python executes an imported
# module once per process, so every browser session after the first would get a
# blank Streamlit shell until the app was rebooted.  run_path executes the page
# body for every Streamlit script run/session.
runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "cloud.py"),
    run_name="__streamlit_cloud_page__",
)
