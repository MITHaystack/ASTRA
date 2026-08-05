"""
Camera page for ASTRA — QHY5III715C interface.

Layout
──────
 ┌─ Config & Controls card ───────────────────────────────────────────────────┐
 │  [Exposure slider+input]  [Gain slider+input]  [Offset slider+input]       │
 │  [Bit depth]  [Bayer]  [Scale]  [JPEG quality]  |  WB R/G/B               │
 │  [Connect]  [Snapshot]  [▶ Movie]  [⏹ Stop]  [Save JPEG]  [Save RAW]      │
 └────────────────────────────────────────────────────────────────────────────┘
 ┌─ Status badges ─────────────────────────────────────────────────────────────┐
 │  ● Connected   Mode: Streaming   FPS: 18.2   Frame #1234   1936×1096 16-bit│
 └────────────────────────────────────────────────────────────────────────────┘
 ┌─ Image display (2/3) ───────────────┐  ┌─ Histogram + Stats (1/3) ─────────┐
 │                                     │  │  [R/G/B histogram plotly chart]   │
 │  ui.interactive_image               │  │                                   │
 │  (live-updated via /camera/frame.jpg│  │  Min / Max / Mean / Std           │
 │   endpoint with cache-busting t=…)  │  │  Exposure / Gain / Offset         │
 │                                     │  │  Timestamp                        │
 └─────────────────────────────────────┘  └───────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, UTC, timezone
from typing import Optional

import numpy as np
import plotly.graph_objects as go
from fastapi.responses import Response as HTTPResponse
from nicegui import app, ui

from .. theme import frame
from .. camera.engine import CameraConfig, CameraEngine, FrameData

# ── module-level singleton ─────────────────────────────────────────────────────
_config = CameraConfig()
_engine = CameraEngine(_config)


# ── FastAPI endpoint: serves the latest JPEG frame ─────────────────────────────
@app.get("/camera/frame.jpg")
def _camera_frame_endpoint() -> HTTPResponse:
    """Serves the latest captured frame as JPEG (no caching)."""
    frm = _engine.get_latest_frame()
    if frm is not None:
        data = frm.jpeg_bytes
    else:
        data = _placeholder_jpeg()
    return HTTPResponse(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ── helpers ────────────────────────────────────────────────────────────────────

def _placeholder_jpeg() -> bytes:
    """1-pixel dark-navy JPEG used before the first frame is captured."""
    from PIL import Image
    img = Image.new("RGB", (640, 432), color=(10, 18, 36))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _base_layout(height: int, margin: dict | None = None) -> dict:
    m = margin or dict(l=46, r=14, t=12, b=36)
    return dict(
        template      = "plotly_dark",
        paper_bgcolor = "#1e293b",
        plot_bgcolor  = "#0f172a",
        font          = dict(color="#94a3b8", size=10),
        height        = height,
        margin        = m,
        showlegend    = True,
        legend        = dict(
            orientation = "h",
            y           = 1.14,
            font        = dict(size=9),
        ),
    )


def _make_hist_figure() -> go.Figure:
    x = list(range(128))
    fig = go.Figure()
    for colour, name in [
        ("#ef4444", "R"),
        ("#22c55e", "G"),
        ("#3b82f6", "B"),
    ]:
        fig.add_trace(go.Scatter(
            x         = x,
            y         = [0] * 128,
            mode      = "lines",
            line      = dict(color=colour, width=1.2),
            fill      = "tozeroy",
            fillcolor = _hex_to_rgba(colour, 0.13),   # ← was: colour.rstrip("f") + "22"
            name      = name,
        ))
    fig.update_layout(
        **_base_layout(220),
        xaxis = dict(title="Pixel value (0–255)", gridcolor="#334155"),
        yaxis = dict(title="Count",               gridcolor="#334155"),
    )
    return fig

def _stat_row(label: str, value_lbl: ui.label) -> None:
    with ui.row().classes("justify-between items-center w-full"):
        ui.label(label).classes("text-xs text-slate-500")
        value_lbl.classes("text-xs font-mono text-slate-200")

def _hex_to_rgba(hex_color: str, alpha: float = 0.13) -> str:
    """Convert a 6-digit hex colour string to rgba() notation for Plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

# ── slider + number linked pair ────────────────────────────────────────────────

def _param_control(
    label:    str,
    lo:       float,
    hi:       float,
    default:  float,
    step:     float = 1,
    fmt:      str   = "%.0f",
    color:    str   = "sky",
) -> ui.number:
    """Returns the number element; slider and number are bidirectionally bound."""
    with ui.column().classes("gap-1 min-w-52"):
        with ui.row().classes("items-center justify-between"):
            ui.label(label).classes("text-xs text-slate-400 font-medium")
        num = ui.number(
            min=lo, max=hi, value=default, step=step, format=fmt,
        ).props("dark dense").classes("w-full")
        sld = ui.slider(min=lo, max=hi, step=step, value=default) \
                .props(f"color={color} dense") \
                .classes("w-full")
        sld.bind_value(num)
        num.bind_value(sld)
    return num


# ── page ──────────────────────────────────────────────────────────────────────

def create() -> None:

    @ui.page("/camera")
    def camera_page() -> None:

        # ─ per-page mutable state ──────────────────────────────────────────────
        _state = {
            "last_frame_index": -1,
            "tick":             0,
            "snapshot_pending": False,
        }

        with frame("Camera"):

            # ══════════════════════════════════════════════════════════════════
            # CONFIGURATION CARD
            # ══════════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            ):
                with ui.column().classes("p-5 gap-5 w-full"):

                    with ui.row().classes("items-center gap-2"):
                        ui.icon("camera").classes("text-sky-400 text-xl")
                        ui.label("Camera Configuration & Controls") \
                            .classes("font-semibold text-white text-base")

                    # ── row 1: exposure / gain / offset ───────────────────────
                    with ui.row().classes("flex-wrap gap-6 items-start w-full"):

                        # Exposure in seconds → converted to µs on apply
                        exp_num = _param_control(
                            "Exposure (s)",
                            lo=0.001, hi=60.0,
                            default=_config.exposure_us / 1e6,
                            step=0.001, fmt="%.3f",
                            color="sky",
                        )

                        gain_num = _param_control(
                            "Gain",
                            lo=0, hi=256,
                            default=_config.gain,
                            color="indigo",
                        )

                        offset_num = _param_control(
                            "Offset  (Bias)",
                            lo=0, hi=255,
                            default=_config.offset,
                            color="amber",
                        )

                    # ── row 2: advanced ───────────────────────────────────────
                    with ui.expansion("Advanced  —  bit depth · Bayer · WB · display",
                                      icon="tune") \
                            .classes("w-full text-slate-400 text-sm"):
                        with ui.column().classes("p-2 gap-4"):

                            with ui.row().classes("flex-wrap gap-6 items-start"):
                                with ui.column().classes("gap-1 min-w-40"):
                                    ui.label("Bit Depth").classes("text-xs text-slate-400")
                                    bit_sel = ui.toggle(
                                        {8: "8-bit", 16: "16-bit"},
                                        value=_config.bit_depth,
                                    ).props("dense")

                                with ui.column().classes("gap-1 min-w-40"):
                                    ui.label("Bayer Pattern").classes("text-xs text-slate-400")
                                    bayer_sel = ui.select(
                                        ["RGGB", "BGGR", "GRBG", "GBRG"],
                                        value=_config.bayer_pattern,
                                    ).props("dark dense")

                                with ui.column().classes("gap-1 min-w-40"):
                                    ui.label("Display Scale").classes("text-xs text-slate-400")
                                    scale_sel = ui.select(
                                        {0.25: "¼ ×", 0.5: "½ ×", 1.0: "1 ×"},
                                        value=_config.display_scale,
                                    ).props("dark dense")

                                with ui.column().classes("gap-1 min-w-40"):
                                    ui.label("JPEG Quality").classes("text-xs text-slate-400")
                                    quality_num = ui.number(
                                        min=40, max=99, value=_config.jpeg_quality,
                                    ).props("dark dense")

                            # White-balance
                            ui.separator().classes("bg-slate-700 my-1")
                            ui.label("White Balance").classes(
                                "text-xs text-slate-400 font-medium"
                            )
                            with ui.row().classes("flex-wrap gap-6 items-start"):
                                wb_r = _param_control(
                                    "WB Red",   0.5, 3.0, _config.wb_r,
                                    step=0.01, fmt="%.2f", color="red",
                                )
                                wb_g = _param_control(
                                    "WB Green", 0.5, 3.0, _config.wb_g,
                                    step=0.01, fmt="%.2f", color="green",
                                )
                                wb_b = _param_control(
                                    "WB Blue",  0.5, 3.0, _config.wb_b,
                                    step=0.01, fmt="%.2f", color="blue",
                                )
                            ui.label(
                                "⚠  WB and display scale changes take effect on next "
                                "Apply or Start/Stop cycle."
                            ).classes("text-xs text-slate-500 italic")

                    # ── row 3: actions ────────────────────────────────────────
                    with ui.row().classes("flex-wrap gap-3 items-center"):

                        conn_btn  = ui.button("Connect",  icon="power")        \
                            .classes("bg-sky-700  hover:bg-sky-600  text-white")
                        snap_btn  = ui.button("Snapshot", icon="photo_camera") \
                            .classes("bg-indigo-700 hover:bg-indigo-600 text-white")
                        movie_btn = ui.button("▶  Movie", icon="videocam")     \
                            .classes("bg-emerald-700 hover:bg-emerald-600 text-white")
                        stop_btn  = ui.button("⏹  Stop",  icon="stop_circle")  \
                            .classes("bg-red-700 hover:bg-red-600 text-white")
                        save_j    = ui.button("Save JPEG", icon="image")        \
                            .props("outline").classes("text-slate-300")
                        save_r    = ui.button("Save RAW",  icon="save")         \
                            .props("outline").classes("text-slate-300")

                        snap_spinner = ui.spinner(size="sm", color="indigo") \
                            .classes("ml-1")
                        snap_spinner.set_visibility(False)

            # ══════════════════════════════════════════════════════════════════
            # STATUS BADGES
            # ══════════════════════════════════════════════════════════════════
            def _badge(icon_name: str, init_text: str,
                       icon_cls: str = "text-slate-400") -> ui.label:
                with ui.row().classes(
                    "items-center gap-1.5 bg-[#1e293b] border border-[#334155] "
                    "rounded-lg px-3 py-1.5"
                ):
                    ui.icon(icon_name).classes(f"text-sm {icon_cls}")
                    lbl = ui.label(init_text).classes(
                        "text-xs font-mono text-slate-300"
                    )
                return lbl

            with ui.row().classes("w-full gap-3 flex-wrap"):
                b_conn  = _badge("circle",           "Disconnected",     "text-slate-500")
                b_mode  = _badge("info",             "Idle",             "text-slate-400")
                b_fps   = _badge("speed",            "FPS: —",           "text-emerald-400")
                b_frame = _badge("filter_frames",    "Frame: —",         "text-indigo-400")
                b_size  = _badge("aspect_ratio",     "—",                "text-sky-400")
                b_src   = _badge("developer_board",  "Source: —",        "text-amber-400")

            # ══════════════════════════════════════════════════════════════════
            # MAIN CONTENT: Image display  |  Histogram + Stats
            # ══════════════════════════════════════════════════════════════════
            with ui.row().classes("w-full gap-4 items-start"):

                # ── Image display (left, ~2/3 width) ──────────────────────────
                with ui.card().classes(
                    "bg-[#0a0f1e] border border-[#334155] rounded-xl "
                    "flex-[2] min-w-0 overflow-hidden"
                ):                       
                    with ui.column().classes("p-0 gap-0 w-full"):
                        with ui.row().classes(
                            "items-center gap-2 px-4 py-2 bg-[#1e293b] "
                            "border-b border-[#334155]"
                        ):
                            ui.icon("image").classes("text-sky-400 text-lg")
                            ui.label("Live Frame") \
                                .classes("text-sm font-semibold text-slate-200")                        
                            
                        live_img = ui.interactive_image(
                            "/camera/frame.jpg",
                            on_mouse=lambda e: ui.notify(
                                f"x={e.image_x:.0f}  y={e.image_y:.0f}",
                                position="bottom-right",
                                timeout=1500,
                            ),
                            events=["mousedown"],
                            cross=True,
                        ).classes("w-full")

                        ui.button('Reload', on_click=live_img.force_reload)

                # ── Histogram + stats (right, ~1/3 width) ─────────────────────
                with ui.card().classes(
                    "bg-[#1e293b] border border-[#334155] rounded-xl "
                    "flex-[1] min-w-64"
                ):
                    with ui.column().classes("p-4 gap-4 w-full"):

                        # histogram
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("bar_chart").classes("text-indigo-400 text-lg")
                            ui.label("Pixel Histogram") \
                                .classes("text-sm font-semibold text-slate-200")
                        hist_chart = ui.plotly(_make_hist_figure()).classes("w-full")

                        ui.separator().classes("bg-slate-700")

                        # image stats
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("analytics").classes("text-amber-400 text-base")
                            ui.label("Frame Statistics") \
                                .classes("text-sm font-semibold text-slate-200")

                        with ui.column().classes("gap-1.5 w-full"):
                            s_min   = ui.label("—")
                            s_max   = ui.label("—")
                            s_mean  = ui.label("—")
                            s_std   = ui.label("—")
                            s_exp   = ui.label("—")
                            s_gain  = ui.label("—")
                            s_off   = ui.label("—")
                            s_ts    = ui.label("—")

                            with ui.grid(columns=2).classes("w-full gap-y-1"):
                                for lbl, val in [
                                    ("Min",       s_min),
                                    ("Max",       s_max),
                                    ("Mean",      s_mean),
                                    ("Std Dev",   s_std),
                                    ("Exposure",  s_exp),
                                    ("Gain",      s_gain),
                                    ("Offset",    s_off),
                                    ("Timestamp", s_ts),
                                ]:
                                    ui.label(lbl).classes("text-xs text-slate-500")
                                    val.classes("text-xs font-mono text-slate-200")

            # ══════════════════════════════════════════════════════════════════
            # CALLBACKS
            # ══════════════════════════════════════════════════════════════════

            def _sync_params() -> None:
                """Push current UI values into the engine config."""
                _engine.set_exposure(int(float(exp_num.value or 0.1) * 1e6))
                _engine.set_gain(int(gain_num.value or 0))
                _engine.set_offset(int(offset_num.value or 0))
                _engine.set_wb(
                    float(wb_r.value or 1.0),
                    float(wb_g.value or 1.0),
                    float(wb_b.value or 1.0),
                )
                _config.bayer_pattern  = bayer_sel.value
                _config.bit_depth      = int(bit_sel.value)
                _config.display_scale  = float(scale_sel.value)
                _config.jpeg_quality   = int(quality_num.value or 84)

            # Connect
            async def _on_connect() -> None:
                _sync_params()
                conn_btn.set_enabled(False)
                ok, msg = await _engine.connect()  
                conn_btn.set_enabled(True)
                if ok:
                    b_conn.set_text("Connected")
                    b_src.set_text(
                        "Simulation" if _config.use_simulation else "Hardware"
                    )
                    ui.notify(msg, type="positive", position="top-right")
                else:
                    b_conn.set_text("Failed")
                    ui.notify(msg, type="negative", position="top-right")

            conn_btn.on_click(_on_connect)

            # Snapshot
            async def _on_snapshot() -> None:
                if not _engine.is_connected:
                    ui.notify("Camera not connected", type="warning"); return
                if _engine.is_streaming:
                    ui.notify("Stop movie mode first", type="warning"); return
                _sync_params()
                _state["snapshot_pending"] = True
                snap_btn.set_enabled(False)
                snap_spinner.set_visibility(True)
                b_mode.set_text("Exposing…")

                frame_data = await _engine.capture_single()

                snap_spinner.set_visibility(False)
                snap_btn.set_enabled(True)
                _state["snapshot_pending"] = False

                if frame_data:
                    # cache-bust so browser re-fetches the new JPEG from the endpoint
                    live_img.set_source(f"/camera/frame.jpg?t={datetime.now(UTC).timestamp():.6f}")
                    _update_histogram(frame_data)
                    _update_stats(frame_data)
                    b_mode.set_text("Snapshot")
                    b_frame.set_text(f"Frame: #{frame_data.frame_index}")
                    b_size.set_text(
                        f"{frame_data.width}×{frame_data.height} {frame_data.bpp}-bit"
                    )
                    ui.notify("Snapshot captured", type="positive",
                              position="top-right")
                else:
                    b_mode.set_text("Error")
                    ui.notify("Capture failed", type="negative", position="top-right")

            snap_btn.on_click(_on_snapshot)

            # Start movie
            async def _on_movie() -> None:
                if not _engine.is_connected:
                    ui.notify("Camera not connected", type="warning"); return
                if _engine.is_streaming:
                    return
                _sync_params()
                ok, msg = await _engine.start_streaming()
                if ok:
                    b_mode.set_text("Streaming")
                    ui.notify(msg, type="positive", position="top-right")
                else:
                    ui.notify(msg, type="negative", position="top-right")

            movie_btn.on_click(_on_movie)

            # Stop movie / streaming
            async def _on_stop() -> None:
                await _engine.stop_streaming()
                b_mode.set_text("Idle")
                b_fps.set_text("FPS: —")
                ui.notify("Stopped", type="info", position="top-right")

            stop_btn.on_click(_on_stop)

            # Save JPEG
            def _on_save_jpeg() -> None:
                frm = _engine.get_latest_frame()
                if frm is None:
                    ui.notify("No frame captured yet", type="warning"); return
                ts  = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                ui.download(
                    frm.jpeg_bytes,
                    filename=f"astra_{ts}.jpg",
                    media_type="image/jpeg",
                )
                ui.notify("Downloading JPEG…", position="top-right")

            save_j.on_click(_on_save_jpeg)

            # Save RAW (numpy .npy)
            def _on_save_raw() -> None:
                frm = _engine.get_latest_frame()
                if frm is None:
                    ui.notify("No frame captured yet", type="warning"); return
                buf = io.BytesIO()
                np.save(buf, frm.raw)
                ts  = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                ui.download(
                    buf.getvalue(),
                    filename=f"astra_{ts}_raw.npy",
                    media_type="application/octet-stream",
                )
                ui.notify("Downloading RAW numpy array…", position="top-right")

            save_r.on_click(_on_save_raw)

            # ══════════════════════════════════════════════════════════════════
            # HISTOGRAM + STATS UPDATE HELPERS
            # ══════════════════════════════════════════════════════════════════

            def _update_histogram(frm: FrameData) -> None:
                rgb  = frm.rgb          # uint8 (H, W, 3)
                bins = 128
                rng  = (0, 255)
                for ch_idx in range(3):
                    h, _ = np.histogram(rgb[:, :, ch_idx], bins=bins, range=rng)
                    hist_chart.figure["data"][ch_idx]["y"] = h.tolist()
                hist_chart.update()

            def _update_stats(frm: FrameData) -> None:
                st = frm.stats
                s_min.set_text(f"{st['min']:.0f}")
                s_max.set_text(f"{st['max']:.0f}")
                s_mean.set_text(f"{st['mean']:.1f}")
                s_std.set_text(f"{st['std']:.1f}")
                s_exp.set_text(f"{_config.exposure_us / 1e3:.1f} ms")
                s_gain.set_text(str(_config.gain))
                s_off.set_text(str(_config.offset))
                s_ts.set_text(
                    datetime.now(UTC).isoformat().replace("+00:00", "Z")
                )

            # ══════════════════════════════════════════════════════════════════
            # LIVE REFRESH TIMER  (20 Hz for image, 5 Hz for heavy ops)
            # ══════════════════════════════════════════════════════════════════

            def _refresh() -> None:
                if _state["snapshot_pending"]:
                    return

                # ── connection status indicator ────────────────────────────
                if _engine.is_connected:
                    b_conn.set_text("Connected")
                else:
                    b_conn.set_text("Disconnected")
                    return

                # ── FPS badge ──────────────────────────────────────────────
                if _engine.is_streaming:
                    b_fps.set_text(f"FPS: {_engine.fps:.1f}")

                # ── image update: only when a new frame is available ────────
                frm = _engine.get_latest_frame()
                if frm is None:
                    return

                if frm.frame_index != _state["last_frame_index"]:
                    _state["last_frame_index"] = frm.frame_index

                    # update image via HTTP endpoint (cache-busting timestamp)
                    live_img.set_source(f"/camera/frame.jpg?t={datetime.now(UTC).timestamp():.6f}")

                    # badges
                    b_frame.set_text(f"Frame: #{frm.frame_index}")
                    b_size.set_text(
                        f"{frm.width}×{frm.height}  {frm.bpp}-bit"
                    )
                    b_src.set_text(
                        "Simulation" if _config.use_simulation else "Hardware"
                    )

                    # stats every tick; histogram every 4th tick (keep CPU low)
                    _state["tick"] = (_state["tick"] + 1) % 4
                    _update_stats(frm)
                    if _state["tick"] == 0:
                        _update_histogram(frm)

            ui.timer(1 / 20, _refresh)