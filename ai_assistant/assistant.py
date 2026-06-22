"""M5 - AI Assistant.

Explains the current alarm and recommends safe operator actions. It reads the
latest tags, the active alarm code and recent history, then returns:
    recommendation_text, diagnosis_label, confidence_level

Two engines are supported:
* Claude (Anthropic API) - used when the ANTHROPIC_API_KEY environment variable
  is set. The prompt constrains the model to operator-facing advice only.
* Rule-based fallback - deterministic advice keyed on the alarm code. Used when
  no API key is configured, so the dashboard always shows a recommendation even
  offline.

Safety rule (from the README): the assistant recommends operator actions but
never directly controls actuators.
"""

from __future__ import annotations

import os
from typing import Dict, List

import config


SYSTEM_PROMPT = (
    "You are an operator-support assistant for a beverage pasteurization and "
    "bottling line. You receive live process tags, an alarm code and recent "
    "history. Diagnose the most likely cause and recommend concrete, safe "
    "operator actions. You must NOT command equipment directly - only advise the "
    "human operator. Keep the answer under 120 words, plain language, and end "
    "with a one-line 'Diagnosis:' label."
)

CONSULT_SYSTEM_PROMPT = (
    "You are an expert operator-support assistant for a beverage pasteurization "
    "and bottling line digital twin. The line has 5 stages: S1 Raw Tank (level "
    "control, target 55%, range 30-80%), S2 Pasteurizer (72°C target, 68-78°C "
    "safe band), S3 Cooler (25°C target, glycol HX, alarm above 32°C), "
    "S4 Inline Filler (4-nozzle monoblock, 500mL bottles), S5 Capper/Conveyor "
    "(accumulation buffer 0-60 bottles, P-controlled belt speed). "
    "You receive live sensor tags and recent history. Answer the operator's "
    "question concisely (under 150 words). Be specific about current values and "
    "recommended actions. Never command actuators — only advise the human operator."
)

# Deterministic fallback advice keyed on alarm code.
_RULE_ADVICE: Dict[int, Dict[str, str]] = {
    config.ALARM_NONE: {
        "label": "Normal operation",
        "text": "All readings are within range. No action required. Continue "
                "monitoring tank level and pasteurization temperature.",
    },
    config.ALARM_SENSOR_TEMP_STUCK: {
        "label": "Temperature sensor fault",
        "text": "The pasteurization temperature reading is frozen while the "
                "heater command is changing. Treat the reading as unreliable. "
                "Do NOT trust the temperature interlock: stop the line, switch "
                "to the backup temperature sensor or a manual probe, and replace "
                "the faulty sensor before restarting.",
    },
    config.ALARM_PUMP_NO_FLOW: {
        "label": "Feed pump failure",
        "text": "The feed pump is ON but there is no flow or feedback. Stop the "
                "line to avoid dry-running the pasteurizer. Check the pump motor "
                "breaker, the pump coupling and the inlet for blockage, then "
                "restart and confirm flow returns.",
    },
    config.ALARM_TEMP_OUT_OF_RANGE: {
        "label": "Pasteurization temperature excursion",
        "text": "Pasteurization temperature is outside the safe band. Product "
                "safety is at risk: divert or quarantine product processed during "
                "the excursion, reduce or cut heater power, and inspect the "
                "heating element/steam valve before resuming production.",
    },
    config.ALARM_DATA_STALE: {
        "label": "Data link stale",
        "text": "Live data has stopped updating. Operate with caution and do not "
                "rely on on-screen values. Check the MQTT broker, the network "
                "link and the publisher process, then confirm tags resume "
                "updating before trusting the dashboard.",
    },
    config.ALARM_TANK_OVERFLOW: {
        "label": "Raw tank overflow risk",
        "text": f"Tank level has exceeded {config.TANK_CRITICAL_HIGH:.0f}%. "
                "Immediate action: stop the feed pump, fully close the inlet "
                "valve, and check the level sensor. If level continues to rise, "
                "activate the emergency overflow diversion.",
    },
    config.ALARM_TANK_EMPTY: {
        "label": "Raw tank empty",
        "text": f"Tank level has dropped below {config.TANK_CRITICAL_LOW:.0f}%. "
                "The feed pump is at risk of dry-running. Stop the pump "
                "immediately, open the inlet valve fully, and verify raw "
                "beverage supply availability before restarting.",
    },
    config.ALARM_BUFFER_HIGH: {
        "label": "Conveyor buffer critically high",
        "text": f"Conveyor buffer is at {config.CONVEYOR_MAX_BOTTLES * 0.9:.0f}+ bottles "
                "(near capacity). The filler is back-pressuring. Increase "
                "conveyor speed to clear the buffer. If the belt is already at "
                "max, reduce feed pump speed to slow fill rate. Check the "
                "capper for jams.",
    },
    config.ALARM_COOLER_HIGH: {
        "label": "Cooler outlet temperature high",
        "text": f"Cooler outlet temperature has exceeded {config.COOLER_ALARM_HIGH:.0f}°C. "
                "Product is too hot for safe bottling. Increase cooling valve "
                "opening to at least 20-30%. If the valve is already high, "
                "reduce feed pump speed to lower the thermal load. Check glycol "
                "supply temperature and heat exchanger for fouling or blockage.",
    },
}


def _detect_provider(key: str) -> str:
    """Pick the LLM provider from the API-key prefix.

    * ``sk-ant-...``  -> Anthropic Claude
    * ``sk-proj-...`` / any other ``sk-...`` -> OpenAI
    """
    key = (key or "").strip()
    if key.startswith("sk-ant"):
        return "anthropic"
    if key.startswith("sk-"):
        return "openai"
    return ""


class AIAssistant:
    def __init__(self) -> None:
        # Accept either provider's key from env / Streamlit secrets.
        self.api_key = (os.environ.get("ANTHROPIC_API_KEY", "").strip()
                        or os.environ.get("OPENAI_API_KEY", "").strip())
        self._client = None
        self.provider = ""          # "anthropic" | "openai" | ""
        # init_error: why the LLM client failed to build (shown in the UI).
        # last_error: why the most recent live API call fell back to rules.
        self.init_error = ""
        self.last_error = ""
        if self.api_key:
            self._init_client(self.api_key)

    def _init_client(self, key: str) -> None:
        """Build the OpenAI or Anthropic client and record any failure reason.

        Failures are stored in ``self.init_error`` (and printed) so the dashboard
        can tell the operator EXACTLY why the LLM is not active instead of
        silently falling back to the rule-based engine.
        """
        self.init_error = ""
        self.last_error = ""
        self._client = None
        self.provider = _detect_provider(key)

        if self.provider == "":
            self.init_error = "API key not recognised (it should start with 'sk-ant-' for Claude or 'sk-' for OpenAI)."
            return

        if self.provider == "openai":
            try:
                from openai import OpenAI  # noqa: WPS433
            except Exception as exc:  # noqa: BLE001
                self.init_error = (f"openai package not importable ({type(exc).__name__}: {exc}). "
                                   "Add 'openai' to requirements.txt and reboot the app.")
                print(f"[AIAssistant] {self.init_error}")
                return
            try:
                self._client = OpenAI(api_key=key)
            except Exception as exc:  # noqa: BLE001
                self.init_error = f"Could not start OpenAI client ({type(exc).__name__}: {exc})."
                print(f"[AIAssistant] {self.init_error}")
            return

        # provider == "anthropic"
        try:
            import anthropic  # noqa: WPS433
        except Exception as exc:  # noqa: BLE001
            self.init_error = (f"anthropic package not importable ({type(exc).__name__}: {exc}). "
                               "Add 'anthropic' to requirements.txt and reboot the app.")
            print(f"[AIAssistant] {self.init_error}")
            return
        try:
            self._client = anthropic.Anthropic(api_key=key)
        except TypeError as exc:  # noqa: BLE001
            # Known httpx/anthropic version clash (a 'proxies' kwarg newer httpx
            # rejects). Retry with an explicit clean http client.
            try:
                import httpx  # noqa: WPS433
                self._client = anthropic.Anthropic(api_key=key, http_client=httpx.Client())
            except Exception as exc2:  # noqa: BLE001
                self.init_error = (f"anthropic/httpx version clash ({type(exc).__name__}: {exc}). "
                                   "Pin anthropic>=0.40 and reboot.")
                print(f"[AIAssistant] {self.init_error} / retry: {exc2}")
        except Exception as exc:  # noqa: BLE001
            self.init_error = f"Could not start Claude client ({type(exc).__name__}: {exc})."
            print(f"[AIAssistant] {self.init_error}")

    def update_api_key(self, key: str) -> None:
        """Hot-swap the API key from the dashboard UI. Re-initializes the client."""
        key = key.strip()
        if key == self.api_key:
            return
        self.api_key = key
        if key:
            self._init_client(key)
        else:
            self._client = None
            self.provider = ""
            self.init_error = ""

    @property
    def using_llm(self) -> bool:
        return self._client is not None

    # Backwards-compatible alias used by older page code.
    @property
    def using_claude(self) -> bool:
        return self._client is not None

    @property
    def provider_label(self) -> str:
        return {"openai": f"OpenAI ({config.OPENAI_MODEL})",
                "anthropic": f"Claude ({config.ANTHROPIC_MODEL})"}.get(self.provider, "Rule-based")

    # ------------------------------------------------------------------
    def _call_llm(self, system_prompt: str, user_msg: str) -> str:
        """Single entry point for a chat completion, provider-agnostic."""
        if self.provider == "openai":
            response = self._client.chat.completions.create(
                model=config.OPENAI_MODEL,
                max_tokens=config.LLM_MAX_TOKENS,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_msg}],
            )
            return (response.choices[0].message.content or "").strip()
        # anthropic
        response = self._client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.LLM_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        return "".join(block.text for block in response.content
                       if getattr(block, "type", "") == "text").strip()

    # ------------------------------------------------------------------
    def consult(self, question: str, latest_tags: Dict,
                recent_history: List[Dict]) -> str:
        """Free-form operator question. Returns plain-text answer string."""
        if self._client is not None:
            try:
                answer = self._consult_with_claude(question, latest_tags, recent_history)
                self.last_error = ""
                return answer
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(f"[AIAssistant] Claude consult failed ({exc}); falling back.")
        return self._consult_with_rules(question, latest_tags)

    def _consult_with_rules(self, question: str, latest_tags: Dict) -> str:
        """Rule-based free-form answers using sensor data + alarm knowledge."""
        alarm_code = int(latest_tags.get("alarm_code", 0))
        temp = float(latest_tags.get("pasteur_temp", 0))
        level = float(latest_tags.get("tank_level", 0))
        flow = float(latest_tags.get("flow_rate", 0))
        cooler = float(latest_tags.get("cooler_temp", 0))
        plc = latest_tags.get("plc_state", "IDLE")
        buffer = int(latest_tags.get("conveyor_queue", 0))
        completed = int(latest_tags.get("bottles_completed", 0))

        # Build a context-aware response from the available data
        lines = ["[Rule-based analysis — no API key configured]\n"]
        lines.append(f"**Current State:** PLC={plc}, Alarm={config.ALARM_LABELS.get(alarm_code, 'None')}")
        lines.append(f"**Sensors:** Pasteurizer={temp:.1f}°C (band 68-78), Cooler={cooler:.1f}°C (limit 28), Tank={level:.0f}% (target 55), Flow={flow:.1f} L/min, Buffer={buffer}/60")

        # Quick assessment
        issues = []
        if alarm_code:
            advice = _RULE_ADVICE.get(alarm_code, _RULE_ADVICE[config.ALARM_NONE])
            lines.append(f"\n**Active Alarm — {advice['label']}:** {advice['text']}")
        else:
            if not (config.PASTEUR_SAFE_MIN <= temp <= config.PASTEUR_SAFE_MAX):
                issues.append(f"Pasteurizer temp {temp:.1f}°C outside 68-78°C band")
            if cooler > config.COOLER_MAX_BOTTLING:
                issues.append(f"Cooler temp {cooler:.1f}°C above {config.COOLER_MAX_BOTTLING}°C bottling limit")
            if level > config.TANK_LEVEL_HIGH:
                issues.append(f"Tank level {level:.0f}% above {config.TANK_LEVEL_HIGH}%")
            if level < config.TANK_LEVEL_LOW:
                issues.append(f"Tank level {level:.0f}% below {config.TANK_LEVEL_LOW}%")
            if buffer > 50:
                issues.append(f"Buffer {buffer}/60 — approaching capacity")
            if issues:
                lines.append("\n**Warnings:** " + "; ".join(issues))
            else:
                lines.append(f"\n**Assessment:** All readings normal. {completed} bottles completed. Line operating safely.")

        lines.append(f"\n*For AI-powered interactive answers, add an OpenAI (sk-proj-…) or Anthropic (sk-ant-…) API key in the sidebar.*")
        return "\n".join(lines)

    def _consult_with_claude(self, question: str, latest_tags: Dict,
                              recent_history: List[Dict]) -> str:
        alarm_code = int(latest_tags.get("alarm_code", 0))
        alarm_label = config.ALARM_LABELS.get(alarm_code, "None")
        trend = _summarize_history(recent_history)
        user_msg = (
            f"Operator question: {question}\n\n"
            f"Active alarm: {alarm_label} (code {alarm_code})\n"
            f"Latest tags:\n{_format_tags(latest_tags)}\n\n"
            f"Recent trend:\n{trend}"
        )
        return self._call_llm(CONSULT_SYSTEM_PROMPT, user_msg)

    # ------------------------------------------------------------------
    def diagnose(self, latest_tags: Dict, alarm_code: int,
                 recent_history: List[Dict]) -> Dict:
        """Return a recommendation dict for the dashboard (M4)."""
        if self._client is not None:
            try:
                result = self._diagnose_with_claude(latest_tags, alarm_code,
                                                    recent_history)
                self.last_error = ""
                return result
            except Exception as exc:  # noqa: BLE001 - never break the dashboard
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(f"[AIAssistant] Claude call failed ({exc}); falling back.")
        return self._diagnose_with_rules(alarm_code)

    # ------------------------------------------------------------------
    def _diagnose_with_rules(self, alarm_code: int) -> Dict:
        advice = _RULE_ADVICE.get(alarm_code, _RULE_ADVICE[config.ALARM_NONE])
        confidence = "high" if alarm_code in _RULE_ADVICE else "medium"
        return {
            "recommendation_text": advice["text"],
            "diagnosis_label": advice["label"],
            "confidence_level": confidence,
            "engine": "rule-based",
        }

    def _diagnose_with_claude(self, latest_tags: Dict, alarm_code: int,
                              recent_history: List[Dict]) -> Dict:
        alarm_label = config.ALARM_LABELS.get(alarm_code, str(alarm_code))
        alarm_desc = config.ALARM_DESCRIPTIONS.get(alarm_code, "")

        # Compact the history to keep the prompt small.
        trend = _summarize_history(recent_history)
        user_msg = (
            f"Active alarm: {alarm_label} (code {alarm_code}).\n"
            f"Alarm meaning: {alarm_desc}\n\n"
            f"Latest tags:\n{_format_tags(latest_tags)}\n\n"
            f"Recent trend (last samples):\n{trend}\n\n"
            "Give the operator a short diagnosis and the safe actions to take."
        )

        text = self._call_llm(SYSTEM_PROMPT, user_msg)

        label = config.ALARM_LABELS.get(alarm_code, "Diagnosis")
        if "Diagnosis:" in text:
            label = text.split("Diagnosis:")[-1].strip()[:60]
        return {
            "recommendation_text": text,
            "diagnosis_label": label,
            "confidence_level": "model",
            "engine": self.provider_label,
        }


def _format_tags(tags: Dict) -> str:
    keys = ["plc_state", "stage_state", "tank_level", "pasteur_temp",
            "cooler_temp", "flow_rate", "pump_feedback", "bottle_count",
            "heater_power_cmd"]
    return "\n".join(f"  {k} = {tags.get(k)}" for k in keys if k in tags)


def _summarize_history(history: List[Dict], n: int = 8) -> str:
    if not history:
        return "  (no history yet)"
    tail = history[-n:]
    lines = []
    for row in tail:
        lines.append(
            f"  t={row.get('tick', '?')} temp={row.get('pasteur_temp')} "
            f"flow={row.get('flow_rate')} level={row.get('tank_level')}"
        )
    return "\n".join(lines)
