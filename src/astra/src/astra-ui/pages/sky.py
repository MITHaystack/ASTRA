"""
Sky View page for ASTRA — with interactive object selection.

Pointing source
---------------
Az/Alt direction is read from ``astra.state.pointing`` — a global singleton
updated by ``astra.mqtt.pointing.PointingSubscriber`` which runs as a
single persistent aiomqtt task shared across all browser sessions.
The per-page MQTT client that was previously embedded here has been removed.

Click behaviour
---------------
Left-click  : find nearest sky object → highlight with SVG crosshair
Right-click : context menu with Goto / Track / Sync / Stop Motion commands
              that publish JSON to astra/motion/command via the antenna commander
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, UTC, timezone
from typing import Optional
from pathlib import Path

from fastapi.responses import Response as HTTPResponse
from nicegui import app, ui

from .. theme import frame
from .. state import astra_state, astra_sub, astra_cmd
from astradata.objects import *

from .. sky.renderer import SkyConfig, FullSkyRenderer
from .. sky.catalog import SkyObject, SkyCatalog
from .. sky.catalog import SkyObject
from .. sky.projection import format_ra, format_dec

# ── module-level singletons ───────────────────────────────────────────────────
_STATIC_DIR  = str(Path(__file__).parent.parent / "static" / "sky")
_sky_cfg     = SkyConfig()
_renderer    = FullSkyRenderer(_sky_cfg, _STATIC_DIR)
_catalog = SkyCatalog()

# Shared catalog — rebuilt after each render
_catalog_state: dict = {
    "objects":       [],
    "render_count":  -1,
    "building":      False,
}


# ── coordinate helpers ────────────────────────────────────────────────────────

def _deg_to_hms(degrees):
    """Converts decimal degrees to hours, minutes, and seconds."""
    # 15 degrees = 1 hour
    hours_decimal = degrees / 15.0
    
    hours = int(hours_decimal)
    
    minutes_decimal = (hours_decimal - hours) * 60.0
    minutes = int(minutes_decimal)
    
    seconds = (minutes_decimal - minutes) * 60.0
    
    return hours, minutes, seconds

# ── projection helpers ────────────────────────────────────────────────────────
# Azimuthal equidistant, zenith-centred.
# Works in the same pixel space as ui.interactive_image event coordinates
# (i.e. the natural pixel resolution of the rendered PNG).

def _altaz_to_norm_pixel(az_d, alt_d, cx=0.5, cy=0.5, mxr=0.45):

        az_r = np.deg2rad(az_d)
        alt_r = np.deg2rad(alt_d)

        zd = (np.pi / 2.0) - alt_r

        if zd > (np.pi / 2.0):
            return None, None

        r = mxr * np.tan(zd / 2.0)
        x = cx + r * np.sin(az_r)
        y = cy - r * np.cos(az_r)

        return 1.0-x, y

def _altaz_to_pixel(az: float, alt: float, res: int, scale:float) -> tuple[float, float]:

    px, py = _altaz_to_norm_pixel(az, alt)

    px *= res * scale
    py *= res * scale

    # """(az_deg, alt_deg) → image pixel.  Inverse of _pixel_to_altaz."""
    # R_h = res * scale * 0.45 # horizon radius
    # cx = cy = res / 2.0
    # r = R_h * (90.0 - alt) / 90.0
    # # 0 = North / up , 90 deg = West / right
    # az_rad = math.radians(90.0 - az)
    # px     = cx + r * math.cos(az_rad)
    # py     = cy - r * math.sin(az_rad)
    return round(px), round(py)


# ── SVG cursor overlay ────────────────────────────────────────────────────────

def _selection_svg(obj: SkyObject, res: int, scale: float) -> str:
    """Dashed circle + crosshair + text labels at the object's pixel position."""
    px, py = obj.px, obj.py

    if px is None or py is None:
        return

    px = px * res * scale
    py = py * res * scale

    #print(f"select point is {px} {py}")

    r    = max(14.0, res * 0.009)
    gap  = r
    arm  = r * 1.8
    sw   = max(1.5, res * 0.001)
    fsz  = max(14.0, res * 0.010)
    fsz2 = fsz * 0.75
    tx   = px + r + res * 0.005

    name = obj.name
    if obj.az > 180.0:
        adj_az = obj.az - 360.0
    else:
        adj_az = obj.az
    info_parts = [obj.obj_type, f"Az {adj_az:.1f}°", f"Alt {obj.alt:.1f}°"]
    if obj.magnitude is not None:
        info_parts.append(f"mag {obj.magnitude:.1f}")
    info   = "  ·  ".join(info_parts)
    coords = f"{format_ra(obj.ra_deg)}  {format_dec(obj.dec_deg)}"

    name_w = len(name)  * fsz  * 0.60 + 16
    info_w = max(len(info), len(coords)) * fsz2 * 0.60 + 14
    bg_w   = max(name_w, info_w)
    bg_y0  = py - r - fsz * 1.2
    lh     = fsz * 1.15
    l2y    = bg_y0 + lh
    l3y    = l2y + fsz2 * 1.15

    return f"""
<g id="sel">
  <circle cx="{px:.1f}" cy="{py:.1f}" r="{r:.1f}"
          stroke="#22d3ee" stroke-width="{sw:.1f}" fill="none"
          stroke-dasharray="{r*0.5:.1f} {r*0.25:.1f}" opacity="0.92"/>
  <line x1="{px-gap-arm:.1f}" y1="{py:.1f}"
        x2="{px-gap:.1f}"     y2="{py:.1f}"
        stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
  <line x1="{px+gap:.1f}"     y1="{py:.1f}"
        x2="{px+gap+arm:.1f}" y2="{py:.1f}"
        stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
  <line x1="{px:.1f}" y1="{py-gap-arm:.1f}"
        x2="{px:.1f}" y2="{py-gap:.1f}"
        stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
  <line x1="{px:.1f}" y1="{py+gap:.1f}"
        x2="{px:.1f}" y2="{py+gap+arm:.1f}"
        stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
  <rect x="{tx-4:.1f}" y="{bg_y0:.1f}" width="{bg_w:.1f}" height="{lh:.1f}"
        rx="4" fill="#020c18" opacity="0.82"/>
  <text x="{tx:.1f}" y="{bg_y0+fsz*0.85:.1f}"
        fill="#22d3ee" font-size="{fsz:.1f}" font-family="monospace"
        font-weight="700" stroke="#020c18" stroke-width="{sw*2:.1f}"
        paint-order="stroke">{name}</text>
  <rect x="{tx-4:.1f}" y="{l2y:.1f}" width="{bg_w:.1f}" height="{fsz2*1.1:.1f}"
        rx="3" fill="#020c18" opacity="0.72"/>
  <text x="{tx:.1f}" y="{l2y+fsz2*0.85:.1f}"
        fill="#7dd3fc" font-size="{fsz2:.1f}"
        font-family="monospace">{info}</text>
  <rect x="{tx-4:.1f}" y="{l3y:.1f}" width="{bg_w:.1f}" height="{fsz2*1.1:.1f}"
        rx="3" fill="#020c18" opacity="0.65"/>
  <text x="{tx:.1f}" y="{l3y+fsz2*0.85:.1f}"
        fill="#64748b" font-size="{fsz2:.1f}"
        font-family="monospace">{coords}</text>
</g>"""



# motion helpers
async def _stop_cmd():
    cmd = AstraStopCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.azimuth = True
    cmd.altitude = True
    await astra_cmd.send(cmd,AstraStopCommand)

async def _send_goto_radec(target_ra_h, target_ra_m, target_ra_s, target_dec, az_rate, alt_rate, track=False):
    cmd = AstraSetTargetCommand()
    cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.target_type = 'radec'
    cmd.target_info = {
        'target_ra_h':target_ra_h,'target_ra_m':target_ra_m,'target_ra_s':target_ra_s,'target_dec':target_dec,'track':track
    }
    await astra_cmd.send(cmd,AstraSetTargetCommand)


async def _send_sync_command(sync_az, sync_alt, sync_values=True, sync_telemetry=False,sync_imu=False):
    cmd = AstraSyncCommand()
    timestamp       = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cmd.sync_az     = sync_az
    cmd.sync_alt    = sync_alt
    cmd.sync_values = sync_values
    cmd.sync_telemetry  = sync_telemetry
    cmd.sync_imu        = sync_imu
    cmd.imu_offset_az   : float = 0.0
    cmd.imu_offset_alt  : float = 0.0
    await astra_cmd.send(cmd,AstraSyncCommand)




# ── FastAPI endpoint ──────────────────────────────────────────────────────────

# @app.get("/sky/chart.png")
# def _sky_chart_endpoint() -> HTTPResponse:
#     return HTTPResponse(
#         content    = _renderer.get_png(),
#         media_type = "image/png",
#         headers    = {"Cache-Control": "no-cache, no-store, must-revalidate"},
#     )


# ── SVG crosshair overlay ─────────────────────────────────────────────────────

# def _selection_svg(obj: SkyObject, res: int) -> str:
#     px, py = obj.px, obj.py
#     r      = max(14.0, res * 0.012)
#     gap    = r
#     arm    = r * 1.7
#     sw     = max(2.0, res * 0.0012)
#     fsz    = max(18.0, res * 0.013)
#     fsz2   = fsz * 0.70
#     tx     = px + r + res * 0.007

#     name       = obj.name
#     info_parts = [obj.obj_type, f"Az {obj.az:.2f}°", f"Alt {obj.alt:.2f}°"]
#     if obj.magnitude is not None:
#         info_parts.append(f"mag {obj.magnitude:.1f}")
#     info   = "  ·  ".join(info_parts)
#     coords = f"{format_ra(obj.ra_deg)}  {format_dec(obj.dec_deg)}"

#     name_w = len(name)  * fsz  * 0.60 + 16
#     info_w = max(len(info), len(coords)) * fsz2 * 0.60 + 14
#     bg_w   = max(name_w, info_w)
#     bg_y0  = py - r - fsz * 1.1
#     lh     = fsz * 1.12
#     l2y    = bg_y0 + lh
#     l3y    = l2y + fsz2 * 1.12

#     return f"""
# <g id="sky-sel">
#   <circle cx="{px:.1f}" cy="{py:.1f}" r="{r:.1f}"
#           stroke="#22d3ee" stroke-width="{sw:.1f}" fill="none"
#           stroke-dasharray="{r*0.55:.1f} {r*0.28:.1f}" opacity="0.92"/>
#   <line x1="{px-gap-arm:.1f}" y1="{py:.1f}" x2="{px-gap:.1f}"   y2="{py:.1f}"
#         stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
#   <line x1="{px+gap:.1f}"     y1="{py:.1f}" x2="{px+gap+arm:.1f}" y2="{py:.1f}"
#         stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
#   <line x1="{px:.1f}" y1="{py-gap-arm:.1f}" x2="{px:.1f}" y2="{py-gap:.1f}"
#         stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
#   <line x1="{px:.1f}" y1="{py+gap:.1f}"     x2="{px:.1f}" y2="{py+gap+arm:.1f}"
#         stroke="#22d3ee" stroke-width="{sw:.1f}" opacity="0.88"/>
#   <rect x="{tx-6:.1f}" y="{bg_y0:.1f}" width="{bg_w:.1f}" height="{lh:.1f}"
#         rx="5" fill="#020c18" opacity="0.82"/>
#   <text x="{tx:.1f}" y="{bg_y0+fsz*0.85:.1f}"
#         fill="#22d3ee" font-size="{fsz:.1f}" font-family="monospace"
#         font-weight="700" stroke="#020c18" stroke-width="{sw*2.5:.1f}"
#         paint-order="stroke">{name}</text>
#   <rect x="{tx-6:.1f}" y="{l2y:.1f}" width="{bg_w:.1f}" height="{fsz2*1.1:.1f}"
#         rx="4" fill="#020c18" opacity="0.72"/>
#   <text x="{tx:.1f}" y="{l2y+fsz2*0.85:.1f}"
#         fill="#7dd3fc" font-size="{fsz2:.1f}"
#         font-family="monospace">{info}</text>
#   <rect x="{tx-6:.1f}" y="{l3y:.1f}" width="{bg_w:.1f}" height="{fsz2*1.1:.1f}"
#         rx="4" fill="#020c18" opacity="0.65"/>
#   <text x="{tx:.1f}" y="{l3y+fsz2*0.85:.1f}"
#         fill="#64748b" font-size="{fsz2:.1f}"
#         font-family="monospace">{coords}</text>
# </g>"""


# ── UI helpers ────────────────────────────────────────────────────────────────

def _badge(icon_name: str, init: str,
           icon_cls: str = "text-slate-400") -> ui.label:
    with ui.row().classes(
        "items-center gap-1.5 bg-[#1e293b] border border-[#334155] "
        "rounded-lg px-3 py-1.5"
    ):
        ui.icon(icon_name).classes(f"text-sm {icon_cls}")
        return ui.label(init).classes("text-xs font-mono text-slate-300")


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

def _pointing_card(az: float, el: float):
    with ui.card().classes("bg-[#1e293b] border border-[#334155] rounded-xl"):
        with ui.column().classes("p-4 gap-3"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("explore").classes("text-sky-400 text-xl")
                ui.label("Current Pointing").classes("text-sm font-medium text-slate-400")
            with ui.row().classes("gap-8"):
                with ui.column().classes("gap-0"):
                    ui.label("Azimuth").classes("text-xs text-slate-500")
                    ui.label(f"{az:.2f}°").classes("text-3xl font-bold text-sky-300")
                with ui.column().classes("gap-0"):
                    ui.label("Elevation").classes("text-xs text-slate-500")
                    ui.label(f"{el:.2f}°").classes("text-3xl font-bold text-sky-300")
            ui.separator().classes("bg-slate-700")
            with ui.row().classes("gap-2 items-center"):
                ui.icon("location_on").classes("text-amber-400 text-sm")
                ui.label("Tracking: Cassiopeia A").classes("text-sm text-slate-300")

def _status_card(icon: str, label: str, value: str, color: str, subtitle: str = ""):
    with ui.card().classes(f"bg-[#1e293b] border border-[#334155] rounded-xl flex-1 min-w-48"):
        with ui.column().classes("p-4 gap-2"):
            with ui.row().classes("items-center gap-2"):
                ui.icon(icon).classes(f"text-2xl text-{color}-400")
                ui.label(label).classes("text-sm text-slate-400 font-medium")
            ui.label(value).classes("text-2xl font-bold text-white")
            if subtitle:
                ui.label(subtitle).classes("text-xs text-slate-500")


# ── page ──────────────────────────────────────────────────────────────────────

def create() -> None:

    @ui.page("/")
    def sky_page() -> None:

        # ui.add_head_html(
        #     '<script src="/static/three.min.js"></script>'
        # )

        # per-session state
        _ui_state = {
            "last_render_count":    -1,
            "last_completed_t":      datetime.now(UTC),
            "last_mqtt_render_t":    datetime.now(UTC),
            "last_render_t":         datetime.now(UTC).timestamp(),
            "last_control_change_t": datetime.now(UTC),
            "scene_ready":  False,
            "control_render_due":    True,
            "control_change_t":    0.0,
            "control_due":         False,
            "current_fov":         120.0,
        }

        _MQTT_RENDER_COOLDOWN = 60.0   # s between MQTT-triggered renders
        _CONTROL_DEBOUNCE     =  2.0   # s after last control change before render
        _AUTO_RENDER_INTERVAL = 300.0   # s for periodic auto-render

        _sel: dict = {"obj": None}     # currently selected SkyObject | None

        _AUTO_RENDER_INTERVAL = 600.0   # 10 min
        _CONTROL_DEBOUNCE     =   2.0   # s

        # Unique JS global key for this page session (avoids cross-tab pollution)
        _ctr_id = f"skyctr{id(_ui_state)}"

        with frame("ASTRA Sky View"):


            # ══════════════════════════════════════════════════════════════════
            # STATUS BADGES + RENDER CONTROLS
            # ══════════════════════════════════════════════════════════════════
            def _badge(ic: str, txt: str,
                       c: str = "text-slate-400") -> ui.label:
                with ui.row().classes(
                    "items-center gap-1 bg-[#1e293b] "
                    "border border-[#334155] rounded-lg px-2 py-1.5"
                ):
                    ui.icon(ic).classes(f"text-sm {c}")
                    return ui.label(txt).classes(
                        "text-xs font-mono text-slate-300"
                    )

            with ui.row().classes("w-full gap-1 flex-wrap items-center"):

                b_next   = _badge("update",   "Next: —",     "text-indigo-400")
                b_az     = _badge("explore",  "Az: —",       "text-sky-400")
                b_alt    = _badge("height",   "Alt: —",      "text-amber-400")
                b_cat    = _badge("list",     "Catalog: —",  "text-indigo-400")
                b_sel    = _badge("gps_fixed","Selected: —", "text-cyan-400")
               

                ui.space()
                render_btn = (
                    ui.button("↺  Render", icon="refresh")
                    .classes("bg-sky-700 hover:bg-sky-600 text-white text-sm")
                )
                render_spin = ui.spinner(size="sm", color="sky")
                render_spin.set_visibility(False)
                render_stat = ui.label("").classes(
                    "text-xs text-slate-500 italic"
                )

            # ══════════════════════════════════════════════════════════════════
            # SKY IMAGE CARD
            # ══════════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#020810] border border-[#334155] "
                "rounded-xl w-full overflow-hidden"
            ):
                # chart header bar
                with ui.row().classes(
                    "items-center gap-1 px-2 py-2 bg-[#1e293b] "
                    "border-b border-[#334155] flex-wrap"
                ):
                    ui.icon("nights_stay").classes("text-indigo-400 text-lg")
                    ui.label("Star Plot").classes(
                        "text-sm font-semibold text-slate-200"
                    )
                    ui.space()
                    with ui.row().classes("items-center gap-1.5"):
                        ui.icon("mouse").classes("text-slate-500 text-sm")
                        ui.label(
                            "Left-click: select object  ·  "
                            "Right-click: tracking commands  ·  "
                            "Double-click: deselect"
                        ).classes("text-xs text-slate-500 italic")

    # ── mouse handler ─────────────────────────────────────────────────

                def _handle_mouse(e) -> None:
                    """
                    Fires for mousedown and dblclick events.
                    e.type      : "mousedown" | "dblclick"
                    e.button    : 0=left, 1=middle, 2=right
                    e.image_x/y : pixel coordinates in the original image space
                    """
                    # Double-click → deselect

                    if e.type == "dblclick":
                        _deselect()
                        return

                    if e.type != "mousedown":
                        return

                    # check that we have a catalog
                    objects = _catalog_state["objects"]
                    if not objects:
                        if e.button == 0:
                            ui.notify(
                                "Catalog not ready — render the sky first",
                                type="info", position="top-right",
                            )
                        return

                    # Select nearest object in pixel space 
                    #print(f"fno call : {e.image_x} {e.image_y} {_sky_cfg.resolution} {_sky_cfg.scale}")
                    obj = _catalog.find_nearest_object(e.image_x,e.image_y,_sky_cfg.resolution,_sky_cfg.scale)

                    spx = (e.image_x / _sky_cfg.scale) / _sky_cfg.resolution
                    spy = (e.image_y / _sky_cfg.scale) / _sky_cfg.resolution

                    #print(f"image point is {e.image_x} {e.image_y} {spx} {spy} object point is {obj.px} {obj.py}")
                    if e.button == 0:       # left-click: select / deselect
                        if obj:
                            _select(obj)
                        else:
                            _deselect()

                    elif e.button == 2:     # right-click: select then let context
                        if obj:             # menu open (already updated above)
                            _select(obj)
                        # The ui.context_menu opens automatically on contextmenu
                        # event — labels were updated by _select() above

                #sky_img.on("mousedown", _handle_mouse)
                #sky_img.on("dblclick",  _handle_mouse)                

                # ── interactive image ─────────────────────────────────────────
                sky_img = (
                    ui.interactive_image(
                        source  = f"{_renderer.output_url}?t=0",
                        content = "",
                        events  = ["mousedown", "dblclick"],
                        cross   = False,
                        on_mouse = _handle_mouse
                    )
                    .classes("w-full cursor-crosshair")
                )

                ## add pointing layer
                pointing_layer = sky_img.add_layer()
                px,py = _altaz_to_pixel(0.0,0.0, _sky_cfg.resolution, _sky_cfg.scale)
                pointing_layer.content = f'<circle cx="{px}" cy="{py}" r="10" fill="green" opacity="0.5" />'


                # ── context menu (right-click, lives inside the image) ─────────
                with sky_img:
                    with ui.context_menu():
                        ctx_name   = ui.label("No object selected").classes(
                            "text-sm font-semibold text-white px-4 pt-3 pb-0.5"
                        )
                        ctx_info   = ui.label("").classes(
                            "text-[11px] text-slate-400 px-4 pb-1"
                        )
                        ctx_azel   = ui.label("").classes(
                            "text-[11px] font-mono text-sky-300 px-4 pb-1"
                        )
                        ctx_radec  = ui.label("").classes(
                            "text-[11px] font-mono text-amber-300 px-4 pb-2"
                        )
                        ui.separator()

                        async def _ctx_stop_cmd():

                            await _stop_cmd()
                            ui.notify("⏹ Stop Motion sent",
                                        type="info", position="top-right")

                        async def _ctx_goto_cmd(track=False):
                            obj = _sel["obj"]

                            print("ctx goto ", obj)
                            print(obj.name, obj.ra_deg, obj.dec_deg)

                            tgt_ra_h, tgt_ra_m, tgt_ra_s = _deg_to_hms(obj.ra_deg)
                            tgt_dec = obj.dec_deg
                            robj = await astra_state.antenna_state.get('mount-rate')

                            if obj is None:
                                ui.notify("Select an object first",
                                            type="warning", position="top-right")
                                return
                            
                            await _send_goto_radec(tgt_ra_h, tgt_ra_m, tgt_ra_s, tgt_dec, robj.az_rate, robj.alt_rate, track)
                        
                        async def _ctx_track_cmd():
                            await _ctx_goto_cmd(True)

                        # async def _ctx_sync_cmd():
                        #     obj = _sel["obj"]

                        #     if obj is None:
                        #         ui.notify("Select an object first",
                        #                     type="warning", position="top-right")
                        #         return

                        #     await _send_sync_object(obj)


                        with ui.menu_item("🎯  Goto",
                                          on_click=_ctx_goto_cmd):
                            ui.tooltip("Slew telescope to this object")
                        with ui.menu_item("🔭  Track",
                                          on_click=_ctx_track_cmd):
                            ui.tooltip("Track this object continuously")
                        #with ui.menu_item("⊙  Sync",
                        #                  on_click=_ctx_sync_cmd):
                        #    ui.tooltip("Sync pointing model to this object")
                        ui.separator()
                        with ui.menu_item("⏹  Stop Motion",
                                          on_click=_ctx_stop_cmd):
                            ui.tooltip("Halt all telescope motion")

                # ── selected-object info panel ─────────────────────────────────
                with ui.row().classes(
                    "items-start gap-4 flex-wrap "
                    "px-5 py-3 bg-[#0a0f1e] border-t border-[#334155]"
                ) as sel_panel:
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("gps_fixed").classes("text-cyan-400 text-sm")
                        ui.label("Selected:").classes(
                            "text-xs text-slate-500 font-medium"
                        )
                    sel_name = ui.label("—").classes(
                        "text-sm font-semibold text-cyan-300 font-mono"
                    )
                    sel_type = ui.label("").classes("text-xs text-slate-400")
                    ui.space()
                    with ui.row().classes("gap-2") as quick_row:
                        (
                            ui.button("Goto", icon="send",
                                      on_click=_ctx_goto_cmd)
                            .props("size=sm")
                            .classes("bg-indigo-700 hover:bg-indigo-600 "
                                     "text-white text-xs")
                        )
                        (
                            ui.button("Track", icon="radio_button_checked",
                                      on_click=_ctx_track_cmd)
                            .props("size=sm")
                            .classes("bg-emerald-700 hover:bg-emerald-600 "
                                     "text-white text-xs")
                        )
                        #(
                        #    ui.button("Sync", icon="sync",
                        #              on_click=_ctx_sync_cmd)
                        #    .props("size=sm")
                        #    .classes("bg-amber-700 hover:bg-amber-600 "
                        #             "text-white text-xs")
                        #)
                        (
                            ui.button("✕", on_click=lambda: _deselect())
                            .props("size=sm flat")
                            .classes("text-slate-400 text-xs")
                            .tooltip("Deselect")
                        )
                    sel_detail = ui.label("").classes(
                        "w-full text-xs text-slate-400 font-mono mt-1"
                    )
                sel_panel.set_visibility(False)



            # ══════════════════════════════════════════════════════════════════
            # DISPLAY CONTROLS
            # ══════════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            ):
                with ui.column().classes("p-5 gap-4 w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("tune").classes("text-indigo-400 text-xl")
                        ui.label("Display Controls") \
                            .classes("font-semibold text-white text-base")
                    with ui.row().classes("flex-wrap gap-8 items-start w-full"):
                        with ui.column().classes("gap-1 min-w-52"):
                            with ui.row().classes(
                                "items-center justify-between"
                            ):
                                ui.label("Limiting Magnitude").classes(
                                    "text-xs text-slate-400 font-medium"
                                )
                                mag_badge = ui.label(
                                    f"{_sky_cfg.limiting_magnitude:.1f}"
                                ).classes("text-xs font-mono text-sky-300")
                            mag_sld = (
                                ui.slider(
                                    min=1.0, max=8.0, step=0.5,
                                    value=_sky_cfg.limiting_magnitude,
                                )
                                .props("color=sky dense label")
                                .classes("w-full")
                            )
                            mag_sld.on(
                                "update:model-value",
                                lambda _: mag_badge.set_text(
                                    f"{mag_sld.value:.1f}"
                                ),
                            )
                        with ui.column().classes("gap-1 min-w-44"):
                            ui.label("Render Resolution").classes(
                                "text-xs text-slate-400 font-medium"
                            )
                            # Guard against stale resolution value
                            _RES_OPTS = {
                                1024: "1024 px (fast)",
                                1200: "1200 px",
                                1800: "1800 px",
                                2400: "2400 px",
                                3600: "3600 px  (quality)",
                                4800: "4800 px  (high)",
                            }
                            if _sky_cfg.resolution not in _RES_OPTS:
                                _sky_cfg.resolution = 1024
                            res_sel = ui.select(
                                _RES_OPTS,
                                value=_sky_cfg.resolution,
                            ).props("dark dense")

                    with ui.row().classes("flex-wrap gap-x-6 gap-y-2"):
                        ui.label("Overlays:").classes(
                            "text-xs text-slate-400 font-medium mr-1"
                        )
                        chk_con_lines  = ui.checkbox(
                            "Constellation Lines",
                            value=_sky_cfg.show_constellation_lines,
                        ).props("dark color=sky dense")
                        chk_con_labels = ui.checkbox(
                            "Constellation Labels",
                            value=_sky_cfg.show_constellation_labels,
                        ).props("dark color=sky dense")
                        chk_altaz      = ui.checkbox(
                            "Alt/Az Grid",
                            value=_sky_cfg.show_altaz_grid,
                        ).props("dark color=indigo dense")
                        chk_mw         = ui.checkbox(
                            "Milky Way",
                            value=_sky_cfg.show_milky_way,
                        ).props("dark color=amber dense")
                        chk_nebula     = ui.checkbox(
                            "Nebulae",
                            value=_sky_cfg.show_nebula,
                        ).props("dark color=emerald dense")
                        chk_clusters   = ui.checkbox(
                            "Open Clusters",
                            value=_sky_cfg.show_open_clusters,
                        ).props("dark color=emerald dense")

            # ══════════════════════════════════════════════════════════════════
            # RENDERING OVERLAY  (shown while starplot is working)
            # We can't overlay ui.scene but we can show a banner
            # ══════════════════════════════════════════════════════════════════
            render_overlay = ui.label(
                "⟳  Rendering sky chart — this takes 20-60 seconds …"
            ).classes(
                "w-full text-center text-sky-300 text-sm font-medium "
                "bg-[#0f1e30] border border-sky-700/40 rounded-xl px-4 py-4"
            )
            render_overlay.set_visibility(False)

            # ══════════════════════════════════════════════════════════════════
            # ACTIONS
            # ══════════════════════════════════════════════════════════════════

            async def _sync_config() -> None:
                loc = await astra_state.antenna_state.get('astra-location')
                _sky_cfg.lat         = float(loc.latitude  or 42.6)
                _sky_cfg.lon         = float(loc.longitude  or -71.5)
                _sky_cfg.elevation_m = float(loc.altitude or 131.0)
                _sky_cfg.use_current_time = True
                _sky_cfg.limiting_magnitude        = float(mag_sld.value)
                _sky_cfg.resolution                = int(res_sel.value)
                _sky_cfg.show_constellation_lines  = bool(chk_con_lines.value)
                _sky_cfg.show_constellation_labels = bool(chk_con_labels.value)
                _sky_cfg.show_altaz_grid           = bool(chk_altaz.value)
                _sky_cfg.show_milky_way            = bool(chk_mw.value)
                _sky_cfg.show_nebula               = bool(chk_nebula.value)
                _sky_cfg.show_open_clusters        = bool(chk_clusters.value)

            async def _kick_render() -> None:
                await _sync_config()
                render_btn.set_enabled(False)
                render_spin.set_visibility(True)
                render_overlay.set_visibility(True)
                render_stat.set_text("Rendering starplot image…")
                _renderer.render_async()

            render_btn.on_click(lambda: _kick_render())

            # Debounce control changes
            def _on_control_change(_=None) -> None:
                _ui_state["control_change_t"] = datetime.now(UTC).timestamp()
                _ui_state["control_due"]      = True

            mag_sld.on("change", _on_control_change)
            res_sel.on_value_change(_on_control_change)
            for cb in [chk_con_lines, chk_con_labels, chk_altaz,
                       chk_mw, chk_nebula, chk_clusters]:
                cb.on_value_change(_on_control_change)

            # ── selection helpers ─────────────────────────────────────────────

            def _select(obj: SkyObject) -> None:
                _sel["obj"] = obj
                sky_img.content = _selection_svg(obj, _sky_cfg.resolution, _sky_cfg.scale)
                mag_s = (f"  ·  mag {obj.magnitude:.1f}"
                         if obj.magnitude is not None else "")
                sel_name.set_text(obj.name)
                sel_type.set_text(f"{obj.obj_type}{mag_s}")
                if obj.az > 180.0:
                    adj_az = obj.az - 360.0
                else:
                    adj_az = obj.az
                sel_detail.set_text(
                    f"Az {adj_az:.3f}°  ·  Alt {obj.alt:.3f}°  ·  "
                    f"{format_ra(obj.ra_deg)}   {format_dec(obj.dec_deg)}"
                )
                sel_panel.set_visibility(True)
                b_sel.set_text(f"Selected: {obj.name}")
                # Update context menu labels (so they're ready before it opens)
                ctx_name.set_text(obj.name)
                ctx_info.set_text(
                    obj.obj_type + mag_s
                )
                ctx_azel.set_text(
                    f"Az {adj_az:.3f}°   Alt {obj.alt:.3f}°"
                )
                ctx_radec.set_text(
                    f"{format_ra(obj.ra_deg)}   {format_dec(obj.dec_deg)}"
                )
                ui.notify(
                    f"Selected: {obj.name}",
                    type="info", position="bottom-right", timeout=1500,
                )

            def _deselect() -> None:
                _sel["obj"] = None
                sky_img.content = ""
                sel_panel.set_visibility(False)
                sel_name.set_text("—")
                sel_detail.set_text("")
                sel_type.set_text("")
                b_sel.set_text("Selected: —")
                ctx_name.set_text("No object selected")
                ctx_info.set_text("")
                ctx_azel.set_text("")
                ctx_radec.set_text("")



            # ══════════════════════════════════════════════════════════════════
            # TIMERS
            # ══════════════════════════════════════════════════════════════════

            # Render on page load (short delay so the frame paints first)
            ui.timer(0.2, lambda: _kick_render(), once=True)

            # 10-minute auto-render
            ui.timer(_AUTO_RENDER_INTERVAL, lambda: _kick_render())

            # 1 Hz refresh: badges, render detection, catalog rebuild
            async def _refresh() -> None:
                now = datetime.now(UTC).timestamp()

                # ── pointing source ───────────────────────────────────────────
                pobj = await astra_state.antenna_state.get('astra-pointing')

                az = pobj.pointing_az
                alt = pobj.pointing_alt                 

                b_az.set_text(f"Az:  {az:.1f}°")
                b_alt.set_text(f"Alt: {alt:.1f}°")

                # --- update sky image layer to add highlight
                px,py = _altaz_to_pixel(az, alt, _sky_cfg.resolution, _sky_cfg.scale)
                #pointing_layer.content = f'<circle cx="{px}" cy="{py}" r="25" fill="#ffde34" opacity="0.5" />'

                pointing_layer.content = f'''
                    <!-- Horizontal Cross Line -->
                    <line x1="{px - 28}" y1="{py}" x2="{px + 28}" y2="{py}" stroke="green" stroke-width="4" />
                        
                    <!-- Vertical Cross Line -->
                    <line x1="{px}" y1="{py - 28}" x2="{px}" y2="{py + 28}" stroke="green" stroke-width="4" />

                    <!-- Center Target Circle -->
                    <circle cx="{px}" cy="{py}" r="16" fill="#24ff84" stroke="green" stroke-width="4" opacity="0.3" />
                        
                    <!-- Center Target Circle -->
                    <circle cx="{px}" cy="{py}" r="24" stroke="green" stroke-width="4" opacity="0.2" />
                '''

                # ── debounced control-change render ───────────────────────────
                if (_ui_state["control_due"]
                        and not _renderer.is_rendering
                        and (now - _ui_state["control_change_t"]) >= _CONTROL_DEBOUNCE):
                    _ui_state["control_due"] = False
                    await _kick_render()

                # ── next auto-render countdown ────────────────────────────────
                if not _renderer.is_rendering:
                    rem = max(0.0, _AUTO_RENDER_INTERVAL
                              - (now - _ui_state["last_render_t"]))
                    b_next.set_text(
                        f"Next: {rem/60:.0f}m" if rem >= 60
                        else f"Next: {rem:.0f}s"
                    )
                else:
                    b_next.set_text("Rendering…")

                render_spin.set_visibility(_renderer.is_rendering)
                render_overlay.set_visibility(_renderer.is_rendering)
                if _renderer.is_rendering:
                    render_btn.set_enabled(False)

                # ── new render complete ───────────────────────────────────────
                if _renderer.render_count > _ui_state["last_render_count"]:
                    _ui_state["last_render_count"] = _renderer.render_count
                    _ui_state["last_render_t"]     = now
                    render_btn.set_enabled(True)
                    render_spin.set_visibility(False)
                    render_overlay.set_visibility(False)
                    dur = _renderer.last_dur
                    render_stat.set_text(
                        f"#{_renderer.render_count}  ·  {dur:.1f}s"
                    )
                    # Cache-bust the image URL so the browser re-fetches
                    sky_img.set_source(
                        f"{_renderer.output_url}?t={int(now)}"
                    )
                    # Clear stale selection — objects moved since last render
                    _deselect()

                # ── catalog rebuild after each new render ─────────────────────
                if (
                    _renderer.render_count > _catalog_state["render_count"]
                    and not _catalog_state["building"]
                ):
                    _catalog_state["building"]     = True
                    _catalog_state["render_count"] = _renderer.render_count
                    b_cat.set_text("Catalog: building…")
                    objects = await _catalog.build(
                        lat                = _sky_cfg.lat,
                        lon                = _sky_cfg.lon,
                        elevation_m        = _sky_cfg.elevation_m,
                        use_current_time   = _sky_cfg.use_current_time,
                        manual_dt          = _sky_cfg.manual_dt,
                        limiting_magnitude = _sky_cfg.limiting_magnitude,
                    )
                    _catalog_state["objects"]  = objects
                    _catalog_state["building"] = False
                    b_cat.set_text(f"Catalog: {len(objects):,} objects")

            ui.timer(1.0, _refresh)


 
