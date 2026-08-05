"""
Settings page for ASTRA.

Data Storage section
--------------------
- Output directory input
- Live storage usage bar  (blue=unknown, green<80%, yellow<90%, red≥90%)
- Expire controls  (type × period)  with confirmation dialog
- Background async clean task  (simulated for now)
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, UTC, timezone
from typing import Optional

from nicegui import ui

from .. theme import frame
from .. state import astra_state, astra_sub, astra_cmd, motion_history
from astradata.objects import *

from .. spectrometer.engine import SpectrometerConfig

# ── module-level singleton shared across browser clients ──────────────────────
_spectrometer_config = SpectrometerConfig()

# ── storage helpers ───────────────────────────────────────────────────────────

def _read_storage(path: str) -> tuple[Optional[float], Optional[float]]:
    """
    Return (used_gb, total_gb) for the filesystem that contains *path*.
    Returns (None, None) if the path does not exist or is unreadable.
    Both values are in GiB (1 GiB = 2^30 bytes).
    """
    try:
        st      = shutil.disk_usage(path if os.path.exists(path) else "/")
        total   = st.total / (1024 ** 3)
        used    = st.used  / (1024 ** 3)
        return used, total
    except Exception:
        return None, None


def _bar_color(fraction: Optional[float]) -> str:
    """Map usage fraction → Tailwind/Quasar colour token."""
    if fraction is None:
        return "blue"
    if fraction < 0.80:
        return "green"
    if fraction < 0.90:
        return "yellow"
    return "red"


def _bar_label(
    used:     Optional[float],
    total:    Optional[float],
    fraction: Optional[float],
    path:     str,
) -> str:
    if used is None or total is None:
        return f"Storage: unknown  (path does not exist: {path})"
    free = total - used
    pct  = (fraction or 0.0) * 100.0
    return (
        f"{used:.1f} GB used  /  {total:.1f} GB total  ·  "
        f"{free:.1f} GB free  ({pct:.1f} %)"
    )


# ── simulated clean routine ───────────────────────────────────────────────────

async def _run_clean(
    directory:  str,
    expire:     str,
    period:     str,
    status_lbl: ui.label,
    prog_bar:   ui.linear_progress,
    clean_btn:  ui.button,
) -> None:
    """
    Simulated storage-clean background task.

    Replace the body of the inner loop with real filesystem
    operations when ready.  The progress bar and status label
    are updated on the event loop throughout.
    """
    clean_btn.set_enabled(False)
    prog_bar.set_visibility(True)

    steps = 8
    for i in range(steps):
        prog_bar.set_value((i + 1) / steps)
        status_lbl.set_text(
            f"Cleaning  [{expire}]  [{period}]  …  step {i + 1}/{steps}"
        )
        # ── replace with real work here ───────────────────────────────────────
        await asyncio.sleep(0.4)   # simulate I/O work
        # ─────────────────────────────────────────────────────────────────────

    prog_bar.set_value(1.0)
    status_lbl.set_text(
        f"✅  Clean complete  —  expire: {expire}  /  period: {period}"
    )
    await asyncio.sleep(1.2)
    prog_bar.set_visibility(False)
    prog_bar.set_value(0.0)
    clean_btn.set_enabled(True)

# -- Command helpers

async def _send_set_location(site_name,latitude,longitude,altitude,use_gps=True):
    cmd = AstraSetLocationCommand()
    cmd.timestamp  = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.site_name = site_name
    cmd.use_gps = use_gps # only if locked
    cmd.latitude  = latitude
    cmd.longitude = longitude
    cmd.altitude = altitude
    await astra_cmd.send(cmd,AstraSetLocationCommand)

# view helpers

def _slider_badge(
    label:   str,
    lo:      float,
    hi:      float,
    default: float,
    step:    float,
    fmt:     str,
    color:   str,
    unit:    str = "",
) -> tuple[ui.slider, ui.label]:
    with ui.column().classes("gap-1 min-w-56"):
        with ui.row().classes("items-center justify-between"):
            ui.label(label).classes("text-xs text-slate-400 font-medium")
            badge = ui.label(fmt % default + unit).classes(
                f"text-xs font-mono text-{color}-300"
            )
        sld = (
            ui.slider(min=lo, max=hi, step=step, value=default)
            .props(f"color={color} dense label")
            .classes("w-full")
        )
    return sld, badge

# ── page ──────────────────────────────────────────────────────────────────────

def create() -> None:

    @ui.page("/settings")
    def settings() -> None:

                # per-session state
        _ui_state = {
            "last_render_count":    -1,
            "last_completed_t":      datetime.now(UTC),
            "last_mqtt_render_t":    datetime.now(UTC),
            "last_control_change_t": datetime.now(UTC),
            "control_render_due":    True,
            "resolution": 1000,
            "limiting_magnitude": 3.0,
            "fov": 60.0,
            "show_constellation_lines": True,
            "show_constellation_labels": True,
            "show_altaz_grid": True,
            "show_radec_grid": False,
            "show_milky_way": True,
            "show_nebula": False,
            "show_open_clusters": False
        }


        with frame("Settings"):
            with ui.row().classes("w-full flex-wrap gap-6 items-start"):

                # ── Site configuration ────────────────────────────────────────
                with ui.card().classes(
                    "bg-[#1e293b] border border-[#334155] rounded-xl"
                ):
                    # ══════════════════════════════════════════════════════════════════
                    # OBSERVER LOCATION
                    # ══════════════════════════════════════════════════════════════════
                    with ui.row().classes("p-5 gap-4 min-w-80"):
                        with ui.column().classes("p-5 gap-4 min-w-80"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("place").classes("text-sky-400 text-xl")
                                ui.label("Site Configuration") \
                                    .classes("font-semibold text-white text-base")
                            osite = ui.input("Site Name",
                                    value="MIT Haystack Observatory") \
                                .props("dark").classes("w-full")
                            olat = ui.number("Latitude (°N)",  value=42.6233,
                                    format="%.4f") \
                                .props("dark").classes("w-full")
                            olong = ui.number("Longitude (°E)", value=-71.4882,
                                    format="%.4f") \
                                .props("dark").classes("w-full")
                            oelev = ui.number("Elevation (m)",  value=131.0,
                                    format="%.1f") \
                                .props("dark").classes("w-full")
                            
                            async def _on_location() -> None:
                                    loc_btn.set_enabled(False)
                                    loc_spin.set_visibility(True)
                                    
                                    await _send_set_location(osite.value,olat.value,olong.value,oelev.value)

                                    loc_btn.set_enabled(True)
                                    loc_spin.set_visibility(False)
                                    loc_status.set_text(
                                        f"Sent set location"
                                    )
                                    ui.notify(
                                        f"Set location",
                                        type  = "positive",
                                        position = "top-right",
                                    )

                            with ui.row().classes("items-center gap-2"):
                                loc_btn = (
                                    ui.button(
                                        "Set Location",
                                        icon     = "place",
                                        on_click = _on_location,
                                    )
                                    .classes(
                                        "bg-violet-700 hover:bg-violet-600 "
                                        "text-white"
                                    )
                                )
                                loc_spin = ui.spinner(size="sm", color="violet")
                                loc_spin.set_visibility(False)

                            loc_status = ui.label("").classes(
                                    "text-[10px] text-slate-500 font-mono "
                                    "text-right max-w-xs"
                                )

                        # ══════════════════════════════════════════════════════════════════
                        # OBSERVER TIME
                        # ══════════════════════════════════════════════════════════════════
                        with ui.column().classes("p-5 gap-4 min-w-80"):
                                with ui.row().classes("items-center gap-2"):
                                    ui.icon("place").classes("text-sky-400 text-xl")
                                    ui.label("Observer Location & Time") \
                                        .classes("font-semibold text-white text-base")

                                with ui.row().classes("flex-wrap gap-5 items-end w-full"):
                                    ui.separator().classes("bg-slate-700 w-px h-auto mx-1")
                                    with ui.column().classes("gap-1"):
                                        ui.label("Time Source").classes(
                                            "text-xs text-slate-400 font-medium"
                                        )
                                        time_src = ui.toggle(
                                            {"live": "🕐 Live UTC", "manual": "📅 Manual"},
                                            value="live",
                                        ).props("dense")
                                    with ui.column().classes("gap-1") as manual_col:
                                        ui.label("Manual Date / Time (UTC)").classes(
                                            "text-xs text-slate-400"
                                        )
                                        with ui.row().classes("gap-2 items-center"):
                                            date_in = (
                                                ui.date(
                                                    value=datetime.now(UTC).isoformat().replace("+00:00", "Z")
                                                )
                                                .props("dark dense").classes("w-40")
                                            )
                                            time_in = (
                                                ui.time(
                                                    value=datetime.now(UTC).isoformat().replace("+00:00", "Z")
                                                )
                                                .props("dark dense").classes("w-32")
                                            )
                                    manual_col.set_visibility(False)
                                    time_src.on_value_change(
                                        lambda _: manual_col.set_visibility(
                                            time_src.value == "manual"
                                        )
                                    )

                                    # ══════════════════════════════════════════════════════════════════
                # DISPLAY CONTROLS
                # ══════════════════════════════════════════════════════════════════              
                # with ui.card().classes(
                #     "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
                # ):
                #     with ui.card().classes(
                #         "bg-[#1e293b] border border-[#334155] rounded-xl"
                #     ):
                #         with ui.column().classes("p-5 gap-4 w-full"):
                #             with ui.row().classes("items-center gap-2"):
                #                 ui.icon("tune").classes("text-indigo-400 text-xl")
                #                 ui.label("Display Controls") \
                #                     .classes("font-semibold text-white text-base")

                #             with ui.row().classes("flex-wrap gap-8 items-start w-full"):
                #                 mag_sld, mag_badge = _slider_badge(
                #                     "Limiting Magnitude",
                #                     1.0, 10.0, _ui_state["limiting_magnitude"],
                #                     0.5, "%.1f", "sky",
                #                 )
                #                 fov_sld, fov_badge = _slider_badge(
                #                     "Field of View",
                #                     5, 160, _ui_state["fov"],
                #                     5, "%.0f", "amber", "°",
                #                 )
                #                 with ui.column().classes("gap-1 min-w-44"):
                #                     ui.label("Render Resolution").classes(
                #                         "text-xs text-slate-400 font-medium"
                #                     )
                #                     res_sel = ui.select(
                #                         {
                #                             800:  "800 px  (fast)",
                #                             1000: "1000 px",
                #                             2000: "2000 px  (quality)",
                #                             3000: "3000 px  (high)",
                #                         },
                #                         value=_ui_state["resolution"],
                #                     ).props("dark dense")
                #     with ui.card().classes(
                #         "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
                #     ):
                #         with ui.row().classes("flex-wrap gap-x-6 gap-y-2"):
                #             ui.label("Overlays:").classes(
                #                 "text-xs text-slate-400 font-medium mr-1"
                #             )
                #             chk_con_lines = ui.checkbox(
                #                 "Constellation Lines",
                #                 value=_ui_state["show_constellation_lines"],
                #             ).props("dark color=sky dense")
                #             chk_con_labels = ui.checkbox(
                #                 "Constellation Labels",
                #                 value=_ui_state["show_constellation_labels"],
                #             ).props("dark color=sky dense")
                #             chk_altaz = ui.checkbox(
                #                 "Alt/Az Grid",
                #                 value=_ui_state["show_altaz_grid"],
                #             ).props("dark color=indigo dense")
                #             chk_radec = ui.checkbox(
                #                 "RA/Dec Grid",
                #                 value=_ui_state["show_radec_grid"],
                #             ).props("dark color=indigo dense")
                #             chk_mw = ui.checkbox(
                #                 "Milky Way",
                #                 value=_ui_state["show_milky_way"],
                #             ).props("dark color=amber dense")
                #             chk_nebula = ui.checkbox(
                #                 "Nebulae",
                #                 value=_ui_state["show_nebula"],
                #             ).props("dark color=emerald dense")
                #             chk_clusters = ui.checkbox(
                #                 "Open Clusters",
                #                 value=_ui_state["show_open_clusters"],
                #             ).props("dark color=emerald dense")

            # ── Data Storage ──────────────────────────────────────────────────
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            ):
                with ui.column().classes("p-5 gap-5 w-full"):

                    # header
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("storage").classes("text-amber-400 text-xl")
                        ui.label("Data Storage") \
                            .classes("font-semibold text-white text-base")

                    # ── output directory ──────────────────────────────────────
                    with ui.row().classes("items-end gap-4 flex-wrap w-full"):
                        dir_in = (
                            ui.input("Output Directory", value="/data/astra")
                            .props("dark dense")
                            .classes("flex-1 min-w-64")
                        )

                        async def _on_refresh_storage() -> None:
                            await _refresh_storage()

                        ui.button(
                            "Refresh",
                            icon     = "refresh",
                            on_click = _on_refresh_storage,
                        ).props("outline dense").classes("text-slate-300 self-end")

                    # ── storage usage bar ─────────────────────────────────────
                    with ui.column().classes("gap-2 w-full"):

                        usage_lbl = ui.label("Storage: checking…").classes(
                            "text-xs font-mono text-slate-400"
                        )

                        usage_bar = (
                            ui.linear_progress(value=0.0, size="16px")
                            .props("color=blue rounded")
                            .classes("w-full")
                        )

                        # sub-labels: used / total
                        with ui.row().classes(
                            "justify-between w-full"
                        ):
                            used_lbl  = ui.label("Used: —").classes(
                                "text-[10px] text-slate-500 font-mono"
                            )
                            total_lbl = ui.label("Total: —").classes(
                                "text-[10px] text-slate-500 font-mono"
                            )
                            free_lbl  = ui.label("Free: —").classes(
                                "text-[10px] text-slate-500 font-mono"
                            )

                    ui.separator().classes("bg-slate-700/60")

                    # ── expire controls ───────────────────────────────────────
                    with ui.column().classes("gap-3 w-full"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("delete_sweep").classes(
                                "text-red-400 text-lg"
                            )
                            ui.label("Expire Storage").classes(
                                "text-sm font-semibold text-slate-200"
                            )
                        ui.label(
                            "Select data type and time window, then press "
                            "Expire to begin cleanup."
                        ).classes("text-xs text-slate-500")

                        with ui.row().classes(
                            "flex-wrap gap-4 items-end w-full"
                        ):
                            with ui.column().classes("gap-1"):
                                ui.label("Expire").classes(
                                    "text-xs text-slate-400 font-medium"
                                )
                                expire_sel = (
                                    ui.select(
                                        ["all", "RF", "Images", "Telemetry"],
                                        value="all",
                                        label="Data type",
                                    )
                                    .props("dark dense")
                                    .classes("min-w-40")
                                )

                            with ui.column().classes("gap-1"):
                                ui.label("Period").classes(
                                    "text-xs text-slate-400 font-medium"
                                )
                                period_sel = (
                                    ui.select(
                                        ["last hour", "last day",
                                         "last week", "all"],
                                        value="last day",
                                        label="Time window",
                                    )
                                    .props("dark dense")
                                    .classes("min-w-44")
                                )

                            # ── confirmation dialog ───────────────────────────
                            with ui.dialog() as confirm_dialog, \
                                    ui.card().classes(
                                        "bg-[#1e293b] border border-red-700/50 "
                                        "rounded-xl min-w-80"
                                    ):
                                with ui.column().classes("p-5 gap-4"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.icon("warning").classes(
                                            "text-red-400 text-xl"
                                        )
                                        ui.label("Confirm Storage Expiry") \
                                            .classes(
                                                "font-semibold text-white"
                                            )

                                    confirm_detail = ui.label("").classes(
                                        "text-sm text-slate-300"
                                    )

                                    confirm_radio = ui.radio(
                                        ["cancel", "okay"],
                                        value="cancel",
                                    ).props("dark inline").classes(
                                        "text-slate-200"
                                    )

                                    with ui.row().classes(
                                        "justify-end gap-3 w-full"
                                    ):
                                        def _cancel() -> None:
                                            confirm_radio.set_value("cancel")
                                            confirm_dialog.close()

                                        def _confirm() -> None:
                                            choice = confirm_radio.value
                                            confirm_dialog.close()
                                            if choice == "okay":
                                                asyncio.create_task(
                                                    _run_clean(
                                                        dir_in.value,
                                                        expire_sel.value,
                                                        period_sel.value,
                                                        clean_status,
                                                        clean_prog,
                                                        clean_btn,
                                                    )
                                                )

                                        ui.button(
                                            "Cancel",
                                            icon     = "close",
                                            on_click = _cancel,
                                        ).props("outline").classes(
                                            "text-slate-400"
                                        )
                                        ui.button(
                                            "Okay — expire now",
                                            icon     = "delete_forever",
                                            on_click = _confirm,
                                        ).classes(
                                            "bg-red-700 hover:bg-red-600 "
                                            "text-white"
                                        )

                            def _open_confirm() -> None:
                                confirm_detail.set_text(
                                    f"This will permanently delete "
                                    f"[ {expire_sel.value} ] data from "
                                    f"[ {period_sel.value} ] in:\n"
                                    f"{dir_in.value}"
                                )
                                confirm_radio.set_value("cancel")
                                confirm_dialog.open()

                            clean_btn = (
                                ui.button(
                                    "Expire…",
                                    icon     = "delete_sweep",
                                    on_click = _open_confirm,
                                )
                                .classes(
                                    "bg-red-800 hover:bg-red-700 "
                                    "text-white self-end"
                                )
                            )

                        # ── clean progress & status ───────────────────────────
                        clean_prog = (
                            ui.linear_progress(value=0.0, size="8px")
                            .props("color=violet rounded")
                            .classes("w-full")
                        )
                        clean_prog.set_visibility(False)

                        clean_status = ui.label("").classes(
                            "text-xs font-mono text-slate-400"
                        )

                # ── storage auto-refresh ──────────────────────────────────────

                async def _refresh_storage() -> None:
                    """Read disk usage in thread pool; update bar in event loop."""
                    path = dir_in.value or "/data/astra"
                    used, total = await asyncio.to_thread(
                        _read_storage, path
                    )
                    fraction = (used / total) if (used and total) else None
                    color    = _bar_color(fraction)

                    usage_bar.set_value(fraction if fraction is not None else 0.0)
                    usage_bar.props(f"color={color} rounded")

                    usage_lbl.set_text(_bar_label(used, total, fraction, path))

                    used_lbl.set_text(
                        f"Used: {used:.1f} GB"  if used  is not None else "Used: —"
                    )
                    total_lbl.set_text(
                        f"Total: {total:.1f} GB" if total is not None else "Total: —"
                    )
                    free_lbl.set_text(
                        f"Free: {(total - used):.1f} GB"
                        if (used is not None and total is not None)
                        else "Free: —"
                    )

                # Initial read on page load + periodic refresh every 30 s
                ui.timer(0.1,  _refresh_storage, once=True)
                ui.timer(30.0, _refresh_storage)

            # ── save / reset row ──────────────────────────────────────────────
            with ui.row().classes("w-full justify-end gap-3 mt-2"):
                ui.button("Reset Defaults", icon="restart_alt") \
                    .props("outline").classes("text-slate-400")
                ui.button("Save Settings",  icon="save") \
                    .classes("bg-sky-600 hover:bg-sky-500 text-white")
                

            # ══════════════════════════════════════════════════════════════════
            # COMMAND MQTT SINK  (replaces per-page MQTT client)
            # ══════════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            ):
                with ui.column().classes("p-5 gap-4 w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("sensors").classes("text-emerald-400 text-xl")
                        ui.label("Telescope Motion Commands") \
                            .classes("font-semibold text-white text-base")
                    ui.label(
                        "The motion control commander is shared across all pages. "
                        "Reconfigure here to change the MQTT command broker or topic."
                    ).classes("text-xs text-slate-500")

                    with ui.row().classes("flex-wrap gap-4 items-end w-full"):
                        broker_in = (
                            ui.input(
                                "MQTT Broker Host",
                                value=astra_cmd.config.broker_host,
                            )
                            .props("dark dense").classes("min-w-44")
                        )
                        port_in = (
                            ui.number(
                                "Port",
                                value=astra_cmd.config.broker_port,
                                min=1, max=65535, format="%d",
                            )
                            .props("dark dense").classes("min-w-28")
                        )
                        topic_in = (
                            ui.input(
                                "Command Channel",
                                value=astra_cmd.config.topic,
                            )
                            .props("dark dense").classes("min-w-52")
                        )

                        async def _do_reconnect() -> None:
                            host  = broker_in.value  or "localhost"
                            port  = int(port_in.value or 1883)
                            topic = topic_in.value   or "astra/antenna/command"
                            await astra_cmd.configure(host, port, topic)
                            await astra_cmd.disconnect() # drop current connection
                            await astra_cmd.connect() # activate with new connection info

                            ui.notify(
                                f"Reconnecting to MQTT commands @ → "
                                f"{host}:{port}  {topic}",
                                type="positive", position="top-right",
                            )

                        ui.button("Reconnect", icon="wifi",
                                  on_click=_do_reconnect) \
                            .classes(
                                "bg-emerald-700 hover:bg-emerald-600 text-white"
                            )


            # ══════════════════════════════════════════════════════════════════
            # TELEMETRY MQTT CHANNEL  (replaces per-page MQTT client)
            # ══════════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            ):
                with ui.column().classes("p-5 gap-4 w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("sensors").classes("text-emerald-400 text-xl")
                        ui.label("Telescope Motion Telemetry Source") \
                            .classes("font-semibold text-white text-base")
                    ui.label(
                        "The motion control subscriber is shared across all pages. "
                        "Reconfigure here to change the MQTT broker or topic."
                    ).classes("text-xs text-slate-500")

                    with ui.row().classes("flex-wrap gap-4 items-end w-full"):
                        broker_in = (
                            ui.input(
                                "MQTT Broker Host",
                                value=astra_sub.config.broker_host,
                            )
                            .props("dark dense").classes("min-w-44")
                        )
                        port_in = (
                            ui.number(
                                "Port",
                                value=astra_sub.config.broker_port,
                                min=1, max=65535, format="%d",
                            )
                            .props("dark dense").classes("min-w-28")
                        )
                        topic_in = (
                            ui.input(
                                "Telemetry Channel",
                                value=astra_sub.config.topic,
                            )
                            .props("dark dense").classes("min-w-52")
                        )

                        async def _do_reconnect() -> None:
                            host  = broker_in.value  or "localhost"
                            port  = int(port_in.value or 1883)
                            topic = topic_in.value   or "astra/antenna/telemetry/#"
                            await astra_sub.configure(host, port, topic)
                            await astra_sub.disconnect() # drop current connection
                            await astra_sub.connect() # activate with new connection info

                            ui.notify(
                                f"Reconnecting to MQTT telemetry @ → "
                                f"{host}:{port}  {topic}",
                                type="positive", position="top-right",
                            )

                        ui.button("Reconnect", icon="wifi",
                                  on_click=_do_reconnect) \
                            .classes(
                                "bg-emerald-700 hover:bg-emerald-600 text-white"
                            )
