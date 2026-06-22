"""Local backend runner — the on-premise half of the cloud/local split.

This is what runs on the LOCAL machine (the laptop / plant-side PC) in the
ISA-95 / Purdue layout the lecturer drew on the whiteboard:

    L0 sensors + L1 controller (M1 plant + M2 PLC closed loop)
        -> L2/L3 historian (M3 SQLite)
        -> MQTT (btl/tags up to the cloud dashboard, btl/cmd back down)

It starts the full :class:`SimulationEngine` with the MQTT backend, publishes the
live tag stream to the broker, and listens for operator commands on the command
topic. The CLOUD dashboard (run with DASHBOARD_MODE=remote) only displays this
stream and sends commands — it never runs the simulation itself.

Run it like::

    # 1. Start a broker (local demo): mosquitto -p 1883
    #    or point at a public/hosted broker via MQTT_HOST / MQTT_PORT in config.py
    # 2. Start this backend on the local machine:
    python local_backend.py
    # 3. Start the dashboard in display-only mode (same machine or the cloud):
    #    Windows PowerShell:  $env:DASHBOARD_MODE="remote"; streamlit run dashboard/app.py
    #    macOS/Linux:         DASHBOARD_MODE=remote streamlit run dashboard/app.py

Press Ctrl+C to stop.
"""

from __future__ import annotations

import time

import config
from engine import SimulationEngine


def main() -> None:
    print("=" * 60)
    print("TUMA206 local backend — M1 plant + M2 PLC + M3 historian")
    print(f"Broker : {config.MQTT_HOST}:{config.MQTT_PORT}")
    print(f"Tags   : publishing on '{config.MQTT_TOPIC_TAGS}'")
    print(f"Command: listening on  '{config.MQTT_TOPIC_CMD}'")
    tg = "on" if (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID) else "off"
    print(f"Telegram alarms: {tg}")
    print("=" * 60)

    engine = SimulationEngine(use_mqtt=True)

    # Connectivity check: ping Telegram once at startup so you can confirm the
    # bot is wired up before any alarm happens.
    if engine.notifier.enabled:
        engine.notifier.send("TUMA206 plant backend online — alarm notifications armed.")

    # Warn clearly if MQTT was not actually reached (create_bus falls back to an
    # in-process bus, which can NOT reach a separate cloud dashboard).
    bus_kind = type(engine.bus).__name__
    if bus_kind != "MqttBus":
        print("\n[WARNING] MQTT broker not reachable — running on the in-process "
              "bus.\n          A remote/cloud dashboard will NOT see this data.\n"
              "          Start a broker (e.g. `mosquitto -p 1883`) and retry.\n")
    else:
        print(f"[OK] Connected via {bus_kind}. Waiting for dashboard commands…\n")

    engine.start()
    engine.start_line()  # auto-start production so cloud dashboard sees live data
    print("Line auto-started — cloud dashboard will show live data.\n")
    try:
        while True:
            time.sleep(5)
            latest = engine.latest()
            print(f"tick={latest.get('tick', 0)} "
                  f"PLC={latest.get('plc_state', '?')} "
                  f"temp={latest.get('pasteur_temp', 0):.1f}C "
                  f"level={latest.get('tank_level', 0):.1f}% "
                  f"alarm={config.ALARM_LABELS.get(int(latest.get('alarm_code', 0)), '-')}")
    except KeyboardInterrupt:
        print("\nStopping backend…")
    finally:
        engine.stop()
        engine.bus.close()


if __name__ == "__main__":
    main()
