"""Shared configuration for the Intelligent Beverage Production Line supervisor.

Every module (M1-M5) imports constants from here so that pin names, set-points,
fault codes and alarm codes stay consistent across the whole system.
"""

from __future__ import annotations

# Load variables from a local .env file if python-dotenv is available, so that
# ANTHROPIC_API_KEY / USE_MQTT are picked up without exporting them manually.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 1. Global timing
# ---------------------------------------------------------------------------
# The whole system advances one "tick" per update period. The README assumes 1 s.
# For a live demo you can speed the wall-clock loop up with TICK_INTERVAL_S while
# keeping the simulated period at 1 s.
UPDATE_PERIOD_S = 1.0          # simulated time represented by one tick
TICK_INTERVAL_S = 1.0         # real seconds between ticks in the background loop

# ---------------------------------------------------------------------------
# 2. Process set-points and physical limits (M1 / M2 share these)
# ---------------------------------------------------------------------------
TANK_LEVEL_LOW = 30.0          # %  -> inlet valve fully open below this
TANK_LEVEL_HIGH = 80.0         # %  -> inlet valve fully closed above this
TANK_LEVEL_TARGET = 55.0       # %  -> target level (midpoint of hysteresis band)
TANK_LEVEL_MIN_PUMP = 10.0     # %  -> do not run feed pump below this (dry-run guard)
TANK_CRITICAL_HIGH = 90.0      # %  -> overflow alarm (early warning before 100%)
TANK_CRITICAL_LOW = 15.0       # %  -> empty alarm (above MIN_PUMP=10, gives time to react)

PASTEUR_SETPOINT = 72.0        # degC target pasteurization temperature
PASTEUR_SAFE_MIN = 68.0        # degC lower safe bound
PASTEUR_SAFE_MAX = 78.0        # degC upper safe bound

# ---------------------------------------------------------------------------
# Bottling line (S4 Filler + S5 Conveyor/Capper)
# ---------------------------------------------------------------------------
# Industrial inline/rotary filler with FILL_NOZZLES nozzles operating in
# lockstep: a carrier of N empty bottles indexes in, all nozzles fill together,
# then the full carrier indexes out to the capper in one motion. This is how
# real rotary monoblock fillers work (all heads on one rotating carousel).
FILL_NOZZLES = 4               # parallel filling nozzles (one carrier batch)
FILL_VOLUME_ML = 500.0         # nominal bottle size (mL) — sets fill time vs flow
FILL_GAP_TICKS = 1             # index/transfer dead-time between carrier batches

# Conveyor / capper accumulation buffer between filler and packing.
# Bottles ENTER the buffer as the filler discharges a batch, and LEAVE the
# buffer as the capper/conveyor moves them downstream. The buffer level is the
# integral of (fill_rate - discharge_rate): it grows when the filler outpaces
# the conveyor and drains when the conveyor outpaces the filler.
CONVEYOR_MAX_BOTTLES = 60      # buffer capacity (bottles on the belt)
CONVEYOR_TARGET_BUFFER = 12    # AUTO conveyor holds the buffer near this level
CONVEYOR_BOTTLES_PER_TICK_AT_100 = 1.5  # discharge throughput at 100% belt speed

COOLER_SETPOINT = 25.0         # degC target product temperature after cooling (PI setpoint)
COOLER_FLOOR = 15.0            # degC coldest achievable at 100% cooling valve
COOLER_OPEN_ABOVE = 30.0       # degC reference threshold for cooling valve
COOLER_MAX_BOTTLING = 28.0     # degC — do NOT bottle when cooler_temp exceeds this
COOLER_ALARM_HIGH = 32.0       # degC — COOLER_HIGH alarm above this

AMBIENT_TEMP = 25.0            # degC ambient temperature (also natural cooler idle temp)

# Number of consecutive abnormal ticks before the PLC latches an alarm.
ALARM_DEBOUNCE_TICKS = 3

# ---------------------------------------------------------------------------
# 3. Fault injection codes (Dashboard -> Plant Simulator)
# ---------------------------------------------------------------------------
FAULT_NONE = 0
FAULT_TEMP_STUCK = 1           # pasteur_temp sensor frozen
FAULT_PUMP_FAIL = 2            # pump runs but no flow / no feedback
FAULT_TEMP_EXCURSION = 3       # pasteurization temperature drifts out of range
FAULT_MQTT_STALE = 4           # data layer stops refreshing -> stale data

FAULT_LABELS = {
    FAULT_NONE: "Normal",
    FAULT_TEMP_STUCK: "Temperature sensor stuck",
    FAULT_PUMP_FAIL: "Feed pump failure (no flow)",
    FAULT_TEMP_EXCURSION: "Pasteurization temperature excursion",
    FAULT_MQTT_STALE: "Data link stale (MQTT)",
}

# ---------------------------------------------------------------------------
# 4. Alarm codes (PLC Controller -> Dashboard / AI)
# ---------------------------------------------------------------------------
ALARM_NONE = 0
ALARM_SENSOR_TEMP_STUCK = 10
ALARM_PUMP_NO_FLOW = 20
ALARM_TEMP_OUT_OF_RANGE = 30
ALARM_DATA_STALE = 40
ALARM_TANK_OVERFLOW = 50
ALARM_TANK_EMPTY = 51
ALARM_BUFFER_HIGH = 52
ALARM_COOLER_HIGH = 53

ALARM_LABELS = {
    ALARM_NONE: "No alarm",
    ALARM_SENSOR_TEMP_STUCK: "SENSOR_TEMP_STUCK",
    ALARM_PUMP_NO_FLOW: "PUMP_NO_FLOW",
    ALARM_TEMP_OUT_OF_RANGE: "TEMP_OUT_OF_RANGE",
    ALARM_DATA_STALE: "DATA_STALE",
    ALARM_TANK_OVERFLOW: "TANK_OVERFLOW",
    ALARM_TANK_EMPTY: "TANK_EMPTY",
    ALARM_BUFFER_HIGH: "BUFFER_HIGH",
    ALARM_COOLER_HIGH: "COOLER_HIGH",
}

# Human readable, operator-facing alarm descriptions (used by M4 and as a hint to M5).
ALARM_DESCRIPTIONS = {
    ALARM_NONE: "All process values are within normal range.",
    ALARM_SENSOR_TEMP_STUCK: (
        "Pasteurization temperature reading is frozen while the heater command "
        "is changing. The temperature sensor is likely faulty."
    ),
    ALARM_PUMP_NO_FLOW: (
        "The feed pump is commanded ON but there is no flow and no pump feedback. "
        "The pump or its drive has likely failed."
    ),
    ALARM_TEMP_OUT_OF_RANGE: (
        "Pasteurization temperature is outside the safe range "
        f"({PASTEUR_SAFE_MIN}-{PASTEUR_SAFE_MAX} degC) for several cycles. "
        "Product safety may be compromised."
    ),
    ALARM_DATA_STALE: (
        "Live data from the plant has stopped updating. The MQTT data link or "
        "publisher may be down."
    ),
    ALARM_TANK_OVERFLOW: (
        f"Raw tank level has exceeded {TANK_CRITICAL_HIGH:.0f}%. Risk of overflow. "
        "Inlet valve should be closed and feed pump stopped immediately."
    ),
    ALARM_TANK_EMPTY: (
        f"Raw tank level has dropped below {TANK_CRITICAL_LOW:.0f}%. Risk of "
        "dry-running the feed pump and pasteurizer. Inlet valve should be opened "
        "and feed pump stopped."
    ),
    ALARM_BUFFER_HIGH: (
        f"Conveyor buffer is approaching capacity ({CONVEYOR_MAX_BOTTLES} bottles). "
        "Filler back-pressure is active; increase conveyor speed or reduce pump "
        "speed to clear the accumulation buffer before it overflows."
    ),
    ALARM_COOLER_HIGH: (
        f"Cooler outlet temperature has exceeded {COOLER_ALARM_HIGH:.0f}°C. "
        "Product is too hot for safe bottling. Increase cooling valve opening "
        "or reduce feed pump speed to lower the thermal load on the cooler. "
        "Check glycol supply and heat exchanger for fouling."
    ),
}

# ---------------------------------------------------------------------------
# 5. PLC state-machine states
# ---------------------------------------------------------------------------
PLC_IDLE = "IDLE"
PLC_STARTING = "STARTING"
PLC_RUNNING = "RUNNING"
PLC_FAULT = "FAULT"
PLC_STOPPING = "STOPPING"

# ---------------------------------------------------------------------------
# 6. Production stages (for display)
# ---------------------------------------------------------------------------
STAGE_NAMES = {
    "S1": "Raw / Balance Tank",
    "S2": "Pasteurizer",
    "S3": "Cooler",
    "S4": "Filler",
    "S5": "Capper / Conveyor",
}

# ---------------------------------------------------------------------------
# 7. Tag names published to the data layer (M3)
# ---------------------------------------------------------------------------
# Numeric tags that are stored as dedicated columns in the historian and used
# for trend charts on the dashboard.
NUMERIC_TAGS = [
    "tank_level",
    "pasteur_temp",
    "cooler_temp",
    "flow_rate",
    "bottle_count",
    "heater_power_cmd",
    "cooling_valve_cmd",
]

# ---------------------------------------------------------------------------
# 8. MQTT / data-layer settings (M3) and AI settings (M5)
# ---------------------------------------------------------------------------
import os as _os

# MQTT broker. Defaults to the public HiveMQ test broker so the cloud dashboard
# AND a local backend can reach the SAME broker with zero setup (route B). Any of
# these can be overridden via environment variables / Streamlit secrets to point
# at a private broker (e.g. HiveMQ Cloud with TLS + auth on port 8883).
MQTT_HOST = _os.environ.get("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = int(_os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = _os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = _os.environ.get("MQTT_PASSWORD", "")
MQTT_TLS = _os.environ.get("MQTT_TLS", "0") == "1"
# Public brokers are shared by the whole world, so namespace our topics with a
# unique prefix to avoid colliding with other users. The local backend and the
# dashboard MUST use the SAME prefix (override both with MQTT_TOPIC_PREFIX).
MQTT_TOPIC_PREFIX = _os.environ.get("MQTT_TOPIC_PREFIX", "tuma206grp1bvg")
MQTT_TOPIC_TAGS = f"{MQTT_TOPIC_PREFIX}/tags"   # plant + control + alarm tags snapshot
MQTT_TOPIC_CMD = f"{MQTT_TOPIC_PREFIX}/cmd"     # operator commands from dashboard
DATA_STALE_TIMEOUT_S = 5.0            # mark data stale if no update within this window

# ── Telegram alarm notifications (optional) ───────────────────────────
# When a token + chat id are provided (env / Streamlit secrets), the local
# backend pushes a Telegram message every time an alarm fires. Get the token
# from @BotFather; get the chat id by messaging the bot then calling
# https://api.telegram.org/bot<token>/getUpdates (or add the bot to a group).
TELEGRAM_BOT_TOKEN = _os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = _os.environ.get("TELEGRAM_CHAT_ID", "").strip()

import tempfile
DB_PATH = _os.path.join(tempfile.gettempdir(), "historian.db")  # SQLite historian (works on Streamlit Cloud)
CSV_EXPORT_PATH = _os.path.join(tempfile.gettempdir(), "history_export.csv")
HISTORY_WINDOW_S = 300                # default trend window shown on the dashboard

# ---------------------------------------------------------------------------
# 9. Shared utility
# ---------------------------------------------------------------------------
def clamp(value: float, low: float, high: float) -> float:
    """Clamp a value between low and high bounds (shared by M1 and M2)."""
    return max(low, min(high, value))


# LLM settings for the AI assistant (M5). The assistant supports BOTH providers
# and auto-detects which one to use from the API key prefix:
#   * key starts with "sk-ant-"  -> Anthropic Claude
#   * key starts with "sk-" (e.g. sk-proj-...) -> OpenAI
# The key is read from ANTHROPIC_API_KEY or OPENAI_API_KEY (env / Streamlit
# secrets) or typed into the dashboard sidebar. If none is set, the assistant
# falls back to the built-in rule-based engine.
ANTHROPIC_MODEL = _os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
OPENAI_MODEL = _os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
LLM_MAX_TOKENS = 400
# Backwards-compatible alias (older code referenced ANTHROPIC_MAX_TOKENS).
ANTHROPIC_MAX_TOKENS = LLM_MAX_TOKENS
