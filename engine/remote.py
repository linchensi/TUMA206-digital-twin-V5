"""Remote engine proxy — the "dashboard-only" client used in the cloud split.

In the teacher's ISA-95 / Purdue layout the CLOUD dashboard (L4/L5) must NOT run
the simulation or control logic. It only:

    * SUBSCRIBES to the live tag stream (``btl/tags``) published by the local
      backend (M1 plant + M2 PLC + M3 historian) over MQTT, and
    * PUBLISHES operator commands (``btl/cmd``) back down to the local backend.

``RemoteEngineProxy`` exposes the *same* public surface the dashboard pages use
on the real :class:`SimulationEngine` (``latest()``, ``historian.recent()``,
``start_line()``, ``inject_fault()``, ``set_manual_actuator()`` …) so the three
pages (SCHEMATIC / TRENDS / ALARMS) work unchanged — but every action becomes an
MQTT message instead of a direct control call. The dashboard therefore *never*
controls the machine directly; it only sends commands over the data link.

The proxy keeps its OWN local historian, filled from the incoming tag stream, so
trend charts and the alarm log still work on the cloud side without reaching back
into the plant.
"""

from __future__ import annotations

import os
import tempfile
import threading
from typing import Dict

import config
from historian import Historian
from messaging import create_bus


class RemoteEngineProxy:
    """Display-only stand-in for :class:`SimulationEngine` driven over MQTT."""

    def __init__(self, use_mqtt: bool = True) -> None:
        # The remote dashboard is meaningless without a real broker, so default
        # to MQTT. If the broker is unreachable, create_bus() falls back to an
        # in-process bus (the dashboard will simply show no data until a backend
        # publishes on the same process — useful for local testing).
        self.bus = create_bus(use_mqtt=use_mqtt, async_connect=True)

        # Separate DB file so a local backend on the same machine (which writes
        # the canonical historian.db) and this dashboard-side mirror never clash.
        mirror_db = os.path.join(tempfile.gettempdir(), "historian_dashboard.db")
        self.historian = Historian(db_path=mirror_db)

        self._latest: Dict = {}
        self._manual_overrides: Dict = {}
        self._lock = threading.RLock()

        self.bus.subscribe(config.MQTT_TOPIC_TAGS, self._on_tags)

    # ------------------------------------------------------------------
    def _on_tags(self, payload: Dict) -> None:
        """Store each incoming snapshot and mirror it into the local historian."""
        with self._lock:
            self._latest = dict(payload)
        try:
            self.historian.record(payload)
        except Exception as exc:  # noqa: BLE001 - never break the UI on a bad row
            print(f"[remote] historian record failed: {exc}")

    def _send(self, **payload) -> None:
        try:
            self.bus.publish(config.MQTT_TOPIC_CMD, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[remote] command publish failed: {exc}")

    # ------------------------------------------------------------------
    # Read API (mirrors SimulationEngine)
    # ------------------------------------------------------------------
    def latest(self) -> Dict:
        with self._lock:
            return dict(self._latest)

    @property
    def manual_overrides(self) -> Dict:
        with self._lock:
            return dict(self._manual_overrides)

    @property
    def is_running(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Command API (mirrors SimulationEngine — every call is an MQTT message)
    # ------------------------------------------------------------------
    def start_line(self) -> None:
        with self._lock:
            self._manual_overrides.clear()
        self._send(cmd="start")

    def stop_line(self) -> None:
        with self._lock:
            self._manual_overrides.clear()
        self._send(cmd="stop")

    def inject_fault(self, code: int) -> None:
        self._send(cmd="inject", code=int(code))

    def reset_fault(self) -> None:
        self._send(cmd="reset")

    def set_manual_actuator(self, name: str, value) -> None:
        with self._lock:
            self._manual_overrides[name] = value
        self._send(cmd="manual_set", name=name, value=value)

    def clear_manual_actuator(self, name: str) -> None:
        with self._lock:
            self._manual_overrides.pop(name, None)
        self._send(cmd="manual_clear", name=name)

    def clear_all_manuals(self) -> None:
        with self._lock:
            self._manual_overrides.clear()
        self._send(cmd="clear_all")

    def hard_reset(self) -> None:
        with self._lock:
            self._manual_overrides.clear()
        try:
            self.historian.clear()
        except Exception as exc:  # noqa: BLE001
            print(f"[remote] historian clear failed: {exc}")
        self._send(cmd="hard_reset")

    # ------------------------------------------------------------------
    def close(self) -> None:
        """Disconnect the MQTT link (used on shutdown / tests)."""
        try:
            self.bus.close()
        except Exception as exc:  # noqa: BLE001
            print(f"[remote] bus close failed: {exc}")
