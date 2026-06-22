"""Telegram alarm notifier.

When the plant raises an alarm, the local backend pushes a message to a Telegram
chat/group via a bot — mirroring the lecturer's reference `plant_ops_2026` bot
(e.g. "[ALARM] TANK LEVEL LOW ..."). This is the L4 "enterprise notification"
edge of the ISA-95 model: an event leaving the plant to reach operators on their
phones.

Design notes:
* Pure standard library (urllib) — no extra dependency.
* Sends in a background thread so a slow/failed HTTP call NEVER blocks the
  1 Hz control loop.
* Disabled (no-op) unless both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set,
  so the rest of the system works with zero configuration.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Dict

import config


class TelegramNotifier:
    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self.token = (token or config.TELEGRAM_BOT_TOKEN or "").strip()
        self.chat_id = (chat_id or config.TELEGRAM_CHAT_ID or "").strip()
        self.last_error = ""

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------
    def send(self, text: str) -> bool:
        """Queue a Telegram message (non-blocking). Returns False if disabled."""
        if not self.enabled:
            return False
        threading.Thread(target=self._post, args=(text,), daemon=True).start()
        return True

    def _post(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text,
        }).encode("utf-8")
        try:
            with urllib.request.urlopen(url, data=data, timeout=10) as resp:
                body = resp.read().decode("utf-8", "ignore")
                ok = json.loads(body).get("ok", False)
                if not ok:
                    self.last_error = body[:200]
                    print(f"[Telegram] send rejected: {body[:200]}")
        except Exception as exc:  # noqa: BLE001 - never break the control loop
            self.last_error = f"{type(exc).__name__}: {exc}"
            print(f"[Telegram] send failed: {self.last_error}")

    # ------------------------------------------------------------------
    def notify_alarm(self, alarm_code: int, snapshot: Dict) -> bool:
        """Send a formatted alarm message for a newly-raised alarm."""
        label = config.ALARM_LABELS.get(alarm_code, str(alarm_code))
        desc = config.ALARM_DESCRIPTIONS.get(alarm_code, "")
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        plc = snapshot.get("plc_state", "?")
        temp = snapshot.get("pasteur_temp", 0.0)
        level = snapshot.get("tank_level", 0.0)
        text = (
            f"[ALARM] {label}\n"
            f"code: {alarm_code} | PLC: {plc}\n"
            f"{desc}\n"
            f"pasteur={float(temp):.1f}C  tank={float(level):.1f}%\n"
            f"at: {ts}"
        )
        return self.send(text)

    def notify_clear(self) -> bool:
        """Optional: announce that all alarms have cleared."""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        return self.send(f"[OK] All alarms cleared — line back to normal.\nat: {ts}")
