"""SVG P&ID builder — industrial process flow diagram.

7 equipment nodes in a clean horizontal pipeline:
  [Inlet Pump] → [Raw Tank] → [Feed Pump] → [Pasteurizer] → [Cooler]
  → [Filler ×4] → [Conveyor/Capper]

Pumps are drawn as standalone circles with rotating impellers flanking the tank.
Tank fill stays strictly within tank bounds. Equipment glows with status colour.
"""

from __future__ import annotations
from typing import Dict
import config

# ── Palette ───────────────────────────────────────────────────────────
BG     = "#0d1117"
BDR    = "#30363d"
TXT    = "#c9d1d9"
TXT2   = "#b0b8c0"
ACC    = "#58a6ff"
GRN    = "#3fb950"
ORN    = "#d2991d"
RED    = "#f85149"
CYA    = "#39d2c0"
HOT_C  = "#f0883e"
COLD_C = "#58a6ff"
LIQUID = "#3a7bd5"
STEEL  = "#2d333b"
IDLE   = "#1c2128"  # darker fill for stopped/idle equipment


def _cls_color(cls: str) -> str:
    return {"active": GRN, "warn": ORN, "fault": RED}.get(cls, BDR)


def _glow(cls: str) -> str:
    if cls == "active":  return 'filter="url(#glow-grn)"'
    if cls == "warn":    return 'filter="url(#glow-orn)"'
    if cls == "fault":   return 'filter="url(#glow-red)"'
    return ""


def _pipe(x1: float, y: float, x2: float, flowing: bool) -> str:
    c = ACC if flowing else BDR
    w = 4.5 if flowing else 3.5
    dash = 'stroke-dasharray="8,5"' if flowing else ""
    anim = 'class="pipe-flow"' if flowing else ""
    return (f'<line x1="{x1:.0f}" y1="{y:.0f}" x2="{x2:.0f}" y2="{y:.0f}" '
            f'stroke="{c}" stroke-width="{w}" stroke-linecap="round" '
            f'{dash} {anim}/>')

# ── CSS animations (scoped inside SVG) ────────────────────────────────
_ANIM = """
@keyframes flow { to { stroke-dashoffset: -26; } }
@keyframes spin  { to { transform: rotate(360deg); } }
@keyframes heat  { 0%,100%{opacity:0.25} 50%{opacity:0.85} }
@keyframes fill  { 0%,100%{opacity:1} 50%{opacity:0.45} }
@keyframes belt  { to { transform: translateX(18px); } }
.pipe-flow { animation: flow 0.5s linear infinite; }
.heat-glow { animation: heat 1.3s ease-in-out infinite; }
.fill-drop { animation: fill 0.55s ease-in-out infinite; }
.belt-btl  { animation: belt 0.45s linear infinite; }
"""

_FILTERS = f"""
<defs>
  <filter id="glow-grn"><feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="{GRN}" flood-opacity="0.55"/></filter>
  <filter id="glow-orn"><feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="{ORN}" flood-opacity="0.55"/></filter>
  <filter id="glow-red"><feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="{RED}" flood-opacity="0.65"/></filter>
  <linearGradient id="liq" x1="0" y1="1" x2="0" y2="0">
    <stop offset="0%" stop-color="{LIQUID}" stop-opacity="0.95"/>
    <stop offset="100%" stop-color="{ACC}" stop-opacity="0.45"/>
  </linearGradient>
</defs>
"""


# ═══════════════════════════════════════════════════════════════════════
# Equipment builders
# ═══════════════════════════════════════════════════════════════════════

def _man_badge(x: float, y: float) -> str:
    return (f'<rect x="{x:.0f}" y="{y:.0f}" width="13" height="9" rx="2" fill="{ORN}" '
            f'stroke="{ORN}" stroke-width="1"/><text x="{x+6.5:.0f}" y="{y+7.5:.0f}" '
            f'text-anchor="middle" fill="#000" font-size="7" font-weight="900">M</text>')


def pump_node(cx: float, cy: float, r: float, label: str, value: str,
              sub: str, active: bool, man: bool, cls: str = "active") -> str:
    """Circular centrifugal pump with rotating impeller triangle."""
    stroke_c = _cls_color(cls)
    bg = STEEL if active else IDLE
    imp_color = ACC if active else TXT2
    imp_style = f'style="animation:spin 0.7s linear infinite;transform-origin:{cx:.0f}px {cy:.0f}px"' if active else ""
    glow = _glow(cls)
    man_b = _man_badge(cx - r, cy - r - 10) if man else ""
    return (
        f'<g>'
        f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{bg}" stroke="{stroke_c}" '
        f'  stroke-width="2.5" {glow}/>'
        f'<polygon points="{cx:.0f},{cy-r*0.55:.0f} {cx+r*0.5:.0f},{cy+r*0.35:.0f} '
        f'  {cx-r*0.5:.0f},{cy+r*0.35:.0f}" fill="{imp_color}" {imp_style}/>'
        f'{man_b}'
        f'<text x="{cx:.0f}" y="{cy-r-16:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="8" font-weight="700">{label}</text>'
        f'<text x="{cx:.0f}" y="{cy+r+16:.0f}" text-anchor="middle" fill="{TXT}" '
        f'  font-size="11" font-weight="700">{value}</text>'
        f'<text x="{cx:.0f}" y="{cy+r+26:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="7">{sub}</text>'
        f'</g>'
    )


def tank_node(x: float, y: float, w: float, h: float, level_pct: float,
              label: str, value: str, sub: str, cls: str, man: bool) -> str:
    """Vertical tank with bounded liquid fill from bottom."""
    stroke_c = _cls_color(cls)
    glow = _glow(cls)
    man_b = _man_badge(x + 3, y + 3) if man else ""

    # Fill rect — strictly inside the tank boundary
    margin_t = 14   # top margin for tank dome
    margin_b = 10   # bottom margin
    margin_x = 8    # horizontal inset
    fillable_h = h - margin_t - margin_b
    fill_h = max(3, (level_pct / 100.0) * fillable_h)
    fill_y = y + h - margin_b - fill_h

    return (
        f'<g>'
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="10" '
        f'  fill="{STEEL}" stroke="{stroke_c}" stroke-width="2.5" {glow}/>'
        f'<rect x="{x+margin_x:.0f}" y="{fill_y:.0f}" width="{w-2*margin_x:.0f}" '
        f'  height="{fill_h:.0f}" rx="4" fill="url(#liq)"/>'
        f'{man_b}'
        f'<text x="{x+w/2:.0f}" y="{y-7:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="8" font-weight="700">{label}</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h/2+4:.0f}" text-anchor="middle" fill="{TXT}" '
        f'  font-size="16" font-weight="700">{value}</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h+14:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="7">{sub}</text>'
        f'</g>'
    )


def pasteurizer_node(x: float, y: float, w: float, h: float, temp: float,
                     heater_pct: float, cls: str, man: bool) -> str:
    """Horizontal vessel with heating bars and temperature readout."""
    stroke_c = _cls_color(cls)
    glow = _glow(cls)
    man_b = _man_badge(x + 3, y + 3) if man else ""
    t_color = GRN if config.PASTEUR_SAFE_MIN <= temp <= config.PASTEUR_SAFE_MAX else (
        ORN if abs(temp - config.PASTEUR_SETPOINT) < 5 else RED)

    # Heating bars inside the vessel
    bars = ""
    n = 6
    gap = 6
    bar_w = (w - 40) / n - gap
    alpha = heater_pct / 100.0
    for i in range(n):
        bx = x + 20 + i * (bar_w + gap)
        by = y + h/2 - 10
        bars += (f'<rect x="{bx:.0f}" y="{by:.0f}" width="{bar_w:.0f}" height="20" '
                 f'rx="2" fill="rgba(240,136,62,{0.25+0.75*alpha})" '
                 f'class="{"heat-glow" if alpha>0.05 else ""}"/>')

    return (
        f'<g>'
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="7" '
        f'  fill="{STEEL}" stroke="{stroke_c}" stroke-width="2.5" {glow}/>'
        f'{bars}'
        f'{man_b}'
        f'<text x="{x+w/2:.0f}" y="{y-7:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="8" font-weight="700">PASTEURIZER</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h/2+6:.0f}" text-anchor="middle" fill="{t_color}" '
        f'  font-size="16" font-weight="700">{temp:.1f}°C</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h+14:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="7">Heater {heater_pct:.0f}% &middot; SP {config.PASTEUR_SETPOINT:.0f}°C</text>'
        f'</g>'
    )


def cooler_node(x: float, y: float, w: float, h: float, temp: float,
                valve_pct: float, cls: str, man: bool) -> str:
    """Cooler HX with cooling coils and temperature readout."""
    stroke_c = _cls_color(cls)
    glow = _glow(cls)
    man_b = _man_badge(x + 3, y + 3) if man else ""
    t_color = GRN if temp <= config.COOLER_MAX_BOTTLING else ORN

    # Cooling coil circles
    alpha = valve_pct / 100.0
    coils = ""
    n = 7
    spacing = (w - 24) / max(n - 1, 1)
    for i in range(n):
        cx_ = x + 12 + i * spacing
        cy_ = y + h/2 + (-5 if i % 2 == 0 else 5)
        coils += (f'<circle cx="{cx_:.0f}" cy="{cy_:.0f}" r="5" '
                  f'fill="{COLD_C}" opacity="{0.2+0.75*alpha}"/>')

    return (
        f'<g>'
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="7" '
        f'  fill="{STEEL}" stroke="{stroke_c}" stroke-width="2.5" {glow}/>'
        f'{coils}'
        f'<line x1="{x+10:.0f}" y1="{y+h/2:.0f}" x2="{x+w-10:.0f}" y2="{y+h/2:.0f}" '
        f'  stroke="{COLD_C}" stroke-width="1.5" opacity="{0.15+0.6*alpha}" '
        f'  stroke-dasharray="4,4"/>'
        f'{man_b}'
        f'<text x="{x+w/2:.0f}" y="{y-7:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="8" font-weight="700">COOLER</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h/2+6:.0f}" text-anchor="middle" fill="{t_color}" '
        f'  font-size="16" font-weight="700">{temp:.1f}°C</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h+14:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="7">Cooler {valve_pct:.0f}% &middot; Tgt {config.COOLER_SETPOINT:.0f}°C</text>'
        f'</g>'
    )


def filler_node(x: float, y: float, w: float, h: float, nozzle_status: list,
                fill_progress: float, fill_phase: str, flow: float,
                running: bool, cls: str) -> str:
    """4-nozzle inline filler — gray border when IDLE."""
    stroke_c = _cls_color(cls)
    glow = _glow(cls)
    active = cls == "active"
    idle_fill = IDLE
    n = 4
    nw = (w - 24) / n - 5
    nozzles = ""
    for i in range(n):
        nx = x + 12 + i * (nw + 5)
        ny = y + h * 0.28
        nh = h * 0.55
        ns = nozzle_status[i] if i < len(nozzle_status) else 0
        # N label — above the nozzle head dot (no overlap with bottom text)
        nozzles += (f'<text x="{nx+nw/2:.0f}" y="{ny-20:.0f}" text-anchor="middle" '
                    f'fill="{TXT2}" font-size="7" font-weight="600">N{i+1}</text>')
        # Nozzle head dot
        d_c = BDR
        if active:
            d_c = GRN if ns == 2 else (ACC if ns == 1 else BDR)
        nozzles += f'<circle cx="{nx+nw/2:.0f}" cy="{ny-12:.0f}" r="3.5" fill="{d_c}"/>'
        # Bottle outline
        bdr_c = BDR if not active else (ACC if ns > 0 else BDR)
        nozzles += (f'<rect x="{nx:.0f}" y="{ny:.0f}" width="{nw:.0f}" '
                    f'height="{nh:.0f}" rx="3" fill="{idle_fill if not active else "none"}" '
                    f'stroke="{bdr_c}" stroke-width="1.8"/>')
        # Fill level inside bottle
        fl = fill_progress if ns == 1 else (1.0 if ns == 2 else 0.0)
        if fl > 0 and active:
            fh = fl * nh
            fy = ny + nh - fh
            nozzles += (f'<rect x="{nx+2:.0f}" y="{fy:.0f}" width="{nw-4:.0f}" '
                        f'height="{fh:.0f}" rx="1" fill="{LIQUID}" opacity="0.85"/>')
        # Fill stream from top
        if ns == 1 and active:
            nozzles += (f'<line x1="{nx+nw/2:.0f}" y1="{ny-10:.0f}" '
                        f'x2="{nx+nw/2:.0f}" y2="{ny+nh*fl:.0f}" '
                        f'stroke="{ACC}" stroke-width="1.8" stroke-dasharray="4,4" '
                        f'class="fill-drop"/>')

    # Status text: "IDLE" when stopped, otherwise fill_phase + progress
    if running:
        status_text = f"{fill_phase} {int(fill_progress*100)}%"
        ph_color = ACC if fill_phase == "FILL" else TXT2
    else:
        status_text = "IDLE"
        ph_color = TXT2
    return (
        f'<g>'
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="7" '
        f'  fill="{STEEL}" stroke="{stroke_c}" stroke-width="2.5" {glow}/>'
        f'{nozzles}'
        f'<text x="{x+w/2:.0f}" y="{y-7:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="8" font-weight="700">FILLER &times;4</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h-6:.0f}" text-anchor="middle" fill="{ph_color}" '
        f'  font-size="9" font-weight="700">{status_text}</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h+14:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="7">Flow {flow:.1f} L/min &middot; 500 mL/bottle</text>'
        f'</g>'
    )


def conveyor_node(x: float, y: float, w: float, h: float, buffer_level: int,
                  buffer_max: int, completed: int, conv_pct: float,
                  cls: str) -> str:
    """Conveyor belt with bottle markers proportional to buffer fill."""
    stroke_c = _cls_color(cls)
    glow = _glow(cls)
    active = cls == "active"

    belt_y = y + h * 0.52
    belt_h = 12

    # Rollers
    rollers = ""
    for rx in [x + 16, x + w - 16]:
        rollers += (f'<circle cx="{rx:.0f}" cy="{belt_y+belt_h/2:.0f}" r="7" '
                    f'fill="{STEEL}" stroke="{BDR}" stroke-width="1.5"/>')

    # Bottle markers on belt — density shows buffer fill
    btls = ""
    frac = buffer_level / max(buffer_max, 1)
    btls_to_show = max(0, min(30, int(frac * 30)))
    if btls_to_show > 0 and (w - 40) > 0:
        sp = (w - 40) / btls_to_show
        for i in range(btls_to_show):
            bx = x + 20 + i * sp
            by = belt_y - 5
            btls += (f'<rect x="{bx-2:.0f}" y="{by-5:.0f}" width="4" height="10" '
                     f'rx="1.5" fill="{LIQUID}" opacity="0.75" '
                     f'class="{"belt-btl" if active else ""}"/>')

    buf_color = ORN if frac > 0.85 else (GRN if frac < 0.5 else ACC)
    return (
        f'<g>'
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="7" '
        f'  fill="{STEEL}" stroke="{stroke_c}" stroke-width="2.5" {glow}/>'
        f'<rect x="{x+10:.0f}" y="{belt_y:.0f}" width="{w-20:.0f}" height="{belt_h:.0f}" '
        f'  rx="3" fill="#1a1f26" stroke="{BDR}" stroke-width="1"/>'
        f'{rollers}'
        f'{btls}'
        f'<text x="{x+w/2:.0f}" y="{y-7:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="8" font-weight="700">CONVEYOR</text>'
        f'<text x="{x+w/2:.0f}" y="{belt_y-10:.0f}" text-anchor="middle" fill="{buf_color}" '
        f'  font-size="13" font-weight="700">{buffer_level}/{buffer_max}</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h-5:.0f}" text-anchor="middle" fill="{TXT}" '
        f'  font-size="10" font-weight="600">Done: {completed}</text>'
        f'<text x="{x+w/2:.0f}" y="{y+h+14:.0f}" text-anchor="middle" fill="{TXT2}" '
        f'  font-size="7">Conv {conv_pct:.0f}%</text>'
        f'</g>'
    )


# ═══════════════════════════════════════════════════════════════════════
# Full diagram composition
# ═══════════════════════════════════════════════════════════════════════

def build_pid_svg(data: Dict) -> str:
    """Return the complete process-flow P&ID as an inline SVG string."""

    # ── Unpack data ──────────────────────────────────────────────────
    level     = float(data.get("tank_level", 0))
    temp      = float(data.get("pasteur_temp", 0))
    cool      = float(data.get("cooler_temp", 0))
    flow      = float(data.get("flow_rate", 0))
    belt      = int(data.get("conveyor_queue", 0))
    belt_max  = int(data.get("conveyor_max", config.CONVEYOR_MAX_BOTTLES))
    ic        = float(data.get("inlet_valve_cmd", 0))
    pc        = float(data.get("pump_cmd", 0))
    hc        = float(data.get("heater_power_cmd", 0))
    cc        = float(data.get("cooling_valve_cmd", 0))
    cvc       = float(data.get("conveyor_cmd", 0))
    pf        = int(data.get("pump_feedback", 0))
    fc        = int(data.get("fill_valve_cmd", 0))
    bp        = int(data.get("bottle_present", 0))
    plc       = data.get("plc_state", "IDLE")
    nozzles   = data.get("nozzle_status", [0, 0, 0, 0])
    phase     = data.get("fill_phase", "INDEX")
    prog      = float(data.get("fill_progress", 0.0))
    completed = int(data.get("bottles_completed", 0))
    man       = set(data.get("_manuals", []))

    running = plc in ("RUNNING", "STARTING")
    flow_ok = running and pc > 0 and pf == 1
    s1_ok = config.TANK_LEVEL_LOW <= level <= config.TANK_LEVEL_HIGH
    s2_ok = config.PASTEUR_SAFE_MIN <= temp <= config.PASTEUR_SAFE_MAX
    s3_ok = cool <= config.COOLER_MAX_BOTTLING
    s4_ok = fc and bp
    s5_ok = cvc > 0

    def cls(ok, warn=False):
        if not running: return ""
        if not ok:      return "warn" if warn else "fault"
        return "active"

    # ── Layout constants ──────────────────────────────────────────────
    # viewBox="0 0 890 180"
    PIPE_Y = 100          # pipe centre-line (all connections at this y)

    # Node positions: (x, width, height, top_y)
    #     [InletPump] --p1-- [Tank] --p2-- [FeedPump] --p3-- [Pasteurizer]
    #     --p4-- [Cooler] --p5-- [Filler] --p6-- [Conveyor]

    # Inlet Pump (circle)
    IP_CX, IP_CY, IP_R = 35, PIPE_Y, 22
    p1_x1, p1_x2 = IP_CX + IP_R, 78

    # Raw Tank
    TK_X, TK_Y, TK_W, TK_H = 78, 18, 72, 135
    p2_x1, p2_x2 = TK_X + TK_W, 172

    # Feed Pump (circle)
    FP_CX, FP_CY, FP_R = 194, PIPE_Y, 22
    p3_x1, p3_x2 = FP_CX + FP_R, 232

    # Pasteurizer
    PZ_X, PZ_Y, PZ_W, PZ_H = 232, 34, 108, 95
    p4_x1, p4_x2 = PZ_X + PZ_W, 366

    # Cooler
    CL_X, CL_Y, CL_W, CL_H = 366, 34, 102, 95
    p5_x1, p5_x2 = CL_X + CL_W, 492

    # Filler
    FL_X, FL_Y, FL_W, FL_H = 492, 16, 128, 125
    p6_x1, p6_x2 = FL_X + FL_W, 648

    # Conveyor
    CV_X, CV_Y, CV_W, CV_H = 648, 38, 155, 92

    # ── Build SVG ─────────────────────────────────────────────────────
    svg = [f'<svg viewBox="0 0 825 175" xmlns="http://www.w3.org/2000/svg" '
           f'style="width:100%;background:{BG};">']
    svg.append(_FILTERS)
    svg.append(f"<style>{_ANIM}</style>")

    # Flow indicator strip at the very top — shows PLC state + startup phase
    sp = int(data.get("startup_phase", 2))
    sp_label = {0: "HEAT", 1: "PRIME", 2: plc}.get(sp, plc)
    flow_dot = GRN if flow_ok else (ORN if sp < 2 and running else (RED if running else BDR))
    svg.append(f'<circle cx="8" cy="10" r="5" fill="{flow_dot}"/>')
    svg.append(f'<text x="18" y="13" fill="{TXT2}" font-size="8">{sp_label}</text>')

    # Pipes (flowing = blue dash, idle = grey solid)
    for x1, x2 in [(p1_x1, p1_x2), (p2_x1, p2_x2), (p3_x1, p3_x2),
                   (p4_x1, p4_x2), (p5_x1, p5_x2), (p6_x1, p6_x2)]:
        svg.append(_pipe(x1, PIPE_Y, x2, flow_ok))

    # Inlet Pump
    svg.append(pump_node(IP_CX, IP_CY, IP_R, "INLET VALVE",
                         f"{ic:.0f}%",
                         f"{'OPEN' if ic>0 else 'SHUT'}",
                         ic > 0 and running,
                         "inlet_valve_cmd" in man,
                         "active" if ic > 0 and running else ""))

    # Raw Tank
    svg.append(tank_node(TK_X, TK_Y, TK_W, TK_H, level, "RAW TANK",
                         f"{level:.1f}%",
                         f"Target {config.TANK_LEVEL_TARGET:.0f}%  |  "
                         f"Inlet {ic:.0f}%  |  Pump {pc:.0f}%",
                         cls(s1_ok, warn=config.TANK_LEVEL_MIN_PUMP < level < config.TANK_LEVEL_HIGH),
                         "inlet_valve_cmd" in man or "pump_cmd" in man))

    # Feed Pump
    svg.append(pump_node(FP_CX, FP_CY, FP_R, "FEED PUMP",
                         f"{flow:.1f} L/min",
                         f"{'OK' if pf else 'OFF'}",
                         flow_ok,
                         "pump_cmd" in man,
                         "active" if flow_ok else cls(pc > 0 and pf == 0)))

    # Pasteurizer
    svg.append(pasteurizer_node(PZ_X, PZ_Y, PZ_W, PZ_H, temp, hc,
                                cls(s2_ok), "heater_power_cmd" in man))

    # Cooler
    svg.append(cooler_node(CL_X, CL_Y, CL_W, CL_H, cool, cc,
                           cls(s3_ok), "cooling_valve_cmd" in man))

    # Filler
    svg.append(filler_node(FL_X, FL_Y, FL_W, FL_H, nozzles, prog, phase, flow,
                           running, "active" if s4_ok else ("warn" if bp else "")))

    # Conveyor
    svg.append(conveyor_node(CV_X, CV_Y, CV_W, CV_H, belt, belt_max, completed, cvc,
                             "active" if s5_ok else ""))

    svg.append('</svg>')
    return "\n".join(svg)
