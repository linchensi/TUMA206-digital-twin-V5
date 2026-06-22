"""M1 - Plant Simulator.

Simulates the physical beverage pasteurization & bottling line. It receives
actuator commands (from the PLC, M2) plus a fault-injection code (from the
dashboard, M4) and produces sensor + feedback values every update period.

This module contains NO control logic - it only models physics and faults.
The control decisions live in M2 (plc/controller.py).

Port specification (see README section 4):
    inputs : pump_cmd, inlet_valve_cmd, heater_power_cmd, cooling_valve_cmd,
             conveyor_cmd, fill_valve_cmd, capper_cmd, fault_inject_code,
             reset_fault
    outputs: tank_level, pasteur_temp, cooler_temp, flow_rate, bottle_present,
             bottle_count, pump_feedback, valve_feedback, stage_state,
             fault_status
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict

import config

FILL_NOZZLES = config.FILL_NOZZLES  # parallel filling nozzles (one carrier batch)


@dataclass
class PlantSimulator:
    """Physical plant model. Call :meth:`step` once per update period."""

    # --- internal physical state (sensor values) ---
    tank_level: float = 0.0        # % — starts empty, fills on START
    pasteur_temp: float = config.AMBIENT_TEMP  # degC
    cooler_temp: float = config.AMBIENT_TEMP   # degC
    flow_rate: float = 0.0         # L/min
    bottle_present: int = 0        # 0/1 - carrier of bottles at the fill station
    bottle_count: int = 0          # bottles filled+capped so far (entered buffer)
    bottles_completed: int = 0     # finished bottles that left the line (packed)
    conveyor_queue: int = 0        # bottles currently on the conveyor/accumulation belt
    conveyor_max: int = config.CONVEYOR_MAX_BOTTLES  # belt capacity
    pump_feedback: int = 0         # 0/1 - real pump running confirmation
    valve_feedback: int = 0        # 0/1 - inlet valve open confirmation

    # --- fault handling ---
    fault_status: int = config.FAULT_NONE
    _frozen_temp: float = field(default=0.0, repr=False)

    # --- inline filler: all nozzles fill in lockstep on one carrier ---
    # Phase machine: "INDEX" (carrier moving in/out, no bottle) -> "FILL" (all
    # nozzles dispensing) -> discharge full carrier to buffer -> back to INDEX.
    _fill_phase: str = field(default="INDEX", repr=False)
    _fill_progress: float = field(default=0.0, repr=False)   # 0..1 fill fraction
    _index_timer: int = field(default=0, repr=False)         # ticks in INDEX phase
    _nozzle_fill: list = field(default_factory=lambda: [0.0]*FILL_NOZZLES)  # per-nozzle 0..1

    # --- conveyor accumulation buffer (float for sub-bottle accounting) ---
    _buffer: float = field(default=0.0, repr=False)          # bottles on belt (float)
    _completed_acc: float = field(default=0.0, repr=False)   # fractional completed accumulator

    def reset(self) -> None:
        """Reset the plant to a clean starting state."""
        self.tank_level = 0.0
        self.pasteur_temp = config.AMBIENT_TEMP
        self.cooler_temp = config.AMBIENT_TEMP
        self.flow_rate = 0.0
        self.bottle_present = 0
        self.bottle_count = 0
        self.bottles_completed = 0
        self.conveyor_queue = 0
        self.pump_feedback = 0
        self.valve_feedback = 0
        self.fault_status = config.FAULT_NONE
        self._fill_phase = "INDEX"
        self._fill_progress = 0.0
        self._index_timer = 0
        self._nozzle_fill = [0.0]*FILL_NOZZLES
        self._buffer = 0.0
        self._completed_acc = 0.0

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------
    def step(self, cmd: Dict) -> Dict:
        """Advance the simulation one tick.

        Args:
            cmd: dictionary of actuator commands and fault controls.

        Returns:
            dictionary of sensor + feedback outputs (the M1 output pins).
        """
        # 0. Fault injection / reset --------------------------------------
        if cmd.get("reset_fault"):
            self.fault_status = config.FAULT_NONE
        else:
            code = int(cmd.get("fault_inject_code", config.FAULT_NONE))
            if code != self.fault_status:
                # Latch the new fault and remember the current temp for "stuck".
                self.fault_status = code
                self._frozen_temp = self.pasteur_temp

        pump_cmd = float(cmd.get("pump_cmd", 0))           # 0-100%
        inlet_valve_cmd = float(cmd.get("inlet_valve_cmd", 0))  # 0-100%
        heater_power_cmd = float(cmd.get("heater_power_cmd", 0.0))  # 0-100%
        cooling_valve_cmd = float(cmd.get("cooling_valve_cmd", 0))   # 0-100%
        conveyor_cmd = float(cmd.get("conveyor_cmd", 0))    # 0-100%
        fill_valve_cmd = int(cmd.get("fill_valve_cmd", 0))
        capper_cmd = int(cmd.get("capper_cmd", 0))

        pump_failed = self.fault_status == config.FAULT_PUMP_FAIL

        # 1. Feed pump & flow (proportional 0-100%) ----------------------
        if pump_cmd > 0 and not pump_failed and self.tank_level > 0.5:
            self.pump_feedback = 1
            # Flow = 40 L/min at 100%, proportional below
            self.flow_rate = 40.0 * (pump_cmd / 100.0) + random.uniform(-0.5, 0.5)
            self.flow_rate = max(0.0, self.flow_rate)
        else:
            self.pump_feedback = 0
            self.flow_rate = 0.0

        # 2. Raw / balance tank (S1) — inflow proportional to valve opening
        self.valve_feedback = 1 if inlet_valve_cmd > 0 else 0
        inflow = 6.0 * (inlet_valve_cmd / 100.0) if inlet_valve_cmd > 0 else 0.0
        outflow = 4.0 * (pump_cmd / 100.0) if self.pump_feedback else 0.0
        self.tank_level = _clamp(self.tank_level + inflow - outflow, 0.0, 100.0)

        # 3. Pasteurizer temperature (S2) --------------------------------
        self._update_pasteur_temp(heater_power_cmd)

        # 4. Cooler (S3) — HX with pipe transit + active glycol cooling.
        #   (a) Inlet heating: hot product from pasteurizer, pipe walls shed
        #       ~40-50% of ΔT. Faster flow = less pipe time = hotter inlet.
        #       Typical inlet 50-55°C (from 72°C pasteurizer).
        #   (b) Active cooling: glycol HX drives temp toward COOLER_FLOOR (15°C).
        # Valve authority (steady-state, flow≈28 L/min, pipe≈53°C):
        #   0%  → 53°C (no cooling, approaches inlet temp)
        #   10% → ~40°C (COOLER_HIGH alarm at 32°C)
        #   30% → ~30°C (near bottling limit)
        #   50% → ~25°C (normal AUTO operating point — PI setpoint)
        #   80% → ~22°C (cold)
        #   100%→ ~21°C (maximum cooling toward 15°C floor)
        if self.flow_rate > 0.5:
            flow_factor = self.flow_rate / 40.0
            pipe_frac = 0.50 * (1.0 - 0.3 * flow_factor)
            pipe_temp = self.pasteur_temp - pipe_frac * (self.pasteur_temp - config.AMBIENT_TEMP)
            self.cooler_temp += 0.08 * flow_factor * (pipe_temp - self.cooler_temp)
        cooling_rate = 0.30 * max(cooling_valve_cmd / 100.0, 0.0)
        self.cooler_temp += cooling_rate * (config.COOLER_FLOOR - self.cooler_temp)
        self.cooler_temp += random.uniform(-0.10, 0.10)

        # 5. Filler & 6. Capper / Conveyor (S4 / S5) ---------------------
        self._update_bottling(conveyor_cmd, fill_valve_cmd, capper_cmd)

        return self.outputs()

    # ------------------------------------------------------------------
    def _update_pasteur_temp(self, heater_power_cmd: float) -> None:
        """First-order thermal model with flow-through cooling and faults."""
        if self.fault_status == config.FAULT_TEMP_STUCK:
            self.pasteur_temp = self._frozen_temp
            return

        if self.fault_status == config.FAULT_TEMP_EXCURSION:
            target = config.PASTEUR_SAFE_MAX + 20.0  # 98 degC — must overcome flow-through cooling
        else:
            # Heater power 0-100% → achievable target 25-90°C (ΔT = 65°C span).
            target = config.AMBIENT_TEMP + (heater_power_cmd / 100.0) * 65.0

        # First-order heating toward target (industrial thermal inertia, τ≈0.08)
        self.pasteur_temp += 0.08 * (target - self.pasteur_temp)

        # Flow-through cooling: cold beverage (~25°C) enters the pasteurizer
        # continuously, absorbing heat from the heated product. More flow = more
        # cold mass entering = more cooling load on the heater. This is the
        # dominant thermal disturbance in real pasteurizers.
        if self.flow_rate > 0.5:
            flow_factor = self.flow_rate / 40.0  # normalised 0..1
            self.pasteur_temp -= 0.012 * flow_factor * (self.pasteur_temp - config.AMBIENT_TEMP)

        self.pasteur_temp += random.uniform(-0.04, 0.04)

    def _update_bottling(self, conveyor_cmd: float, fill_valve_cmd: int,
                         capper_cmd: int) -> None:
        """Inline filler + conveyor accumulation buffer.

        FILLER (S4): an inline/rotary monoblock with FILL_NOZZLES nozzles that
        fill in lockstep. One carrier of N empty bottles indexes in, all nozzles
        dispense together at a rate set by the available product flow, then the
        full carrier indexes out to the capper as one batch. Phase machine:

            INDEX  -> (FILL_GAP_TICKS dead-time, carrier transfers)
            FILL   -> fill_progress 0..1 driven by flow_rate
            (on full) discharge N bottles into the conveyor buffer, back to INDEX

        CONVEYOR/CAPPER (S5): an accumulation buffer. Filled bottles ENTER the
        buffer in batches of N; the capper+conveyor REMOVE bottles continuously
        at a rate proportional to conveyor speed. The buffer level is therefore
        the integral of (fill_in_rate - discharge_out_rate) and visibly grows or
        shrinks whenever the filler and conveyor speeds are mismatched.
        """
        # ---- S5 discharge: conveyor removes bottles from the buffer ----
        # Runs whenever the belt is commanded, independent of the filler, so a
        # fast belt drains the buffer and a slow belt lets it accumulate.
        if conveyor_cmd > 0 and capper_cmd:
            out_rate = config.CONVEYOR_BOTTLES_PER_TICK_AT_100 * (conveyor_cmd / 100.0)
            removed = min(self._buffer, out_rate)
            self._buffer -= removed
            self._completed_acc += removed
            # Promote whole finished bottles to the completed counter
            whole = int(self._completed_acc)
            if whole > 0:
                self.bottles_completed += whole
                self._completed_acc -= whole

        # ---- S4 inline filler phase machine ----
        ready_to_fill = fill_valve_cmd and self.flow_rate > 1.0

        if self._fill_phase == "INDEX":
            self.bottle_present = 0
            self._index_timer += 1
            # Dynamic gap: faster flow → shorter INDEX dead-time → faster cadence.
            # Flow 30+ → gap=1, 10-20 → gap=1, 5-10 → gap=2, <5 → gap=3.
            dyn_gap = max(1, min(3, int(8.0 / max(self.flow_rate, 2.0))))
            if self._index_timer >= dyn_gap:
                self._index_timer = 0
                self._fill_phase = "FILL"
                self._fill_progress = 0.0
                self._nozzle_fill = [0.0]*FILL_NOZZLES

        elif self._fill_phase == "FILL":
            self.bottle_present = 1
            if ready_to_fill:
                # Fill rate per nozzle: flow (L/min) shared across nozzles, each
                # bottle is FILL_VOLUME_ML. Convert to fraction-per-tick.
                # L/min -> mL/tick (1 tick = UPDATE_PERIOD_S seconds)
                ml_per_tick = (self.flow_rate * 1000.0 / 60.0) * config.UPDATE_PERIOD_S
                frac_per_tick = ml_per_tick / (config.FILL_VOLUME_ML * FILL_NOZZLES)
                self._fill_progress = min(1.0, self._fill_progress + frac_per_tick)
                for i in range(FILL_NOZZLES):
                    self._nozzle_fill[i] = self._fill_progress
                # Carrier full -> discharge whole batch to the buffer
                if self._fill_progress >= 1.0:
                    space = self.conveyor_max - self._buffer
                    batch = min(FILL_NOZZLES, int(space))
                    if batch >= FILL_NOZZLES:
                        # Only discharge if the capper can accept the whole carrier
                        self._buffer += FILL_NOZZLES
                        self.bottle_count += FILL_NOZZLES
                        self._fill_phase = "INDEX"
                        self._fill_progress = 0.0
                        self._nozzle_fill = [0.0]*FILL_NOZZLES
                    # else: buffer full -> hold filled carrier (back-pressure)
            # if not ready_to_fill, the carrier waits with partial fill

        self.conveyor_queue = int(round(self._buffer))

    # ------------------------------------------------------------------
    def stage_state(self) -> str:
        """A coarse description of where product currently is."""
        if self.flow_rate > 0 and self.pasteur_temp >= config.PASTEUR_SAFE_MIN:
            return "PROCESSING"
        if self.flow_rate > 0:
            return "HEATING"
        if self.tank_level > config.TANK_LEVEL_MIN_PUMP:
            return "READY"
        return "EMPTY"

    def outputs(self) -> Dict:
        """Return the current M1 output pins as a dictionary."""
        # Per-nozzle status for the dashboard: 0=empty, 1=filling, 2=full
        nozzle_status = []
        for i in range(FILL_NOZZLES):
            if self._fill_phase == "FILL" and self.bottle_present:
                nozzle_status.append(2 if self._nozzle_fill[i] >= 0.999 else 1)
            else:
                nozzle_status.append(0)
        return {
            "tank_level": round(self.tank_level, 2),
            "pasteur_temp": round(self.pasteur_temp, 2),
            "cooler_temp": round(self.cooler_temp, 2),
            "flow_rate": round(self.flow_rate, 2),
            "bottle_present": int(self.bottle_present),
            "fill_phase": self._fill_phase,
            "fill_progress": round(self._fill_progress, 3),
            "nozzle_status": nozzle_status,
            "bottle_count": int(self.bottle_count),
            "bottles_completed": int(self.bottles_completed),
            "conveyor_queue": int(self.conveyor_queue),
            "conveyor_max": int(self.conveyor_max),
            "pump_feedback": int(self.pump_feedback),
            "valve_feedback": int(self.valve_feedback),
            "stage_state": self.stage_state(),
            "fault_status": int(self.fault_status),
        }


from config import clamp as _clamp  # shared utility
