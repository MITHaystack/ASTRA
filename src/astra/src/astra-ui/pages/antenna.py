"""
Antenna Control page for ASTRA.

"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC, timezone
from typing import Optional

import plotly.graph_objects as go
from nicegui import ui

from .. theme import frame
from .. state import astra_state, astra_sub, astra_cmd, motion_history
from astradata.objects import *


def _deg_to_hms(degrees):
    """Converts decimal degrees to hours, minutes, and seconds."""
    # 15 degrees = 1 hour
    hours_decimal = degrees / 15.0
    
    hours = int(hours_decimal)
    
    minutes_decimal = (hours_decimal - hours) * 60.0
    minutes = int(minutes_decimal)
    
    seconds = (minutes_decimal - minutes) * 60.0
    
    return hours, minutes, seconds


# DSO temporary location
# ── built-in DSO catalog ──────────────────────────────────────────────────────
# (name, type, ra_deg J2000, dec_deg J2000, magnitude | None)

_DSOS = {
    # ── radio calibrators & famous radio sources ──────────────────────────────
    'Cassiopeia A'          : ("Cassiopeia A",           "SupernovaRemnant", 350.866,  58.815, None),
    'Cygnus A'              : ("Cygnus A",               "RadioGalaxy",      299.868,  40.734, None),
    'Taurus A (M1)'         : ("Taurus A (M1)",          "SupernovaRemnant",  83.633,  22.015,  8.4),
    'Virgo A (M87)'         : ("Virgo A (M87)",          "RadioGalaxy",      187.706,  12.391,  8.6),
    'Sagittarius A*'        : ("Sagittarius A*",         "GalacticCenter",   266.417, -29.008, None),
    'Centaurus A (NGC5128)' : ("Centaurus A (NGC 5128)", "RadioGalaxy",      201.365, -43.019,  6.8),
    'Hercules A (3C 348)'   : ("Hercules A (3C 348)",    "RadioGalaxy",      252.783,   4.993, None),
    '3C 273'          : ("3C 273",                 "Quasar",           187.277,   2.052, 12.9),
    '3C 286': ("3C 286",                 "Quasar",           202.784,  30.509, 17.3),
    '3C 48': ("3C 48",                  "Quasar",            24.424,  33.160, 16.2),
    '3C 147': ("3C 147",                 "Quasar",            85.649,  49.852, 16.9),
    'Fornax A (NGC 1316)': ("Fornax A (NGC 1316)",    "RadioGalaxy",       50.674, -37.208,  8.5),
    'Perseus A (NGZC 1275)': ("Perseus A (NGC 1275)",   "RadioGalaxy",       49.951,  41.512, 11.9),
    'M84 (3C 272.1)': ("M84 (3C 272.1)",         "RadioGalaxy",      186.266,  12.887,  9.1),
    'NGC 1068 *3C 71)': ("NGC 1068 (3C 71)",       "Seyfert",           40.670,  -0.013,  8.9),
    # ── galaxies ──────────────────────────────────────────────────────────────
    'M31 Andromeda Galaxy': ("M31 Andromeda Galaxy",   "Galaxy",            10.684,  41.269,  3.4),
    'M33 Triangulum Galaxy': ("M33 Triangulum Galaxy",  "Galaxy",            23.462,  30.660,  5.7),
    'M51 Whirlpool Galaxy': ("M51 Whirlpool Galaxy",   "Galaxy",           202.470,  47.195,  8.4),
    'M81 Bodes Galaxy': ("M81 Bode's Galaxy",      "Galaxy",           148.888,  69.065,  6.9),
    'M82 Cigar Galaxy': ("M82 Cigar Galaxy",       "Galaxy",           148.970,  69.681,  8.4),
    'M101 Pinwheel Galaxy': ("M101 Pinwheel Galaxy",   "Galaxy",           210.802,  54.349,  7.9),
    'M104 Sombrero Galaxy': ("M104 Sombrero Galaxy",   "Galaxy",           189.997, -11.623,  8.0),
    'NGC 253 Sculptor': ("NGC 253 Sculptor",       "Galaxy",            11.888, -25.288,  7.1),
    'NGC 4565 Needle': ("NGC 4565 Needle",        "Galaxy",           189.086,  25.988,  9.6),
    'NGC 4631 Whale': ("NGC 4631 Whale",         "Galaxy",           190.533,  32.541,  9.0),
    # ── open clusters ─────────────────────────────────────────────────────────
    'M45 Pleiades': ("M45 Pleiades",           "OpenCluster",       56.871,  24.105,  1.6),
    'M44 Beehive': ("M44 Beehive",            "OpenCluster",      130.025,  19.621,  3.1),
    'M35': ("M35",                    "OpenCluster",       92.268,  24.333,  5.1),
    'NGC 869 h Per': ("NGC 869 h Per",          "OpenCluster",       34.747,  57.132,  5.3),
    'NGC 884 χ Per': ("NGC 884 χ Per",          "OpenCluster",       35.430,  57.138,  6.1),
    # ── globular clusters ─────────────────────────────────────────────────────
    'M13 Hercules Cluster': ("M13 Hercules Cluster",   "GlobularCluster",  250.423,  36.461,  5.8),
    'M3': ("M3",                     "GlobularCluster",  205.549,  28.377,  6.2),
    'M5': ("M5",                     "GlobularCluster",  229.638,   2.081,  5.6),
    'M22': ("M22",                    "GlobularCluster",  279.100, -23.905,  5.1),
    'M92': ("M92",                    "GlobularCluster",  259.280,  43.136,  6.4),
    'NGC 5139 Omega Cen': ("NGC 5139 Omega Cen",     "GlobularCluster",  201.697, -47.480,  3.9),

    # ── nebulae & supernova remnants ──────────────────────────────────────────
    'M1 Crab Nebula': ("M1  Crab Nebula",        "SupernovaRemnant",  83.633,  22.015,  8.4),
    'M8 Lagoon Nebula': ("M8  Lagoon Nebula",      "Nebula",           271.033, -24.383,  6.0),
    'M17 Omega Nebula': ("M17 Omega Nebula",       "Nebula",           275.217, -16.183,  6.0),
    'M20 Trifid Nebula': ("M20 Trifid Nebula",      "Nebula",           270.620, -23.035,  9.0),
    'M27 Dumbell Nebula': ("M27 Dumbbell Nebula",    "PlanetaryNebula",  299.901,  22.721,  7.4),
    'M42 Orion Nebula': ("M42 Orion Nebula",       "Nebula",            83.822,  -5.391,  4.0),
    'M57 Ring Nebula': ("M57 Ring Nebula",        "PlanetaryNebula",  283.396,  33.029,  8.8),
    'M97 Owl Nebula': ("M97 Owl Nebula",         "PlanetaryNebula",  168.700,  55.019,  9.9),
    'NGC 7293 Helix': ("NGC 7293 Helix",         "PlanetaryNebula",  337.410, -20.837,  7.3),
    'NGC 6543 Cat Eye': ("NGC 6543 Cat's Eye",     "PlanetaryNebula",  269.639,  66.633,  8.1),
    'NGC 6960 Veil Nebula W': ("NGC 6960 Veil Nebula W", "SupernovaRemnant", 312.180,  30.716, None),
    'NGC 6992 Veil Nebula E': ("NGC 6992 Veil Nebula E", "SupernovaRemnant", 314.260,  31.722, None),
    'NGC 7000 N American': ("NGC 7000 N. America",    "EmissionNebula",   314.000,  44.300, None),
    'IC 1805 Heart Nebula': ("IC  1805 Heart Nebula",  "EmissionNebula",    38.175,  61.451, None),
    'IC1848 Soul Nebula': ("IC  1848 Soul Nebula",   "EmissionNebula",    43.175,  60.402, None),
    'NGC 2244 Rosette': ("NGC 2244 Rosette",       "EmissionNebula",    97.778,   4.933,  4.8),
    'IC  443  Jellyfish': ("IC  443  Jellyfish",     "SupernovaRemnant",  94.310,  22.530, None),
}


# ── Plotly helpers ────────────────────────────────────────────────────────────

def _base_layout(title: str, y_label: str, height: int = 240) -> dict:
    return dict(
        template      = "plotly_dark",
        paper_bgcolor = "#1e293b",
        plot_bgcolor  = "#0f172a",
        font          = dict(color="#94a3b8", size=10),
        height        = height,
        margin        = dict(l=54, r=14, t=36, b=42),
        title         = dict(text=title,
                             font=dict(size=11, color="#e2e8f0"),
                             x=0.02, pad=dict(t=6)),
        xaxis         = dict(title="Time (UTC)", gridcolor="#334155",
                             type="date", tickformat="%H:%M:%S"),
        yaxis         = dict(title=y_label, gridcolor="#334155"),
        showlegend    = False,
    )

def _make_history_fig(title: str, y_label: str, color: str) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x         = [],
        y         = [],
        mode      = "lines",
        line      = dict(color=color, width=1.5),
        fill      = "tozeroy",
        fillcolor = _hex_to_rgba(color, 0.10),   # ← was: color + "18"
    ))
    fig.update_layout(**_base_layout(title, y_label))
    return fig

def _update_chart(chart: ui.plotly, t_list: list, val_list: list) -> None:
    chart.figure["data"][0]["x"] = t_list
    chart.figure["data"][0]["y"] = val_list
    chart.update()

def _hex_to_rgba(hex_color: str, alpha: float = 0.10) -> str:
    """Convert a 6-digit hex colour string to an rgba() string Plotly accepts."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

# command helpers

async def _stop_cmd():
    cmd = AstraStopCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.azimuth = True
    cmd.altitude = True
    await astra_cmd.send(cmd,AstraStopCommand)

async def _estop_cmd():
    cmd = AstraEStopCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.estop = True
    await astra_cmd.send(cmd,AstraEStopCommand)

async def _send_set_rate(az_rate,alt_rate):
    cmd = AstraSetRateCommand()
    cmd.timestamp  = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.az_rate = az_rate
    cmd.alt_rate  = alt_rate
    await astra_cmd.send(cmd,AstraSetRateCommand)

async def _send_goto_azalt(target_az,target_alt,az_rate,alt_rate):
    cmd = AstraSetTargetCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.target_type = 'altaz'
    cmd.target_info = {
        'target_az':target_az,'target_alt':target_alt,'az_rate':az_rate,'alt_rate':alt_rate
    }
    await astra_cmd.send(cmd,AstraSetTargetCommand)

async def _send_goto_radec(target_ra_h, target_ra_m, target_ra_s, target_dec, az_rate, alt_rate, track=False):
    cmd = AstraSetTargetCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.target_type = 'radec'
    cmd.target_info = {
        'target_ra_h':target_ra_h,'target_ra_m':target_ra_m,'target_ra_s':target_ra_s,'target_dec':target_dec,'track':track
    }
    await astra_cmd.send(cmd,AstraSetTargetCommand)

async def _send_slew(axis, ccw, rate, timeout=1.0):
    cmd = AstraSetTargetCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.target_type = 'slew'
    # map axis to values used by the mount
    match axis:
        case 'az':
            maxis = '1'
        case 'alt':
            maxis = '2'
        case 'both':
            return

    cmd.target_info = {
        'axis':maxis,'ccw':ccw, 'rate':rate, 'timeout':timeout
    }
    await astra_cmd.send(cmd,AstraSetTargetCommand)



# ── page ──────────────────────────────────────────────────────────────────────

def create() -> None:

    @ui.page("/antenna")
    def antenna_page() -> None:

        # per-session state
        _ui_state = {
            'plot_time':   datetime.now(UTC),
            'plot_due':      True,
            'az_rate': 1.0,
            'alt_rate': 1.0
        }

        _TELEMETRY_INTERVAL = 0.05
        _PLOT_INTERVAL = 1.0   # seconds between automatic plot refreshes

        # slew state — tracks which direction button is held
        _slew: dict = {"axis": None, "sign": 0.0, "active": False}

        with frame("ASTRA Control"):

            # ══════════════════════════════════════════════════════════════════
            # STATUS BADGES
            # ══════════════════════════════════════════════════════════════════
            def _badge(icon_name: str, text: str,
                       icon_cls: str = "text-slate-400") -> ui.label:
                with ui.row().classes(
                    "items-center gap-1.5 bg-[#1e293b] border border-[#334155] "
                    "rounded-lg px-3 py-1.5 min-w-40"
                ):
                    ui.icon(icon_name).classes(f"text-sm {icon_cls}")
                    return ui.label(text).classes(
                        "text-xs font-mono text-slate-300"
                    )
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl flex-1 justify-end"
            ):
                with ui.row().classes("w-full flex-wrap gap-1"):

            # ── Position display (center) ───────────────────────────────────
                    with ui.card().classes(
                        "bg-[#1e293b] border border-[#334155] rounded-xl flex-1 justify-end"
                    ):
                        with ui.column().classes("p-2 gap-1"):
                            with ui.row().classes("items-center gap-1"):
                                ui.icon("explore").classes("text-sky-400 text-lg")
                                ui.label("Current Position  ") \
                                    .classes("font-semibold text-white text-sm")
                                status_lbl = ui.label("Status: —").classes(
                                    "text-xs text-slate-400 font-mono gap-1"
                                )

                            # 4x1 metric grid
                            pos_labels: dict[str, ui.label] = {}
                            with ui.grid(columns=4).classes("gap-1 w-full"):
                                for key, label, unit, color in [
                                    ("az",       "Azimuth",   "°",   "sky"),
                                    ("alt",      "Altitude",  "°",   "amber"),
                                    ("az_rate",  "Az Rate",   "°/s", "sky"),
                                    ("alt_rate", "Alt Rate",  "°/s", "amber"),
                                ]:
                                    with ui.card().classes(
                                        "bg-[#0f172a] border border-[#334155] "
                                        "rounded-lg w-full"
                                    ):
                                        with ui.column().classes(
                                            "p-3 items-center gap-0.5"
                                        ):
                                            ui.label(label).classes(
                                                "text-[10px] text-slate-500 "
                                                "uppercase tracking-wider"
                                            )
                                            lbl = ui.label("—").classes(
                                                f"text-2xl font-bold font-mono "
                                                f"text-{color}-300 leading-tight"
                                            )
                                            ui.label(unit).classes(
                                                "text-[10px] text-slate-600"
                                            )
                                            pos_labels[key] = lbl

                            ui.separator().classes("bg-slate-700")
            
                        with ui.row().classes("p-2 gap-1 min-w-24"):
                            b_mqtt    = _badge("sensors",          "MQTT: —",        "text-slate-500")
                            b_msgs    = _badge("move_up",          "Msgs: 0",         "text-indigo-400")
                            #b_mode    = _badge("info",             "Idle",            "text-slate-400")
                        #with ui.column().classes("p-2 gap-1 min-w-24"):
                            #b_age     = _badge("schedule",         "Never",           "text-slate-400")
                        #with ui.column().classes("p-2 gap-1 min-w-24"):
                        #    b_db      = _badge("storage",          "DB: —",           "text-amber-400")
                        #    tmp_db    = _badge("holder",           "INFO: —",           "text-amber-400")
       

            # ══════════════════════════════════════════════════════════════════
            # MOTION CONTROL + RATE (side by side)
            # ══════════════════════════════════════════════════════════════════

            # ── Motion control (left) ────────────────────────────────────
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl flex-1"
            ):
                with ui.row().classes("p-3 gap-2"):
                    with ui.column().classes("p-2 gap-2"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("gamepad").classes("text-emerald-400 text-lg")
                            ui.label("Motion Control") \
                                .classes("font-semibold text-white text-sm")

                        # ── D-pad ─────────────────────────────────────────────
                        _BTN_BASE = (
                            "w-16 h-16 text-white font-bold text-xl "
                            "rounded-xl shadow-lg select-none "
                            "active:scale-95 transition-transform cursor-pointer"
                        )

                        def _jog_btn(
                            icon_name: str,
                            bg: str,
                            axis: str,
                            sign: int,
                        ) -> ui.button:
                            btn = (
                                ui.button(icon=icon_name)
                                .classes(f"{_BTN_BASE} {bg}")
                            )

                            def _press():
                                _slew["axis"]   = axis
                                _slew["sign"]   = sign
                                _slew["active"] = True

                            async def _release():
                                if _slew["active"]:
                                    _slew["active"] = False
                                    _slew["axis"]   = None

                                    cmd = AstraStopCommand()
                                    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                                    cmd.azimuth = True
                                    cmd.altitude = True
                                    await astra_cmd.send(cmd,AstraStopCommand)

                            btn.on("mousedown",   lambda: _press())
                            btn.on("mouseup",     lambda: _release())
                            btn.on("mouseleave",  lambda: _release())
                            btn.on("touchstart",  lambda: _press())
                            btn.on("touchend",    lambda: _release())
                            btn.on("touchcancel", lambda: _release())
                            return btn

                        # 3×3 D-pad grid
                        with ui.card().classes(
                            "bg-[#1e293b] border border-[#334155] rounded-xl flex-1"
                        ):
                            with ui.grid(columns=3).classes(
                                "gap-3 place-items-center mx-auto"
                            ):
                                ui.element("div")
                                _jog_btn("keyboard_arrow_up",
                                        "bg-emerald-700 hover:bg-emerald-600",
                                        "alt", 0).tooltip("Altitude Up")
                                ui.element("div")

                                _jog_btn("keyboard_arrow_left",
                                        "bg-sky-700 hover:bg-sky-600",
                                        "az", 1).tooltip("Azimuth Left")

                                # STOP (centre)
                                (
                                    ui.button(icon="stop_circle")
                                    .classes(
                                        f"{_BTN_BASE} bg-red-700 hover:bg-red-600"
                                    )
                                    .tooltip("STOP all motion")
                                    .on_click(lambda: _stop_cmd())
                                )

                                _jog_btn("keyboard_arrow_right",
                                        "bg-sky-700 hover:bg-sky-600",
                                        "az", 0).tooltip("Azimuth Right")

                                ui.element("div")
                                _jog_btn("keyboard_arrow_down",
                                        "bg-emerald-700 hover:bg-emerald-600",
                                        "alt",1).tooltip("Altitude Down")
                                ui.element("div")
                        # ── Emergency stop ─────────────────────────────────────────
                        with ui.card().classes(
                            "bg-red-950/30 border border-red-700/20 rounded-xl"
                        ):
                            # with ui.column().classes("p-2 gap-2 min-w-24"):
                                # with ui.row().classes("items-center gap-2"):
                                #     ui.icon("warning").classes("text-red-400 text-xl")
                                #     ui.label("Safety").classes("font-semibold text-white")
                                # ui.label("Halt all telescope motion immediately.") \
                                #     .classes("text-sm text-slate-400")

                            async  def estop():
                                await _estop_cmd()
                                ui.notify("⛔ EMERGENCY STOP SENT", type="negative",
                                            position="top", multi_line=True)

                            ui.button("EMERGENCY STOP", on_click=estop, icon="stop_circle") \
                                .classes("w-sm bg-red-600 hover:bg-red-500 text-white font-bold")
                        
                    with ui.column().classes("p-2 gap-2"):
                        # -- Rate slider
                        with ui.card().classes(
                            "bg-[#1e293b] border border-[#334155] rounded-xl flex-1"
                        ):
                            with ui.column().classes("gap-1 w-full"):

                                # ── Rate sliders ──────────────────────────────────────
                                with ui.column().classes("gap-1 w-full"):
                                    # for axis_key, label, color in [
                                    #     ("az",  "Azimuth Rate  (°/s)",  "sky"),
                                    #     ("alt", "Altitude Rate (°/s)", "amber"),
                                    # ]:
                                    # Capture loop variables in closure
                                    async def _handler(ax, badge, slider):
                                            v = float(slider.value or 1.0)
                                            print(f"set ax {ax} for {badge} to {v} ")
                                            badge.set_text(f"{v:.2f} °/s")
                                            if ax == 'az':
                                                _ui_state['az_rate'] = v
                                                axv = '1'
                                            elif ax == 'alt':
                                                _ui_state['alt_rate'] = v
                                                axv = '2'
                                            else:
                                                pass

                                            await _send_set_rate(_ui_state['az_rate'], _ui_state['alt_rate'])

                                    with ui.column().classes("gap-1 w-full"):
                                        with ui.row().classes(
                                            "items-center justify-between"
                                        ):
                                            ui.label("Azimuth Rate (°/s)").classes(
                                                "text-xs text-slate-400 font-medium"
                                            )
                                            rate_badge_az = ui.label("1.00 °/s").classes(
                                                f"text-xs font-mono text-{color}-300"
                                            )
                                        sld_az = (
                                            ui.slider(
                                                min=0.01, max=5.0,
                                                step=0.1, value=1.0,
                                            )
                                            .props(f"color={"sky"} dense label")
                                            .classes("w-full")
                                        )

                                        sld_az.on(
                                            "update:model-value",
                                            lambda _: _handler(
                                                "az", rate_badge_az, sld_az
                                            ),
                                        )

                                        # Store slider ref for slew tick
                                        az_rate_sld = sld_az


                                    with ui.column().classes("gap-1 w-full"):
                                        with ui.row().classes(
                                            "items-center justify-between"
                                        ):
                                            ui.label("Altitude Rate (°/s)").classes(
                                                "text-xs text-slate-400 font-medium"
                                            )
                                            rate_badge_alt = ui.label("1.00 °/s").classes(
                                                f"text-xs font-mono text-{color}-300"
                                            )
                                        sld_alt = (
                                            ui.slider(
                                                min=0.01, max=5.0,
                                                step=0.1, value=1.0,
                                            )
                                            .props(f"color={"amber"} dense label")
                                            .classes("w-full")
                                        )

                                        sld_alt.on(
                                            "update:model-value",
                                            lambda _: _handler(
                                                "alt", rate_badge_alt, sld_alt
                                            ),
                                        )

                                        # Store slider ref for slew tick
                                        alt_rate_sld = sld_alt

                                ui.label(
                                    "Hold a direction button to slew  ·  "
                                    "Release to stop"
                                ).classes("text-[10px] text-slate-500 italic text-center")

                            

                        # ── Source catalogue ──────────────────────────────────────
                        with ui.card().classes("bg-[#1e293b] border border-[#334155] rounded-xl"):
                            with ui.column().classes("p-2 gap-1 min-w-64"):
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon("star").classes("text-amber-400 text-xl")
                                    ui.label("Source Catalog").classes("font-semibold text-white")

                                #sources = [
                                #    "Sun", "Venus", "Moon", "Mars", "Jupiter", "Saturn", "Cassiopeia A", "Cygnus A", "Virgo A", "Sagitarius A",
                                #   "Taurus A", 
                                #]
                                sources = list(_DSOS)
                                selected = ui.select(
                                    sources, value="Cassiopeia A", label="Select source"
                                ).classes("w-full").props("dark")

                                async def _trackobj():
                                    #await _send_track_object(selected.value)

                                    #(name, type, ra_deg J2000, dec_deg J2000, magnitude | None)
                                    track_obj = _DSOS[selected.value]
                                    ra_dms = _deg_to_hms(track_obj[2])
                                    dec_dd = track_obj[3]
                                    az_r = _ui_state['az_rate']
                                    alt_r = _ui_state['alt_rate']

                                    print("_trackobj : ", ra_dms, dec_dd, az_r, alt_r)
                                                                    
                                    await _send_goto_radec(ra_dms[0], ra_dms[1], ra_dms[2], dec_dd, az_r, alt_r, track=False)

                                    ui.notify(
                                        f"Goto: {selected.value} - {track_obj[1]}", type="info",
                                        position="top-right",
                                    )

                                ui.button("Goto Source", icon="send",
                                        on_click=_trackobj) \
                                    .classes("bg-indigo-700 hover:bg-indigo-600 text-white")

                        ui.separator().classes("bg-slate-700")

            # ══════════════════════════════════════════════════════════════════
            # GOTO COMMANDS CARD
            # ══════════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl flex-1"
            ):
                with ui.column().classes("p-2 gap-2 w-full"):
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("my_location").classes("text-indigo-400 text-xl")
                        ui.label("Goto Commands") \
                            .classes("font-semibold text-white text-base")

                    # ── AltAz goto ────────────────────────────────────────────
                    with ui.row().classes(
                        "items-center gap-2 flex-wrap w-full "
                        "bg-[#0f172a] rounded-lg px-4 py-3"
                    ):
                        ui.label("Alt / Az").classes(
                            "text-xs font-bold text-slate-400 uppercase "
                            "tracking-wider w-16"
                        )
                        goto_az_in = (
                            ui.number("Azimuth (°)", value=0.0,
                                      min=-185, max=185, step=0.1, format="%.1f")
                            .props("dark dense").classes("min-w-40")
                        )
                        goto_alt_in = (
                            ui.number("Altitude (°)", value=0.0,
                                      min=-5, max=90, step=0.1, format="%.1f")
                            .props("dark dense").classes("min-w-40")
                        )
                        ui.space()

                        async def _goto_altaz():
                            az  = float(goto_az_in.value  or 0.0)
                            alt = float(goto_alt_in.value or 0.0)
                            if not (-185 <= az <= 185 and -5 <= alt <= 90):
                                ui.notify("Invalid Az/Alt", type="warning"); return
                            await _send_goto_azalt(az, alt, _ui_state['az_rate'], _ui_state['alt_rate'])
                            ui.notify(
                                f"Goto  Az {az:.1f}°  Alt {alt:.1f}°",
                                type="positive", position="top-right",
                            )

                        ui.button("Goto AltAz", icon="send",
                                  on_click=_goto_altaz) \
                            .classes("bg-indigo-700 hover:bg-indigo-600 text-white")

                    # ── RaDec goto ────────────────────────────────────────────
                    with ui.row().classes(
                        "items-center gap-2 flex-wrap w-full "
                        "bg-[#0f172a] rounded-lg px-4 py-3"
                    ):
                        ui.label("RA / Dec").classes(
                            "text-xs font-bold text-slate-400 uppercase "
                            "tracking-wider w-16"
                        )
                        with ui.row().classes("items-end gap-1"):
                            goto_ra_h = (
                                ui.number("h", value=12,
                                          min=0, max=23, step=1, format="%d")
                                .props("dark dense").classes("w-16")
                            )
                            ui.label("ʰ").classes("text-slate-400 pb-1 text-sm")
                            goto_ra_m = (
                                ui.number("m", value=0,
                                          min=0, max=59, step=1, format="%02d")
                                .props("dark dense").classes("w-16")
                            )
                            ui.label("ᵐ").classes("text-slate-400 pb-1 text-sm")
                            goto_ra_s = (
                                ui.number("s", value=0.0,
                                          min=0, max=59.99,
                                          step=0.1, format="%05.2f")
                                .props("dark dense").classes("w-20")
                            )
                            ui.label("ˢ").classes("text-slate-400 pb-1 text-sm")

                        goto_dec = (
                            ui.number("Dec (°)", value=45.0,
                                      min=-90, max=90, step=0.1, format="%0.2f")
                            .props("dark dense").classes("min-w-36")
                        )
                        ui.space()

                        async def _goto_radec():
                            ra_h = int(goto_ra_h.value or 0)
                            ra_m = int(goto_ra_m.value or 0)
                            ra_s = float(goto_ra_s.value or 0)
                            dec  = float(goto_dec.value or 0)
                            if not (0 <= ra_h <= 23 and
                                    0 <= ra_m <= 59 and
                                    0 <= ra_s < 60.0):
                                ui.notify("Invalid RA", type="warning"); return
                            if not (-90 <= dec <= 90):
                                ui.notify("Invalid Dec", type="warning"); return
                            await _send_goto_radec(ra_h, ra_m, ra_s, dec, _ui_state['az_rate'], _ui_state['alt_rate'])
                            ui.notify(
                                f"Goto  "
                                f"{ra_h:02d}ʰ{ra_m:02d}ᵐ{ra_s:05.2f}ˢ  "
                                f"Dec {dec:+.2f}°",
                                type="positive", position="top-right",
                            )

                        ui.button("Goto RaDec", icon="send",
                                  on_click=_goto_radec) \
                            .classes("bg-violet-700 hover:bg-violet-600 text-white")
            # ══════════════════════════════════════════════════════════════════
            # MOTION HISTORY CARD
            # ══════════════════════════════════════════════════════════════════
            # with ui.card().classes(
            #     "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            # ):
            #     with ui.column().classes("p-5 gap-2 w-full"):

            #         # ── header + controls ─────────────────────────────────────
            #         with ui.row().classes("items-center gap-1"):
            #             ui.icon("timeline").classes("text-amber-400 text-xl")
            #             ui.label("Motion History") \
            #                 .classes("font-semibold text-white text-base")

            #         with ui.row().classes("flex-wrap gap-2 items-end"):
            #             with ui.column().classes("gap-1"):
            #                 ui.label("Time Unit").classes(
            #                     "text-xs text-slate-400 font-medium"
            #                 )
            #                 time_unit_sel = ui.select(
            #                     {"min": "Minutes", "hr": "Hours", "day": "Days"},
            #                     value="min",
            #                 ).props("dark dense").classes("w-32")

            #             with ui.column().classes("gap-1 min-w-56"):
            #                 dur_badge = ui.label("15 min").classes(
            #                     "text-xs font-mono text-amber-300"
            #                 )
            #                 duration_sld = (
            #                     ui.slider(min=1, max=120,
            #                               step=1, value=15)
            #                     .props("color=amber dense label")
            #                     .classes("w-full")
            #                 )

            #             ui.space()

            #             async def _on_refresh():
            #                 _ui_state["plot_due"] = True

            #             (
            #                 ui.button("↺  Refresh", icon="refresh",
            #                           on_click=_on_refresh)
            #                 .props("outline")
            #                 .classes("text-slate-300 self-end")
            #             )

            #         # ── time unit / slider coordination ───────────────────────
            #         def _on_unit_change() -> None:
            #             unit = time_unit_sel.value
            #             if unit == "min":
            #                 duration_sld.min = 1
            #                 duration_sld.max = 120
            #                 duration_sld.value = 15
            #             elif unit == "hr":
            #                 duration_sld.min = 1
            #                 duration_sld.max = 48
            #                 duration_sld.value = 2
            #             else:
            #                 duration_sld.min = 1
            #                 duration_sld.max = 30
            #                 duration_sld.value = 1
            #             _update_dur_badge()
            #             _ui_state["plot_due"] = True

            #         def _update_dur_badge() -> None:
            #             v    = float(duration_sld.value or 1)
            #             unit = time_unit_sel.value
            #             suffix = {"min": "min", "hr": "hr", "day": "day"}
            #             dur_badge.set_text(f"{v:.0f} {suffix.get(unit, 'min')}")

            #         time_unit_sel.on_value_change(lambda _: _on_unit_change())
            #         duration_sld.on("update:model-value",
            #                         lambda _: _update_dur_badge())

            #         # ── 2×2 plot grid ─────────────────────────────────────────
            #         with ui.row().classes("w-full gap-2 flex-wrap"):
            #             with ui.card().classes(
            #                 "bg-[#1e293b] border border-[#334155] "
            #                 "rounded-xl flex-1 min-w-0"
            #             ):
            #                 az_chart = ui.plotly(
            #                     _make_history_fig("Azimuth",  "Az (°)",   "#0ea5e9")
            #                 ).classes("w-full")

            #             with ui.card().classes(
            #                 "bg-[#1e293b] border border-[#334155] "
            #                 "rounded-xl flex-1 min-w-0"
            #             ):
            #                 alt_chart = ui.plotly(
            #                     _make_history_fig("Altitude", "Alt (°)",  "#f59e0b")
            #                 ).classes("w-full")

            #         with ui.row().classes("w-full gap-2 flex-wrap"):
            #             with ui.card().classes(
            #                 "bg-[#1e293b] border border-[#334155] "
            #                 "rounded-xl flex-1 min-w-0"
            #             ):
            #                 az_rate_chart = ui.plotly(
            #                     _make_history_fig("Az Rate",  "°/s",  "#8b5cf6")
            #                 ).classes("w-full")

            #             with ui.card().classes(
            #                 "bg-[#1e293b] border border-[#334155] "
            #                 "rounded-xl flex-1 min-w-0"
            #             ):
            #                 alt_rate_chart = ui.plotly(
            #                     _make_history_fig("Alt Rate", "°/s",  "#10b981")
            #                 ).classes("w-full")

            # ══════════════════════════════════════════════════════════════════
            # HELPERS used by timers
            # ══════════════════════════════════════════════════════════════════

            def _duration_s() -> float:
                v    = float(duration_sld.value or 15)
                unit = time_unit_sel.value
                mult = {"min": 60, "hr": 3600, "day": 86400}
                return v * mult.get(unit, 60)

            def _do_update_plots(data: dict) -> None:
                _update_chart(az_chart,       data["t"], data["az"])
                _update_chart(alt_chart,      data["t"], data["alt"])
                _update_chart(az_rate_chart,  data["t"], data["az_rate"])
                _update_chart(alt_rate_chart, data["t"], data["alt_rate"])

            # ══════════════════════════════════════════════════════════════════
            # SLEW TICK  (200 ms)
            # Periodically re-emits the slew command while a D-pad button is held
            # ══════════════════════════════════════════════════════════════════
            async def _slew_tick() -> None:
                if not _slew["active"] or _slew["axis"] is None:
                    return
                if _slew["axis"] == "az":
                    rate = float(az_rate_sld.value)
                else:
                    rate = float(alt_rate_sld.value)
                
                await _send_slew(_slew["axis"], _slew["sign"], rate)

            ui.timer(0.500, _slew_tick)

            # ══════════════════════════════════════════════════════════════════
            # DISPLAY REFRESH  (50 ms)  — async so MongoDB query runs off-loop
            # ══════════════════════════════════════════════════════════════════
            async def _refresh() -> None:
                now = datetime.now(UTC)

                # ── connection badges ─────────────────────────────────────────

                # telemetry connection, command is ephemeral
                if astra_sub.is_connected:
                    b_mqtt.set_text("MQTT: ● Live")
                else:
                    b_mqtt.set_text("MQTT: ○ Idle")

                # database connection
                #b_db.set_text(f"DB: {motion_history.backend}")

                # ── telemetry snapshot ────────────────────────────────────────
                pobj = await astra_state.antenna_state.get('astra-pointing')
                robj = await astra_state.antenna_state.get('mount-rate')
                az_mode = await astra_state.antenna_state.get('mount-mode-az')
                alt_mode = await astra_state.antenna_state.get('mount-mode-alt')

                #print("pobj -> ", pobj)
                #print("robj -> ", robj)

                #print("azm -> ", az_mode)
                #print("altm -> ", alt_mode)

                mstat_az = "MOVING" if az_mode.moving else "STOP"
                mstat_alt = "MOVING" if alt_mode.moving else "STOP"

                pos_labels["az"].set_text(f"{pobj.pointing_az:.2f}")
                pos_labels["alt"].set_text(f"{pobj.pointing_alt:.2f}")
                pos_labels["az_rate"].set_text(f"{robj.az_rate:.1f}")
                pos_labels["alt_rate"].set_text(f"{robj.alt_rate:.1f}")

                status_lbl.set_text(f"    AZ: {mstat_az} ALT: {mstat_alt}")

                # if tel.epoch > 0:
                #     age = now - tel.epoch
                #     age_lbl.set_text(
                #         f"Last update: {age:.1f}s ago"
                #         if age < 60
                #         else f"Last update: {age/60:.1f}m ago"
                #     )
                #     b_age.set_text(
                #         f"Age: {age:.1f}s"
                #         if age < 60
                #         else f"Age: {age/60:.1f}m"
                #     )

                b_msgs.set_text(f"update {pobj.timestamp}")

                # ── decide whether to refresh plots, slower rate ───────────────────────────
                # loop_time = now
                # duration = loop_time - _ui_state['plot_time']
                # time_due  = duration.total_seconds() >= _PLOT_INTERVAL
                # force_due = _ui_state["plot_due"]

                # if time_due or force_due:
                #     _ui_state["plot_due"]     = False
                #     _ui_state["plot_time"]  = loop_time

                #     # form query
                #     fields = {
                #         'astra-position-data' : 1,
                #         'astra-rate-data' : 1
                #     }

                #     try:
                #         loop = asyncio.get_event_loop()
                #         data = await motion_history.query(fields,_duration_s())
                #         _do_update_plots(data)
                #     except:
                #         print("problem updating motion history from mongodb")
            

            ui.timer(_TELEMETRY_INTERVAL, _refresh)

