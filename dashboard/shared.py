"""Shared singletons for the dashboard.

All three pages import get_engine() and get_assistant() from HERE so that
@st.cache_resource returns the SAME object across SCHEMATIC / TRENDS / ALARMS.
Each page defining its own get_engine() creates a SEPARATE cached instance
(Streamlit keys the cache by function object identity).
"""
from __future__ import annotations
import os

import streamlit as st

from engine import SimulationEngine, RemoteEngineProxy
from ai_assistant import AIAssistant


@st.cache_resource
def get_engine():
    """Return the engine the dashboard talks to.

    Two modes, selected by the DASHBOARD_MODE environment variable:

    * ``local`` (default) — self-contained: this process runs the full
      simulation + control + historian in-process. Used for the public
      Streamlit Cloud showcase and for a quick single-laptop run.
    * ``remote`` — display-only: this process runs NO simulation. It connects
      to the MQTT broker, shows the tag stream published by a separate local
      backend, and sends operator commands back over MQTT. This is the
      "cloud dashboard only" topology the lecturer asked for.
    """
    mode = os.environ.get("DASHBOARD_MODE", "local").strip().lower()
    if mode == "remote":
        # Display-only proxy over MQTT — never starts a simulation here.
        return RemoteEngineProxy(use_mqtt=True)

    e = SimulationEngine(use_mqtt=os.environ.get("USE_MQTT", "0") == "1")
    e.start()
    return e


@st.cache_resource
def get_assistant() -> AIAssistant:
    return AIAssistant()
