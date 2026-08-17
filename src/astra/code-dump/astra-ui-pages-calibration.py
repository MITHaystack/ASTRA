"""
Calibration page for ASTRA.

Layout
──────
 ┌─ Motion Calibration ──────────────┐  ┌─ Radio Calibration ───────────────┐
 │  [Calibrate IMU]                  │  │  RF Source: [mode ▼]              │
 │  Sync: [mode ▼]  [Sync]           │  │  ● On   ● Pulsed                 │
 │  ─────────────────────────────    │  │  ─────────────────────────────    │
 │  IMU Status:                      │  │  [Collect Background]             │
 │  Sys  ■■■□  Gyro  ■■■■            │  │  Last: Az 180°  Alt 45°  14:32   │
 │  Accel ■■□□  Mag  ■■■□            │  └───────────────────────────────────┘
 └────────────────────────────────────┘
 ┌─ IMU Telemetry ─────────────────────────────────────────────────────────────┐
 │  [Time window ▼]  [↺ Refresh]   DB: Memory                                 │
 │  ┌─ Compass ─────┐  ┌─ Position Az / Alt ───────────────────────────────┐  │
 │  │  SVG rose     │  │  plotly                                            │  │
 │  └───────────────┘  └───────────────────────────────────────────────────┘  │
 │  ┌─ Magnetometer ────────────────┐  ┌─ Accelerometer ────────────────────┐ │
 │  │  x / y / z vs time           │  │  x / y / z vs time                 │ │
 │  └──────────────────────────────┘  └────────────────────────────────────┘ │
 │  ┌─ Gyroscope ───────────────────┐  ┌─ Quaternion ───────────────────────┐ │
 │  │  x / y / z vs time           │  │  w / x / y / z vs time             │ │
 │  └──────────────────────────────┘  └────────────────────────────────────┘ │
 └─────────────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, UTC, timezone

import plotly.graph_objects as go
from nicegui import ui


from .. theme import frame
from .. state import astra_state, astra_sub, astra_cmd, motion_history, imu_history, gps_history
from astradata.objects import *

# ── compass rose SVG ──────────────────────────────────────────────────────────

def _compass_svg(heading: float = 0.0, size: int = 220, type='az') -> str:
    """SVG compass rose with needle pointing at heading (degrees, 0=N, CW)."""
    cx = cy = size / 2.0
    ro = size * 0.46           # outer radius
    ri = ro * 0.84             # inner dashed ring
    rl = ro * 0.70             # label ring
    rt_maj = ro * 0.87         # major tick start
    rt_min = ro * 0.93         # minor tick start
    nlen_n = ro * 0.58         # needle north length
    nlen_s = ro * 0.33         # needle south length
    nw     = ro * 0.055        # needle half-width
    pc     = ro * 0.06         # pivot circle radius

    parts: list[str] = []

    # background
    parts.append(
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ro:.1f}" '
        f'fill="#0a0f1e" stroke="#334155" stroke-width="2"/>'
    )

    # degree tick marks — every 5°; major every 30°
    for deg in range(0, 360, 5):
        rad    = math.radians(deg - 90)   # 0° → up (North)
        major  = deg % 30 == 0
        r_in   = rt_maj if major else rt_min
        x1 = cx + r_in * math.cos(rad);   y1 = cy + r_in * math.sin(rad)
        x2 = cx + ro   * math.cos(rad);   y2 = cy + ro   * math.sin(rad)
        col = "#64748b" if major else "#2d3f55"
        sw  = "1.6" if major else "0.7"
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{col}" stroke-width="{sw}"/>'
        )

    # inner dashed ring
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ri:.1f}" '
        f'fill="none" stroke="#1e3a5f" stroke-width="0.8" '
        f'stroke-dasharray="4 8"/>'
    )

    # cardinal & ordinal labels
    if type == 'az':
        labels = [
            (  0, "N",  "#f1f5f9", "13", "bold"),
            ( 90, "E",  "#94a3b8", "11", "normal"),
            (180, "S",  "#94a3b8", "11", "normal"),
            (270, "W",  "#94a3b8", "11", "normal"),
            ( 45, "NE", "#475569",  "9", "normal"),
            (135, "SE", "#475569",  "9", "normal"),
            (225, "SW", "#475569",  "9", "normal"),
            (315, "NW", "#475569",  "9", "normal"),
        ]
    elif type =='alt':
        labels = [
            (  0, "ZENITH",  "#f1f5f9", "13", "bold"),
            ( 90, "FRONT",  "#94a3b8", "11", "normal"),
            (180, "NADIR",  "#94a3b8", "11", "normal"),
            (270, "REAR",  "#94a3b8", "11", "normal"),
            ( 45, "", "#475569",  "9", "normal"),
            (135, "", "#475569",  "9", "normal"),
            (225, "", "#475569",  "9", "normal"),
            (315, "", "#475569",  "9", "normal"),
        ]
    for deg, txt, col, fsz, wt in labels:
        rad = math.radians(deg - 90)
        fx  = float(fsz)
        x   = cx + rl * math.cos(rad)
        y   = cy + rl * math.sin(rad) + fx * 0.36
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
            f'fill="{col}" font-size="{fsz}" font-weight="{wt}" '
            f'font-family="monospace">{txt}</text>'
        )

    if type == 'alt':
        heading += 90.0
        heading = heading % 180.0

    # needle group — rotated to heading
    parts.append(
        f'<g transform="rotate({heading:.2f},{cx:.1f},{cy:.1f})">'
    )
    # north (red)
    parts.append(
        f'<polygon points="'
        f'{cx:.1f},{cy - nlen_n:.1f} '
        f'{cx - nw:.1f},{cy:.1f} '
        f'{cx + nw:.1f},{cy:.1f}" '
        f'fill="#ef4444" opacity="0.92"/>'
    )
    # south (slate)
    parts.append(
        f'<polygon points="'
        f'{cx:.1f},{cy + nlen_s:.1f} '
        f'{cx - nw:.1f},{cy:.1f} '
        f'{cx + nw:.1f},{cy:.1f}" '
        f'fill="#94a3b8" opacity="0.60"/>'
    )
    # pivot
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{pc:.1f}" '
        f'fill="#1e293b" stroke="#64748b" stroke-width="1.5"/>'
    )
    parts.append('</g>')

    # heading value
    parts.append(
        f'<text x="{cx:.1f}" y="{cy + ro * 0.26:.1f}" '
        f'text-anchor="middle" fill="#22d3ee" '
        f'font-size="{ro * 0.19:.0f}" font-weight="bold" '
        f'font-family="monospace">{heading:.1f}°</text>'
    )

    parts.append('</svg>')
    return "".join(parts)


# ── Plotly helpers ────────────────────────────────────────────────────────────

def _hex_to_rgba(h: str, a: float = 0.12) -> str:
    h = h.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


def _base_layout(title: str, y_label: str, height: int = 220) -> dict:
    return dict(
        template      = "plotly_dark",
        paper_bgcolor = "#1e293b",
        plot_bgcolor  = "#0f172a",
        font          = dict(color="#94a3b8", size=10),
        height        = height,
        margin        = dict(l=52, r=14, t=32, b=40),
        title         = dict(
            text = title, x=0.02, pad=dict(t=4),
            font = dict(size=11, color="#e2e8f0"),
        ),
        xaxis         = dict(
            title="Time (UTC)", gridcolor="#334155",
            type="date", tickformat="%H:%M:%S",
        ),
        yaxis         = dict(title=y_label, gridcolor="#334155"),
        legend        = dict(
            orientation="h", y=1.08, font=dict(size=9)
        ),
        showlegend    = True,
    )


def _line(color: str, name: str) -> go.Scatter:
    return go.Scatter(
        x=[], y=[], mode="lines", name=name,
        line=dict(color=color, width=1.4),
    )


def _make_pos_fig() -> go.Figure:
    fig = go.Figure()
    fig.add_trace(_line("#0ea5e9", "Azimuth (°)"))
    fig.add_trace(_line("#f59e0b", "Altitude (°)"))
    fig.update_layout(**_base_layout("Position  —  Az / Alt", "Degrees", 260))
    return fig


def _make_mag_fig() -> go.Figure:
    fig = go.Figure()
    fig.add_trace(_line("#ef4444", "Mag X (µT)"))
    fig.add_trace(_line("#22c55e", "Mag Y (µT)"))
    fig.add_trace(_line("#3b82f6", "Mag Z (µT)"))
    fig.update_layout(**_base_layout("Magnetometer", "µT"))
    return fig


def _make_accel_fig() -> go.Figure:
    fig = go.Figure()
    fig.add_trace(_line("#ef4444", "Accel X"))
    fig.add_trace(_line("#22c55e", "Accel Y"))
    fig.add_trace(_line("#3b82f6", "Accel Z"))
    fig.update_layout(**_base_layout("Accelerometer", "m/s²"))
    return fig


def _make_gyro_fig() -> go.Figure:
    fig = go.Figure()
    fig.add_trace(_line("#a78bfa", "Gyro X"))
    fig.add_trace(_line("#34d399", "Gyro Y"))
    fig.add_trace(_line("#fbbf24", "Gyro Z"))
    fig.update_layout(**_base_layout("Gyroscope", "°/s"))
    return fig


def _make_quat_fig() -> go.Figure:
    fig = go.Figure()
    fig.add_trace(_line("#e2e8f0", "W"))
    fig.add_trace(_line("#ef4444", "X"))
    fig.add_trace(_line("#22c55e", "Y"))
    fig.add_trace(_line("#3b82f6", "Z"))
    fig.update_layout(**_base_layout("Quaternion", "unit"))
    return fig


def _update_fig(chart: ui.plotly, data: dict,
                keys: list[str]) -> None:
    t = data["t"]
    for i, k in enumerate(keys):
        chart.figure["data"][i]["x"] = t
        chart.figure["data"][i]["y"] = data.get(k, [])
    chart.update()


# ── calibration indicator helper ──────────────────────────────────────────────

def _cal_row(
    label: str,
    color_class: str = "text-slate-400",
) -> tuple[ui.label, ui.label]:
    """Return (level_lbl, bar_lbl) for a calibration channel."""
    with ui.row().classes("items-center gap-2"):
        ui.label(label).classes("text-xs text-slate-400 w-14")
        bar  = ui.label("□□□").classes("font-mono text-sm text-slate-600")
        lvl  = ui.label("0 / 3").classes("text-xs text-slate-500 w-10")
    return bar, lvl


def _set_cal(bar: ui.label, lvl: ui.label, level: int) -> None:
    colors = {
        0: ("text-slate-600",  "text-slate-500"),
        1: ("text-orange-400", "text-orange-300"),
        2: ("text-yellow-400", "text-yellow-300"),
        3: ("text-green-400",  "text-green-300"),
    }
    bc, lc = colors.get(level, colors[0])
    filled = "■" * level + "□" * (3 - level)
    bar.set_text(filled)
    bar.classes(
        remove="text-slate-600 text-orange-400 text-yellow-400 text-green-400",
        add=bc,
    )
    lvl.set_text(f"{level} / 3")
    lvl.classes(
        remove="text-slate-500 text-orange-300 text-yellow-300 text-green-300",
        add=lc,
    )

async def _send_set_motion_cal():
    cmd = AstraSetTargetCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.target_type = 'calibration'
    cmd.target_info = {'az_cal':True,'alt_cal':True}
    await astra_cmd.send(cmd,AstraSetTargetCommand)

async def _send_sync_command(sync_az, sync_alt, sync_values=True, sync_telemetry=False,sync_imu=False):
    cmd = AstraSyncCommand()
    cmd.timestamp       = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.sync_az     = sync_az
    cmd.sync_alt    = sync_alt
    cmd.sync_values = sync_values
    cmd.sync_telemetry  = sync_telemetry
    cmd.sync_imu        = sync_imu
    cmd.imu_offset_az   : float = 0.0
    cmd.imu_offset_alt  : float = 0.0
    await astra_cmd.send(cmd,AstraSyncCommand)

async def _send_noise_command(mode):
    cmd = AstraSetNoiseDiodeCommand()
    cmd.timestamp       = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    match mode.upper():
        case 'DISABLE':
            cmd.mode = 'DISABLE'
        case 'ENABLE':
            cmd.mode = 'ENABLE'
        case 'PULSE':
            cmd.mode = 'PULSE'
        case _:
            cmd.mode = 'DISABLE'

    await astra_cmd.send(cmd,AstraSetNoiseDiodeCommand)




# ── page ─────────────────────────────────────────────────────────────────────

def create() -> None:

    @ui.page("/calibration")
    def calibration_page() -> None:

        # per-session RF state
        _rf: dict = {
            "mode":    "disable",
            "last_bg_az":   None,
            "last_bg_alt":  None,
            "last_bg_time": None,
        }

        _ui_state = {
            'plot_time':   datetime.now(UTC),
            'plot_due':      True,
        }
        _PLOT_INTERVAL = 1.0
        _IMU_INTERVAL = 1.0

        with frame("Calibration"):

            # ══════════════════════════════════════════════════════════════
            # TOP ROW: Motion + Radio cards
            # ══════════════════════════════════════════════════════════════
            with ui.row().classes("w-full gap-6 flex-wrap items-start"):

                # ── MOTION CALIBRATION ─────────────────────────────────────
                with ui.card().classes(
                    "bg-[#1e293b] border border-[#334155] rounded-xl flex-1 min-w-80"
                ):
                    with ui.column().classes("p-5 gap-4"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("explore").classes("text-sky-400 text-xl")
                            ui.label("Motion Calibration") \
                                .classes("font-semibold text-white text-base")

                        # Calibrate motion button
                        async def _do_cal_motion() -> None:
                            
                            # send the command to the motion controller
                            await _send_set_motion_cal()

                            ui.notify(
                                "Motion calibration started — telescope "
                                "will move in calibration pattern",
                                type="positive", position="top-right",
                            )

                        ui.button(
                            "Calibrate Motion",
                            icon="compass_calibration",
                            on_click=_do_cal_motion,
                        ).classes(
                            "bg-sky-700 hover:bg-sky-600 text-white w-full"
                        )

                        ui.separator().classes("bg-slate-700/60")

                        # Sync button + mode selector
                        with ui.row().classes("items-end gap-3 w-full"):
                            with ui.column().classes("gap-1 flex-1"):
                                ui.icon("sync").classes("text-sky-400 text-xl")
                                ui.label("Sync Mode").classes(
                                    "font-semibold text-white text-base"
                                )
                                sync_sel = (
                                    ui.select(
                                        [
                                            "Values",
                                            "Position",
                                            "IMU",
                                            "Zero",
                                        ],
                                        value="Zero",
                                        label="Sync Mode",
                                    )
                                    .props("dark dense")
                                    .classes("w-full")
                                )

                            async def _do_sync() -> None:
                                mode = sync_sel.value or "Zero"
                                match mode:
                                    case 'Values':
                                        pass # place holder till we add entry fields
                                    case 'Position':
                                        await _send_sync_command(0.0,0.0, sync_values=False, sync_telemetry=True,sync_imu=False)
                                    case 'IMU':
                                        await _send_sync_command(0.0,0.0, sync_values=False, sync_telemetry=False,sync_imu=True)
                                    case 'Zero':
                                        await _send_sync_command(0.0, 0.0, sync_values=True,sync_telemetry=False,sync_imu=False)

                                ui.notify(
                                    f"Sync → {mode}",
                                    type="positive",
                                    position="top-right",
                                )

                            ui.button(
                                "Sync",
                                icon="sync",
                                on_click=_do_sync,
                            ).classes(
                                "bg-indigo-700 hover:bg-indigo-600 text-white"
                            )

                        ui.separator().classes("bg-slate-700/60")

                        # IMU status indicators
                        ui.label("IMU Calibration Status").classes(
                            "text-xs text-slate-400 font-medium"
                        )
                        with ui.grid(columns=2).classes("gap-x-6 gap-y-1 w-full"):
                            cal_sys_bar,   cal_sys_lvl   = _cal_row("System")
                            cal_gyro_bar,  cal_gyro_lvl  = _cal_row("Gyro")
                            cal_accel_bar, cal_accel_lvl = _cal_row("Accel")
                            cal_mag_bar,   cal_mag_lvl   = _cal_row("Mag")

                        ui.label(
                            "3 = fully calibrated  ·  0 = not calibrated"
                        ).classes("text-[10px] text-slate-600 italic")

                # ── RADIO CALIBRATION ──────────────────────────────────────
                with ui.card().classes(
                    "bg-[#1e293b] border border-[#334155] rounded-xl flex-1 min-w-80"
                ):
                    with ui.column().classes("p-5 gap-4"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("wifi_tethering").classes(
                                "text-amber-400 text-xl"
                            )
                            ui.label("Radio Calibration") \
                                .classes("font-semibold text-white text-base")

                        # RF noise source selector + status LEDs
                        with ui.row().classes("items-end gap-4 flex-wrap"):
                            with ui.column().classes("gap-1 min-w-44"):
                                ui.label("RF Noise Source").classes(
                                    "font-semibold text-white text-base"
                                )
                                rf_sel = (
                                    ui.select(
                                        ["disable", "enable", "pulsed"],
                                        value="disable",
                                        label="RF Noise Source",
                                    )
                                    .props("dark dense")
                                    .classes("w-full")
                                )

                            # Status dots
                            with ui.column().classes("gap-2 pb-1"):
                                with ui.row().classes("items-center gap-2"):
                                    rf_on_dot = ui.icon("circle").classes(
                                        "text-slate-600 text-base"
                                    )
                                    ui.label("On").classes(
                                        "text-xs text-slate-400"
                                    )
                                with ui.row().classes("items-center gap-2"):
                                    rf_pulse_dot = ui.icon("radio_button_checked").classes(
                                        "text-slate-600 text-base"
                                    )
                                    ui.label("Pulsed").classes(
                                        "text-xs text-slate-400"
                                    )

                        async def _on_rf_change(_=None) -> None:
                            mode = rf_sel.value or "disable"
                            _rf["mode"] = mode

                            # Update LEDs
                            is_on     = mode == "enable" or mode == "pulsed"
                            is_pulsed = mode == "pulsed"
                            rf_on_dot.classes(
                                remove="text-slate-600 text-green-400",
                                add="text-green-400" if is_on else "text-slate-600",
                            )
                            rf_pulse_dot.classes(
                                remove="text-slate-600 text-amber-400",
                                add="text-amber-400" if is_pulsed else "text-slate-600",
                            )

                            # Send MQTT command
                            await _send_noise_command(mode)

                            ui.notify(
                                f"RF noise source → {mode}",
                                type="positive" if mode != "disable" else "info",
                                position="top-right",
                            )

                        rf_sel.on_value_change(_on_rf_change)

                        ui.separator().classes("bg-slate-700/60")

                        # Collect background
                        with ui.column().classes("gap-3 w-full"):
                            ui.label("Background Collection").classes(
                                "font-semibold text-white text-base"
                            )

                            async def _do_collect_bg() -> None:
                                pobj = await astra_state.antenna_state.get('astra-pointing')
                                az  = pobj.pointing_az
                                alt = pobj.pointing_alt
                                ts  = pobj.timestamp

                                _rf["last_bg_az"]   = az
                                _rf["last_bg_alt"]  = alt
                                _rf["last_bg_time"] = ts

                                bg_az_lbl.set_text(f"Az {az:.1f}°")
                                bg_alt_lbl.set_text(f"Alt {alt:.1f}°")
                                bg_time_lbl.set_text(ts)

                                ### SEND RF BACKGROUND DAQ COMMAND
                                ### STORE IN /data/rf/calibration/cal-<isodate>
                                ### ADD WHEN WE HAVE RADIO CONTROL COMMANDS

                                ui.notify(
                                    f"RF background collection → "
                                    f"Az {az:.1f}°  Alt {alt:.1f}°",
                                    type="positive", position="top-right",
                                )

                            ui.button(
                                "Collect RF Background",
                                icon="camera",
                                on_click=_do_collect_bg,
                            ).classes(
                                "bg-emerald-700 hover:bg-emerald-600 "
                                "text-white w-full"
                            )

                            with ui.row().classes("items-center gap-3 flex-wrap"):
                                ui.label("Last:").classes(
                                    "text-xs text-slate-500"
                                )
                                with ui.row().classes(
                                    "items-center gap-1 bg-[#0f172a] "
                                    "rounded px-2 py-1"
                                ):
                                    ui.icon("explore").classes(
                                        "text-sky-400 text-xs"
                                    )
                                    bg_az_lbl = ui.label("—").classes(
                                        "text-xs font-mono text-slate-300"
                                    )
                                with ui.row().classes(
                                    "items-center gap-1 bg-[#0f172a] "
                                    "rounded px-2 py-1"
                                ):
                                    ui.icon("height").classes(
                                        "text-amber-400 text-xs"
                                    )
                                    bg_alt_lbl = ui.label("—").classes(
                                        "text-xs font-mono text-slate-300"
                                    )
                                with ui.row().classes(
                                    "items-center gap-1 bg-[#0f172a] "
                                    "rounded px-2 py-1"
                                ):
                                    ui.icon("schedule").classes(
                                        "text-slate-400 text-xs"
                                    )
                                    bg_time_lbl = ui.label("—").classes(
                                        "text-xs font-mono text-slate-300"
                                    )

            # ══════════════════════════════════════════════════════════════
            # IMU TELEMETRY TAB
            # ══════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            ):
                with ui.column().classes("w-full"):

                    # tab header
                    with ui.tabs().classes(
                        "bg-[#1e293b] text-slate-300 border-b border-[#334155]"
                    ) as tabs:
                        imu_tab = ui.tab(
                            "IMU Telemetry", icon="analytics"
                        )

                    with ui.tab_panels(tabs, value=imu_tab) \
                            .classes("bg-[#1e293b] w-full"):

                        with ui.tab_panel(imu_tab).classes("p-4"):

                            # ── time window + DB status ────────────────────
                            with ui.row().classes(
                                "items-end gap-4 flex-wrap w-full"
                            ):
                                with ui.column().classes("gap-1"):
                                    ui.label("Time Window").classes(
                                        "text-xs text-slate-400 font-medium"
                                    )
                                    tw_sel = ui.select(
                                        {
                                            30:   "30 seconds",
                                            60:   "1 minute",
                                            300:  "5 minutes",
                                            600:  "10 minutes",
                                            3600: "1 hour",
                                        },
                                        value=300,
                                        label="Time Window",
                                    ).props("dark dense").classes("min-w-40")

                                db_lbl = ui.label(
                                    f"DB: {imu_history.backend}"
                                ).classes(
                                    "text-xs text-slate-500 italic self-end"
                                )
                                ui.space()

                                async def _on_refresh() -> None:
                                    _ui_state["plot_due"] = True

                                ui.button(
                                    "↺ Refresh",
                                    icon="refresh",
                                    on_click=_on_refresh,
                                ).props("outline dense") \
                                 .classes("text-slate-300 self-end")

                            ui.separator().classes("bg-slate-700/60 my-2")

                            # ── row 1: compass + position history ──────────
                            with ui.row().classes("w-full gap-4 items-start"):

                                # Azimuth Compass rose
                                with ui.card().classes(
                                    "bg-[#0f172a] border border-[#334155] "
                                    "rounded-xl shrink-0"
                                ):
                                    with ui.column().classes(
                                        "p-3 gap-2 items-center"
                                    ):
                                        with ui.row().classes(
                                            "items-center gap-2"
                                        ):
                                            ui.icon("explore").classes(
                                                "text-cyan-400 text-sm"
                                            )
                                            ui.label("Azimuth").classes(
                                                "text-xs font-semibold "
                                                "text-slate-200"
                                            )

                                        az_heading = 0.0 # default 0.0 on startup

                                        compass_az_html = ui.html(
                                            _compass_svg(az_heading,type='az')
                                        )
                                        heading_az_lbl = ui.label(
                                            f"{az_heading:.1f}°"
                                        ).classes(
                                            "text-xs font-mono text-cyan-400"
                                        )


                                # Altitude Compass rose
                                with ui.card().classes(
                                    "bg-[#0f172a] border border-[#334155] "
                                    "rounded-xl shrink-0"
                                ):
                                    with ui.column().classes(
                                        "p-3 gap-2 items-center"
                                    ):
                                        with ui.row().classes(
                                            "items-center gap-2"
                                        ):
                                            ui.icon("explore").classes(
                                                "text-cyan-400 text-sm"
                                            )
                                            ui.label("Altitude").classes(
                                                "text-xs font-semibold "
                                                "text-slate-200"
                                            )

                                        alt_heading = 0.0 # default 0.0 on startup

                                        compass_alt_html = ui.html(
                                            _compass_svg(alt_heading,type='alt') 
                                        )
                                        heading_alt_lbl = ui.label(
                                            f"{alt_heading:.1f}°"
                                        ).classes(
                                            "text-xs font-mono text-cyan-400"
                                        )                                

                                # Position history
                                with ui.card().classes(
                                    "bg-[#1e293b] border border-[#334155] "
                                    "rounded-xl flex-1 min-w-0"
                                ):
                                    with ui.column().classes("p-3 gap-1 w-full"):
                                        with ui.row().classes(
                                            "items-center gap-2"
                                        ):
                                            ui.icon("timeline").classes(
                                                "text-sky-400 text-sm"
                                            )
                                            ui.label("Position History") \
                                                .classes(
                                                "text-xs font-semibold "
                                                "text-slate-200"
                                            )
                                        pos_chart = ui.plotly(
                                            _make_pos_fig()
                                        ).classes("w-full")

                            # ── row 2: magnetometer + accelerometer ────────
                            with ui.row().classes("w-full gap-4"):
                                with ui.card().classes(
                                    "bg-[#1e293b] border border-[#334155] "
                                    "rounded-xl flex-1 min-w-0"
                                ):
                                    with ui.column().classes("p-3 gap-1 w-full"):
                                        with ui.row().classes(
                                            "items-center gap-2"
                                        ):
                                            ui.icon("north").classes(
                                                "text-red-400 text-sm"
                                            )
                                            ui.label("Magnetometer").classes(
                                                "text-xs font-semibold "
                                                "text-slate-200"
                                            )
                                        mag_chart = ui.plotly(
                                            _make_mag_fig()
                                        ).classes("w-full")

                                with ui.card().classes(
                                    "bg-[#1e293b] border border-[#334155] "
                                    "rounded-xl flex-1 min-w-0"
                                ):
                                    with ui.column().classes("p-3 gap-1 w-full"):
                                        with ui.row().classes(
                                            "items-center gap-2"
                                        ):
                                            ui.icon("vibration").classes(
                                                "text-amber-400 text-sm"
                                            )
                                            ui.label("Accelerometer").classes(
                                                "text-xs font-semibold "
                                                "text-slate-200"
                                            )
                                        accel_chart = ui.plotly(
                                            _make_accel_fig()
                                        ).classes("w-full")

                            # ── row 3: gyro + quaternion ───────────────────
                            with ui.row().classes("w-full gap-4"):
                                with ui.card().classes(
                                    "bg-[#1e293b] border border-[#334155] "
                                    "rounded-xl flex-1 min-w-0"
                                ):
                                    with ui.column().classes("p-3 gap-1 w-full"):
                                        with ui.row().classes(
                                            "items-center gap-2"
                                        ):
                                            ui.icon("rotate_90_degrees_ccw").classes(
                                                "text-violet-400 text-sm"
                                            )
                                            ui.label("Gyroscope").classes(
                                                "text-xs font-semibold "
                                                "text-slate-200"
                                            )
                                        gyro_chart = ui.plotly(
                                            _make_gyro_fig()
                                        ).classes("w-full")

                                with ui.card().classes(
                                    "bg-[#1e293b] border border-[#334155] "
                                    "rounded-xl flex-1 min-w-0"
                                ):
                                    with ui.column().classes("p-3 gap-1 w-full"):
                                        with ui.row().classes(
                                            "items-center gap-2"
                                        ):
                                            ui.icon("360").classes(
                                                "text-emerald-400 text-sm"
                                            )
                                            ui.label("Quaternion").classes(
                                                "text-xs font-semibold "
                                                "text-slate-200"
                                            )
                                        quat_chart = ui.plotly(
                                            _make_quat_fig()
                                        ).classes("w-full")

            # ══════════════════════════════════════════════════════════════
            # TIMERS
            # ══════════════════════════════════════════════════════════════

            # 500 ms: cal indicators + compass
            async def _refresh_live() -> None:
                pobj = await astra_state.antenna_state.get('astra-pointing')

                imu_obj = await astra_state.antenna_state.get('astra-imu')
                imu_cal = imu_obj.cal_status

                # calibration indicators
                _set_cal(cal_sys_bar,   cal_sys_lvl,  imu_cal[0])
                _set_cal(cal_gyro_bar,  cal_gyro_lvl,  imu_cal[1])
                _set_cal(cal_accel_bar, cal_accel_lvl, imu_cal[2])
                _set_cal(cal_mag_bar,   cal_mag_lvl,   imu_cal[3])

                # compass rose
                compass_az_html.set_content(_compass_svg(pobj.pointing_az,type='az'))
                compass_alt_html.set_content(_compass_svg(pobj.pointing_alt,type='alt'))
                az = pobj.pointing_az
                alt = pobj.pointing_alt
                heading_az_lbl.set_text(f"{az:.1f}°")
                heading_alt_lbl.set_text(f"{alt:.1f}°")

                # DB backend label
                db_lbl.set_text(f"DB: {imu_history.backend}")

            ui.timer(_IMU_INTERVAL, _refresh_live)

            # 3 s: plot refresh (async so MongoDB query is non-blocking)
            async def _refresh_plots() -> None:
                # ── decide whether to refresh plots, slower rate ───────────────────────────
                loop_time = datetime.now(UTC)
                duration = loop_time - _ui_state['plot_time']
                time_due  = duration.total_seconds() >= _IMU_INTERVAL
                force_due = _ui_state["plot_due"]

                if time_due or force_due:
                    _ui_state["plot_due"]     = False
                    _ui_state["plot_time"]  = loop_time

                    duration = float(tw_sel.value or 300)

                    fields = {
                        'astra-position-data' : 1,
                        'astra-imu-data' : 1
                    }

                    data = await imu_history.query(fields, duration)

                    _update_fig(pos_chart,   data, ["az",     "alt"])
                    _update_fig(mag_chart,   data, ["mag_x",  "mag_y",  "mag_z"])
                    _update_fig(accel_chart, data, ["accel_x","accel_y","accel_z"])
                    _update_fig(gyro_chart,  data, ["gyro_x", "gyro_y", "gyro_z"])
                    _update_fig(quat_chart,  data, ["quat_w", "quat_x", "quat_y", "quat_z"])

            ui.timer(_PLOT_INTERVAL, _refresh_plots)

            # Initial plot on page load
            ui.timer(0.2, _refresh_plots, once=True)