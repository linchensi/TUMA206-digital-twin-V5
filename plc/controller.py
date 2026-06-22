"""M2 - PLC Controller.

Runs the control logic for the beverage line: a start/stop state machine,
per-stage proportional control with actuator adaptation, and comprehensive
fault detection that translates abnormal sensor patterns into alarm codes.

This module reads the plant's sensor + feedback pins and the operator buttons,
and produces actuator command pins plus an alarm code and PLC state. It never
touches physics directly — that is M1's job.

Manual override: the PLC receives a manual_overrides dict {actuator: value}.
It uses those values as FIXED outputs and adapts remaining auto-controlled
actuators to compensate within safe limits. Fault detection runs regardless
of manual/auto mode — safety interlocks are never bypassed.

Port specification (see README section 5):
    inputs : tank_level, pasteur_temp, cooler_temp, flow_rate, bottle_present,
             pump_feedback, valve_feedback, operator_start, operator_stop
    outputs: pump_cmd, inlet_valve_cmd, heater_power_cmd, cooling_valve_cmd,
             conveyor_cmd, fill_valve_cmd, capper_cmd, alarm_code, plc_state
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import config


@dataclass
class PLCController:
    """Scan-cycle controller. Call :meth:`step` once per update period."""

    state: str = config.PLC_IDLE
    alarm_code: int = config.ALARM_NONE

    # --- internal control accumulators (PI-style) ---
    heater_power_cmd: float = 0.0   # accumulated heater output (0-100%)
    cooling_valve_cmd: float = 0.0  # accumulated cooling output (0-100%)
    pump_cmd: float = 0.0           # accumulated feed pump output (0-100%)

    # --- discrete fill control memory ---
    _fill_timer: int = field(default=0, repr=False)

    # last pump command issued (used by the no-flow fault detector) ---
    last_pump_cmd: float = field(default=0.0, repr=False)

    # --- fault-detection debounce counters ---
    _temp_stuck_count: int = field(default=0, repr=False)
    _no_flow_count: int = field(default=0, repr=False)
    _temp_range_count: int = field(default=0, repr=False)
    _tank_overflow_count: int = field(default=0, repr=False)
    _tank_empty_count: int = field(default=0, repr=False)
    _buffer_high_count: int = field(default=0, repr=False)
    _cooler_high_count: int = field(default=0, repr=False)
    _prev_temp: float = field(default=-999.0, repr=False)
    _prev_heater_cmd: float = field(default=0.0, repr=False)
    # True once the pasteurizer has reached the safe band at least once.
    _warmed_up: bool = field(default=False, repr=False)

    # Sequential startup: 0=HEAT (heat+fill, no pump), 1=PRIME (pump ramp-up), 2=RUNNING
    _startup_phase: int = field(default=0, repr=False)
    _startup_ticks: int = field(default=0, repr=False)
    # Track previous state to detect FAULT→IDLE transition for fast recovery
    _prev_state: str = field(default=config.PLC_IDLE, repr=False)
    # Track previous manual overrides to detect manual→auto transitions
    _prev_manuals: set = field(default_factory=set, repr=False)

    def reset(self) -> None:
        self.state = config.PLC_IDLE
        self.alarm_code = config.ALARM_NONE
        self.heater_power_cmd = 0.0
        self.cooling_valve_cmd = 0.0
        self.pump_cmd = 0.0
        self._fill_timer = 0
        self.last_pump_cmd = 0.0
        self._temp_stuck_count = 0
        self._no_flow_count = 0
        self._temp_range_count = 0
        self._tank_overflow_count = 0
        self._tank_empty_count = 0
        self._buffer_high_count = 0
        self._cooler_high_count = 0
        self._startup_phase = 0
        self._startup_ticks = 0
        self._prev_temp = -999.0
        self._prev_heater_cmd = 0.0
        self._warmed_up = False
        self._prev_state = config.PLC_IDLE
        self._prev_manuals = set()

    # ------------------------------------------------------------------
    def step(self, sensors: Dict,
             manual_overrides: Dict[str, float] = None) -> Dict:
        """One scan cycle: update state machine, detect faults, run control.

        Args:
            sensors: plant sensor values + operator_start/stop + data_stale_flag
            manual_overrides: {actuator_name: value} for operator-overridden actuators.
                              The PLC uses these as FIXED outputs and adapts
                              remaining auto actuators around them.

        Returns:
            dict of actuator commands + alarm_code + plc_state
        """
        if manual_overrides is None:
            manual_overrides = {}

        operator_start = int(sensors.get("operator_start", 0))
        operator_stop = int(sensors.get("operator_stop", 0))
        data_stale = int(sensors.get("data_stale_flag", 0))

        # 1. State machine ----------------------------------------------
        self._prev_state = self.state
        self._update_state(operator_start, operator_stop)

        # 2. Fault detection (always active — safety is never bypassed) --
        self._detect_faults(sensors, data_stale)

        # Detect FAULT→IDLE transition (auto-clear or manual acknowledge)
        if self._prev_state == config.PLC_FAULT and self.state == config.PLC_IDLE:
            self._fast_recovery_init()

        # 3. Control logic ----------------------------------------------
        running = self.state in (config.PLC_RUNNING, config.PLC_STARTING)
        serious = self.alarm_code in (config.ALARM_PUMP_NO_FLOW,
                                       config.ALARM_TEMP_OUT_OF_RANGE,
                                       config.ALARM_SENSOR_TEMP_STUCK,
                                       config.ALARM_DATA_STALE,
                                       config.ALARM_TANK_OVERFLOW,
                                       config.ALARM_TANK_EMPTY,
                                       config.ALARM_BUFFER_HIGH,
                                       config.ALARM_COOLER_HIGH)
        if serious:
            self.state = config.PLC_FAULT
            running = False

        if running:
            cmds = self._run_control(sensors, manual_overrides)
        else:
            cmds = self._safe_outputs()

        cmds["alarm_code"] = self.alarm_code
        cmds["plc_state"] = self.state
        return cmds

    # ------------------------------------------------------------------
    def _update_state(self, operator_start: int, operator_stop: int) -> None:
        if operator_stop:
            self.state = config.PLC_STOPPING
        if self.state == config.PLC_STOPPING:
            self.state = config.PLC_IDLE
            self._startup_phase = 0
            return

        if self.state == config.PLC_FAULT:
            if self.alarm_code == config.ALARM_NONE:
                self.state = config.PLC_IDLE
                self._startup_phase = 0
            return

        if operator_start and self.state == config.PLC_IDLE:
            self.state = config.PLC_STARTING
            self._startup_phase = 0  # Begin HEAT phase
            self._startup_ticks = 0
            # Do NOT pre-charge pump — pump starts only when temp+level ready
            self.pump_cmd = 0.0
        # STARTING→RUNNING transition is now handled by startup sequencer in _run_control

    # ------------------------------------------------------------------
    def _fast_recovery_init(self) -> None:
        """Reset accumulators on FAULT→IDLE for clean auto restart."""
        self.heater_power_cmd = self.heater_power_cmd * 0.6
        self.cooling_valve_cmd = self.cooling_valve_cmd * 0.4
        self.pump_cmd = 0.0
        self._fill_timer = 0
        self._startup_phase = 0
        self._startup_ticks = 0

    # ------------------------------------------------------------------
    def _run_control(self, sensors: Dict,
                     man: Dict[str, float]) -> Dict:
        """Run auto control with adaptation around manual overrides.

        Strategy:
        - Manual actuators use their override values directly.
        - Auto actuators adapt around manual constraints where possible.
        - All safety limits are still enforced; violations trigger alarms.
        """
        tank_level = float(sensors.get("tank_level", 50.0))
        pasteur_temp = float(sensors.get("pasteur_temp", 25.0))
        cooler_temp = float(sensors.get("cooler_temp", 25.0))
        flow_rate = float(sensors.get("flow_rate", 0.0))

        # Track manual→auto transitions: reset ALL related debounce counters
        # so auto has time to recover before faults re-trigger.
        released = self._prev_manuals - set(man.keys())
        if "heater_power_cmd" in released or "cooling_valve_cmd" in released:
            self._temp_range_count = 0
            self._temp_stuck_count = 0
        if "pump_cmd" in released:
            self._no_flow_count = 0
        if "inlet_valve_cmd" in released:
            self._tank_overflow_count = 0
            self._tank_empty_count = 0
        if "conveyor_cmd" in released:
            self._buffer_high_count = 0
        if "cooling_valve_cmd" in released:
            self._cooler_high_count = 0
        self._prev_manuals = set(man.keys())
        bottle_present = int(sensors.get("bottle_present", 0))

        man_inlet  = "inlet_valve_cmd" in man
        man_pump   = "pump_cmd" in man
        man_heater = "heater_power_cmd" in man
        man_cool   = "cooling_valve_cmd" in man
        man_conv   = "conveyor_cmd" in man
        man_fill   = "fill_valve_cmd" in man

        # ── S1: Feed Pump (computed first — inlet feed-forward references it) ──
        if man_pump:
            pump_cmd = float(man["pump_cmd"])
            self.pump_cmd = pump_cmd
        else:
            if tank_level <= config.TANK_LEVEL_MIN_PUMP:
                self.pump_cmd = 0.0
            else:
                if man_inlet:
                    manual_inflow = float(man["inlet_valve_cmd"])
                    target_pump = min(manual_inflow * 1.2, 100.0)
                else:
                    if tank_level >= config.TANK_LEVEL_HIGH:
                        target_pump = 100.0
                    elif tank_level <= config.TANK_LEVEL_LOW:
                        target_pump = 30.0
                    else:
                        frac = (tank_level - config.TANK_LEVEL_LOW) / (config.TANK_LEVEL_HIGH - config.TANK_LEVEL_LOW)
                        target_pump = 30.0 + 70.0 * frac
                self.pump_cmd += 0.4 * (target_pump - self.pump_cmd)
                self.pump_cmd = _clamp(self.pump_cmd, 0.0, 100.0)
            pump_cmd = self.pump_cmd

        # ── S1: Inlet Valve (feed-forward from pump + level trim) ──────
        # Feed-forward matches pump consumption: pump 100% = 4.0 u/t out,
        # inlet 100% = 6.0 u/t in → valve ≈ 67% of pump to match steady state.
        # P-trim on tank level error adjusts around the feed-forward baseline.
        if man_inlet:
            inlet_valve_cmd = float(man["inlet_valve_cmd"])
        else:
            ff_valve = (pump_cmd / 100.0) * (4.0 / 6.0) * 100.0
            level_error = tank_level - config.TANK_LEVEL_TARGET
            trim = -3.0 * level_error
            inlet_valve_cmd = _clamp(ff_valve + trim, 0.0, 100.0)

        # ── S2: Heater (PI with anti-windup) ──────────────────────
        if man_heater:
            heater_power_cmd = round(float(man["heater_power_cmd"]), 1)
            self.heater_power_cmd = heater_power_cmd
        else:
            error = config.PASTEUR_SETPOINT - pasteur_temp
            # Gain adapts to flow rate: higher flow = more cold mass entering
            # = faster heat loss = need stronger controller response.
            if flow_rate > 35:
                gain = 5.0
            elif flow_rate > 20:
                gain = 3.0
            elif flow_rate < 8:
                gain = 1.5
            else:
                gain = 2.0
            # Conditional integration: block only if already at limit AND
            # error would push further into saturation (true anti-windup)
            candidate = self.heater_power_cmd + gain * error
            sat_high = self.heater_power_cmd >= 100.0 and error > 0
            sat_low  = self.heater_power_cmd <= 0.0 and error < 0
            if not sat_high and not sat_low:
                self.heater_power_cmd = _clamp(candidate, 0.0, 100.0)
            heater_power_cmd = round(self.heater_power_cmd, 1)

        # ── S3: Cooler (PI with anti-windup) ──────────────────────
        if man_cool:
            cooling_valve_cmd = float(man["cooling_valve_cmd"])
            self.cooling_valve_cmd = cooling_valve_cmd
        else:
            cool_error = cooler_temp - config.COOLER_SETPOINT
            cool_gain = 2.5
            candidate = self.cooling_valve_cmd + cool_gain * cool_error
            sat_high = self.cooling_valve_cmd >= 100.0 and cool_error > 0
            sat_low  = self.cooling_valve_cmd <= 0.0 and cool_error < 0
            if not sat_high and not sat_low:
                self.cooling_valve_cmd = _clamp(candidate, 0.0, 100.0)
            cooling_valve_cmd = round(self.cooling_valve_cmd, 1)

        # ── S4/S5: Bottling readiness ────────────────────────────────
        # Bottle only when product is both pasteurized AND cooled — a hard
        # food-safety interlock. cooler_temp / buffer level read from sensors.
        pasteurized = pasteur_temp >= config.PASTEUR_SAFE_MIN
        cooled = cooler_temp <= config.COOLER_MAX_BOTTLING
        ready = pasteurized and cooled
        buffer_level = float(sensors.get("conveyor_queue", 0))
        buffer_max = float(sensors.get("conveyor_max", config.CONVEYOR_MAX_BOTTLES))

        # ── S4: Fill Valve ──────────────────────────────────────────
        # Open whenever the line is ready to bottle and the buffer isn't full.
        # The plant's inline filler handles the fill-cycle timing internally;
        # the PLC just enables/disables filling (interlock + back-pressure).
        if man_fill:
            fill_valve_cmd = int(man["fill_valve_cmd"])
        else:
            buffer_ok = buffer_level < buffer_max * 0.95
            fill_valve_cmd = 1 if (ready and buffer_ok) else 0

        # ── S5: Conveyor/Capper — accumulation-buffer P-controller ──
        # The conveyor runs the capper and clears the accumulation buffer.
        # AUTO speed tracks the buffer toward CONVEYOR_TARGET_BUFFER: when
        # bottles pile up (filler faster than packing) the belt speeds up;
        # when the buffer is low it idles slow. This makes the belt count
        # visibly respond to any pump/fill vs conveyor speed mismatch.
        if man_conv:
            conveyor_cmd = float(man["conveyor_cmd"])
        else:
            if buffer_level <= 0.5:
                conveyor_cmd = 0.0          # nothing to move
            else:
                err = buffer_level - config.CONVEYOR_TARGET_BUFFER
                # base 40% keeps product moving; +/- proportional on buffer error
                conveyor_cmd = _clamp(40.0 + 6.0 * err, 20.0, 100.0)

        # Capper runs whenever the conveyor moves bottles
        capper_cmd = 1 if conveyor_cmd > 0 else 0

        # ── Startup sequencer gating ─────────────────────────────────
        # During STARTING, gate actuators by startup phase: HEAT → PRIME → RUNNING.
        # Each actuator is only gated if NOT manually overridden — the operator
        # can take manual control of the inlet without affecting the pump sequence.
        if self.state == config.PLC_STARTING:
            self._startup_ticks += 1

            if self._startup_phase == 0:
                # HEAT: warm pasteurizer + cooler, fill tank. No flow.
                if not man_heater:
                    heater_power_cmd = 100.0
                    self.heater_power_cmd = 100.0
                if not man_pump:
                    pump_cmd = 0.0
                    self.pump_cmd = 0.0
                if not man_fill:
                    fill_valve_cmd = 0
                if not man_conv:
                    conveyor_cmd = 0.0
                    capper_cmd = 0
                if (pasteur_temp >= config.PASTEUR_SAFE_MIN and
                    cooler_temp <= config.COOLER_MAX_BOTTLING and
                    tank_level >= config.TANK_LEVEL_LOW):
                    self._startup_phase = 1
                    self._startup_ticks = 0

            elif self._startup_phase == 1:
                # PRIME: start pump at low speed, wait for flow.
                if not man_pump:
                    self.pump_cmd = _clamp(self.pump_cmd + 3.0, 0.0, 40.0)
                    pump_cmd = self.pump_cmd
                if not man_fill:
                    fill_valve_cmd = 0
                if not man_conv:
                    conveyor_cmd = 0.0
                    capper_cmd = 0
                # Require stable flow for a few ticks before filler starts —
                # creates a visible pause between "pump running" and "bottling".
                if flow_rate > 5.0:
                    self._startup_ticks += 1
                    if self._startup_ticks >= 3:
                        self.state = config.PLC_RUNNING
                        self._startup_phase = 2
                else:
                    self._startup_ticks = 0

        self.last_pump_cmd = pump_cmd
        return {
            "pump_cmd": round(pump_cmd, 1),
            "inlet_valve_cmd": round(inlet_valve_cmd, 1),
            "heater_power_cmd": heater_power_cmd,
            "cooling_valve_cmd": cooling_valve_cmd,
            "conveyor_cmd": round(conveyor_cmd, 1),
            "fill_valve_cmd": fill_valve_cmd,
            "capper_cmd": capper_cmd,
            "startup_phase": self._startup_phase,
        }

    # ------------------------------------------------------------------
    def _safe_outputs(self) -> Dict:
        """All actuators off — used in IDLE / STOPPING / FAULT."""
        self.heater_power_cmd = 0.0
        self.cooling_valve_cmd = 0.0
        self.pump_cmd = 0.0
        self._fill_timer = 0
        self.last_pump_cmd = 0.0
        self._startup_phase = 0
        self._startup_ticks = 0
        return {
            "pump_cmd": 0.0,
            "inlet_valve_cmd": 0.0,
            "heater_power_cmd": 0.0,
            "cooling_valve_cmd": 0.0,
            "conveyor_cmd": 0.0,
            "fill_valve_cmd": 0,
            "capper_cmd": 0,
            "startup_phase": self._startup_phase,
        }

    # ------------------------------------------------------------------
    def _detect_faults(self, sensors: Dict, data_stale: int) -> None:
        """Translate abnormal sensor patterns into a latched alarm code.

        Fault detection runs ALWAYS regardless of manual/auto mode.
        Safety interlocks cannot be bypassed by the operator.
        """
        pasteur_temp = float(sensors.get("pasteur_temp", 0.0))
        flow_rate = float(sensors.get("flow_rate", 0.0))
        pump_feedback = int(sensors.get("pump_feedback", 0))
        tank_level = float(sensors.get("tank_level", 0.0))
        running = self.state in (config.PLC_RUNNING, config.PLC_STARTING)

        # Infrastructure fault: stale data takes highest priority.
        if data_stale:
            self.alarm_code = config.ALARM_DATA_STALE
            return

        # Track warm-up so the normal ramp (temp < safe-min) is not flagged.
        if not running:
            self._warmed_up = False
        elif pasteur_temp >= config.PASTEUR_SAFE_MIN:
            self._warmed_up = True

        # Sensor fault: two detection modes cover both scenarios.
        # (a) Heater moving >5% but temp frozen <0.1°C — rapid: 3 ticks.
        # (b) Temp exactly frozen <0.001°C (injected fault at setpoint
        #     where heater stays stable) — also 3 ticks. Normal operation
        #     has ±0.04°C noise so exact-freeze never triggers falsely.
        heater_moved = abs(self.heater_power_cmd - self._prev_heater_cmd) > 5.0
        temp_frozen = abs(pasteur_temp - self._prev_temp) < 0.1
        temp_exact   = abs(pasteur_temp - self._prev_temp) < 0.001
        if running and ((heater_moved and temp_frozen) or temp_exact):
            self._temp_stuck_count += 1
        else:
            self._temp_stuck_count = 0

        # Equipment fault: pump commanded on but no feedback and no flow.
        # Uses actual pump command (could be manual or auto).
        pump_on = self.last_pump_cmd > 0
        if pump_on and pump_feedback == 0 and flow_rate <= 0.1:
            self._no_flow_count += 1
        else:
            self._no_flow_count = 0

        # Process fault: pasteurization temperature outside the safe band.
        # Now ALWAYS detected — even when heater is under manual control.
        # The operator can cause a TEMP_OUT_OF_RANGE alarm by setting
        # heater too high or too low, which is correct safety behavior.
        out_of_range = (pasteur_temp > config.PASTEUR_SAFE_MAX
                        or pasteur_temp < config.PASTEUR_SAFE_MIN)
        if running and self._warmed_up and out_of_range:
            self._temp_range_count += 1
        else:
            self._temp_range_count = 0

        # Tank level alarms: overflow (too full) or empty (too low).
        pump_active = (self.state == config.PLC_RUNNING or
                       (self.state == config.PLC_STARTING and self._startup_phase >= 1) or
                       self.pump_cmd > 0)  # manual pump override during HEAT

        # OVERFLOW is a hard safety hazard and must alarm whenever the line is
        # active (STARTING or RUNNING), regardless of startup phase OR manual
        # override. In AUTO the inlet valve closes above TANK_LEVEL_HIGH (80%),
        # so the tank can never reach 90% on its own — a >=90% reading means the
        # operator has forced the inlet open (manual override) and the tank is
        # genuinely about to overflow. Previously this was gated on `pump_active`
        # which is False during HEAT and stays False when a manual override
        # freezes the startup sequencer, so a manually-overfilled tank never
        # alarmed. Tie it to `running` instead so manual overfill is always caught.
        if running and tank_level >= config.TANK_CRITICAL_HIGH:
            self._tank_overflow_count += 1
        else:
            self._tank_overflow_count = 0

        # EMPTY is only dangerous when the pump is actually drawing product, so
        # it stays gated on pump-active phases — during HEAT the tank legitimately
        # fills from 0% with the pump off and must not raise a false empty alarm.
        if pump_active and tank_level <= config.TANK_CRITICAL_LOW:
            self._tank_empty_count += 1
        else:
            self._tank_empty_count = 0

        # Infrastructure / process: conveyor buffer dangerously high.
        buffer_level = float(sensors.get("conveyor_queue", 0))
        buffer_max = float(sensors.get("conveyor_max", config.CONVEYOR_MAX_BOTTLES))
        if running and buffer_level >= buffer_max * 0.90:
            self._buffer_high_count += 1
        else:
            self._buffer_high_count = 0

        # Process fault: cooler outlet temperature critically high.
        cooler_temp = float(sensors.get("cooler_temp", 25.0))
        if running and cooler_temp >= config.COOLER_ALARM_HIGH:
            self._cooler_high_count += 1
        else:
            self._cooler_high_count = 0

        # Auto-clear TEMP_OUT_OF_RANGE / COOLER_HIGH when temp returns to safe band.
        if self.alarm_code == config.ALARM_TEMP_OUT_OF_RANGE and not out_of_range:
            self.alarm_code = config.ALARM_NONE
            self._temp_range_count = 0
            if self.state == config.PLC_FAULT:
                self.state = config.PLC_IDLE
        if self.alarm_code == config.ALARM_COOLER_HIGH and cooler_temp < config.COOLER_ALARM_HIGH:
            self.alarm_code = config.ALARM_NONE
            self._cooler_high_count = 0
            if self.state == config.PLC_FAULT:
                self.state = config.PLC_IDLE

        # Latch the first alarm that exceeds its debounce threshold.
        # Priority order: safety hazards (tank) > process (temp) > equipment > sensor.
        if self.alarm_code == config.ALARM_NONE:
            if self._tank_overflow_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_TANK_OVERFLOW
            elif self._tank_empty_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_TANK_EMPTY
            elif self._buffer_high_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_BUFFER_HIGH
            elif self._cooler_high_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_COOLER_HIGH
            elif self._temp_range_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_TEMP_OUT_OF_RANGE
            elif self._no_flow_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_PUMP_NO_FLOW
            elif self._temp_stuck_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_SENSOR_TEMP_STUCK

        self._prev_temp = pasteur_temp
        self._prev_heater_cmd = self.heater_power_cmd

    # ------------------------------------------------------------------
    def acknowledge(self) -> None:
        """Operator acknowledges / clears the current alarm."""
        self.alarm_code = config.ALARM_NONE
        self._temp_stuck_count = 0
        self._no_flow_count = 0
        self._temp_range_count = 0
        self._tank_overflow_count = 0
        self._tank_empty_count = 0
        self._buffer_high_count = 0
        self._cooler_high_count = 0
        if self.state == config.PLC_FAULT:
            self.state = config.PLC_IDLE


from config import clamp as _clamp  # shared utility
