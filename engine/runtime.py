"""Simulation engine - the runtime that ties the modules together.

Responsibilities:
* Run the closed control loop between M1 (PlantSimulator) and M2 (PLCController)
  once per update period. The README states the closed loop is ONLY between
  M1 and M2 - the engine honours that.
* Publish the combined tag snapshot through the M3 message bus.
* Persist the snapshot in the M3 historian.
* Apply operator commands (start/stop/fault inject/reset) coming from M4.
* Detect a stale data link (the MQTT_STALE infrastructure fault).

It can run its loop in a background thread (used by the Streamlit dashboard and
the FastAPI backend) or be stepped manually (used by tests/CLI).
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

import config
from historian import Historian
from messaging import MessageBus, create_bus
from notifications import TelegramNotifier
from plc import PLCController
from simulator import PlantSimulator


class SimulationEngine:
    def __init__(self, use_mqtt: bool = False, historian: Optional[Historian] = None,
                 bus: Optional[MessageBus] = None) -> None:
        self.plant = PlantSimulator()
        self.plc = PLCController()
        self.bus = bus or create_bus(use_mqtt=use_mqtt)
        self.historian = historian or Historian()

        # L4 enterprise edge: push a Telegram message whenever an alarm fires.
        # No-op unless a bot token + chat id are configured (env / secrets).
        self.notifier = TelegramNotifier()
        self._last_notified_alarm = config.ALARM_NONE

        # Operator commands may arrive over the M3 command topic (btl/cmd) as
        # well as via direct method calls. This is what lets a REMOTE / cloud
        # dashboard drive the line through MQTT instead of touching the engine
        # directly — the dashboard publishes a command, the engine (here, on the
        # local machine) executes it. Direct method calls still work unchanged
        # for the single-process / local demo.
        try:
            self.bus.subscribe(config.MQTT_TOPIC_CMD, self._handle_command)
        except Exception as exc:  # noqa: BLE001 - never block startup on the cmd link
            print(f"[engine] could not subscribe to command topic: {exc}")

        # Operator command state (driven by the dashboard, M4).
        self._operator_start = 0
        self._operator_stop = 0
        self._fault_inject_code = config.FAULT_NONE
        self._reset_fault = 0
        # Simulated MQTT stale: when set, the engine stops refreshing the bus.
        self._simulate_stale = False

        # Manual override: per-actuator values set by operator (bypass PLC)
        self._manual_overrides: Dict = {}   # {actuator_name: value}
        self._manual_mode = False           # global manual mode flag

        self._latest: Dict = {}
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._tick = 0

    # ------------------------------------------------------------------
    # Operator command API (called from M4 dashboard / M3 command topic)
    # ------------------------------------------------------------------
    def start_line(self) -> None:
        with self._lock:
            self._operator_start = 1
            self._operator_stop = 0
            # Clear all manual overrides on START — return to full AUTO
            self._manual_overrides.clear()

    def stop_line(self) -> None:
        with self._lock:
            self._operator_stop = 1
            self._operator_start = 0

    def inject_fault(self, code: int) -> None:
        with self._lock:
            self._fault_inject_code = int(code)
            self._reset_fault = 0
            self._simulate_stale = (int(code) == config.FAULT_MQTT_STALE)

    def reset_fault(self) -> None:
        with self._lock:
            self._fault_inject_code = config.FAULT_NONE
            self._reset_fault = 1
            self._simulate_stale = False
        self.plc.acknowledge()

    # ------------------------------------------------------------------
    # Command-over-bus dispatch (called when a command arrives on btl/cmd)
    # ------------------------------------------------------------------
    def _handle_command(self, payload: Dict) -> None:
        """Execute an operator command received from the M3 command topic.

        Expected payload shapes (JSON over MQTT, or dict in-process)::

            {"cmd": "start"}
            {"cmd": "stop"}
            {"cmd": "inject", "code": 3}
            {"cmd": "reset"}
            {"cmd": "manual_set", "name": "cooling_valve_cmd", "value": 5}
            {"cmd": "manual_clear", "name": "cooling_valve_cmd"}
            {"cmd": "clear_all"}
            {"cmd": "hard_reset"}
        """
        cmd = str(payload.get("cmd", "")).lower()
        if cmd == "start":
            self.start_line()
        elif cmd == "stop":
            self.stop_line()
        elif cmd == "inject":
            self.inject_fault(int(payload.get("code", config.FAULT_NONE)))
        elif cmd == "reset":
            self.reset_fault()
        elif cmd == "manual_set":
            self.set_manual_actuator(str(payload.get("name", "")), payload.get("value"))
        elif cmd == "manual_clear":
            self.clear_manual_actuator(str(payload.get("name", "")))
        elif cmd == "clear_all":
            self.clear_all_manuals()
        elif cmd == "hard_reset":
            self.hard_reset()

    # ------------------------------------------------------------------
    # Manual override API (operator can override any actuator anytime)
    # ------------------------------------------------------------------
    def set_manual_actuator(self, name: str, value) -> None:
        """Set a manual override for an actuator. Bypasses PLC for this actuator."""
        with self._lock:
            self._manual_overrides[name] = value

    def clear_manual_actuator(self, name: str) -> None:
        """Return an actuator to automatic PLC control."""
        with self._lock:
            self._manual_overrides.pop(name, None)

    def clear_all_manuals(self) -> None:
        """Return all actuators to automatic PLC control."""
        with self._lock:
            self._manual_overrides.clear()

    @property
    def manual_overrides(self) -> Dict:
        with self._lock:
            return dict(self._manual_overrides)

    # ------------------------------------------------------------------
    # One control-loop iteration
    # ------------------------------------------------------------------
    def step(self) -> Dict:
        with self._lock:
            operator_start = self._operator_start
            operator_stop = self._operator_stop
            fault_code = self._fault_inject_code
            reset_fault = self._reset_fault
            simulate_stale = self._simulate_stale
            # start/stop/reset are edge-triggered: consume them after one tick.
            self._operator_start = 0
            self._operator_stop = 0
            self._reset_fault = 0

        # Infrastructure fault (DATA_STALE / MQTT down): the data link to the
        # dashboard is broken. No fresh tags are published or stored, so the
        # values the operator sees must FREEZE. We surface the last snapshot
        # with the DATA_STALE alarm set, and keep its old timestamp so the data
        # is visibly stale. The physical line is not stepped while frozen; it
        # resumes from the same state when the fault is reset.
        if simulate_stale:
            with self._lock:
                frozen = dict(self._latest) if self._latest else {}
                frozen["data_stale_flag"] = 1
                frozen["alarm_code"] = config.ALARM_DATA_STALE
                frozen["plc_state"] = frozen.get("plc_state", config.PLC_RUNNING)
                frozen.setdefault("ts", time.time())
                self._latest = frozen
                self._tick += 1
            self._maybe_notify(frozen)
            return frozen

        data_stale_flag = 0
        if self.bus.seconds_since_last(config.MQTT_TOPIC_TAGS) > config.DATA_STALE_TIMEOUT_S:
            # only meaningful once we have published at least once
            if self._tick > 0:
                data_stale_flag = 1

        # --- M2 reads the previous sensor snapshot + operator buttons ---
        sensors_for_plc = dict(self.plant.outputs())
        sensors_for_plc["operator_start"] = operator_start
        sensors_for_plc["operator_stop"] = operator_stop
        sensors_for_plc["data_stale_flag"] = data_stale_flag
        # Pass manual override values directly — PLC uses them as fixed outputs
        # and adapts remaining auto actuators around them.
        with self._lock:
            overrides = dict(self._manual_overrides)
        control = self.plc.step(sensors_for_plc, manual_overrides=overrides)

        # --- M1 applies the actuator commands + fault injection ---
        plant_cmd = dict(control)
        plant_cmd["fault_inject_code"] = fault_code
        plant_cmd["reset_fault"] = reset_fault
        sensors = self.plant.step(plant_cmd)

        # --- Build the combined tag snapshot (plant + control + alarm) ---
        snapshot: Dict = {}
        snapshot.update(sensors)
        snapshot.update(control)
        snapshot["data_stale_flag"] = data_stale_flag
        snapshot["ts"] = time.time()
        snapshot["tick"] = self._tick

        # --- M3: publish through the bus and store in the historian ---
        self.bus.publish(config.MQTT_TOPIC_TAGS, snapshot)
        self.historian.record(snapshot)

        with self._lock:
            self._latest = snapshot
            self._tick += 1
        self._maybe_notify(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    def _maybe_notify(self, snapshot: Dict) -> None:
        """Push a Telegram alarm message on an alarm transition (edge-triggered).

        Fires once when the active alarm changes to a non-zero code, so the
        operator's phone buzzes on every NEW fault without being spammed every
        tick while the alarm persists.
        """
        alarm_now = int(snapshot.get("alarm_code", config.ALARM_NONE))
        if alarm_now == self._last_notified_alarm:
            return
        if alarm_now != config.ALARM_NONE:
            self.notifier.notify_alarm(alarm_now, snapshot)
        self._last_notified_alarm = alarm_now

    # ------------------------------------------------------------------
    # Background loop control
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            start = time.time()
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                print(f"[engine] step error: {exc}")
            elapsed = time.time() - start
            time.sleep(max(0.0, config.TICK_INTERVAL_S - elapsed))

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def hard_reset(self) -> None:
        """Full factory reset — clears all state, history, and restarts the engine."""
        was_running = self._running
        if was_running:
            self.stop()
        with self._lock:
            self.plant.reset()
            self.plc.reset()
            self._operator_start = 0
            self._operator_stop = 0
            self._fault_inject_code = config.FAULT_NONE
            self._reset_fault = 0
            self._simulate_stale = False
            self._manual_overrides.clear()
            self._latest = {}
            self._tick = 0
        self.historian.clear()
        if was_running:
            self.start()

    # ------------------------------------------------------------------
    def latest(self) -> Dict:
        with self._lock:
            return dict(self._latest)

    @property
    def is_running(self) -> bool:
        return self._running
