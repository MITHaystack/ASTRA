"""
Spectrometer page — Analog Devices PlutoSDR via libiio.

Controls
--------
  URI input     → Pluto IP / USB address
  [Connect]     → open libiio context, configure AD9361
  [Disconnect]  → tear down IIO context
  Freq input    → centre frequency in MHz  + [Set] button
  Gain slider   → hardware gain 0–73 dB (live update on release)
  Sample rate   → select box (common MSPS options)
  Advanced ▶    → FFT size, integration time, waterfall rows
  Calibration ▶ → calibrator mode, remove background, scale to cal
  [▶ Start]     → begin streaming + processing task
  [⏹ Stop]      → halt task
  [📷 Snapshot] → record IQ burst to DigitalRF in /data/rf/spectrogram/

Plots
-----
  PSD          : latest Welch-averaged spectrum  (dBFS/Hz vs MHz)
  Power vs Time: rolling total band power         (dBFS vs elapsed s)
  Waterfall    : scrolling time-frequency map     (dBFS/Hz, colour-coded)
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import plotly.graph_objects as go
from nicegui import ui

from .. theme import frame
from .. spectrometer.engine import (
    SpectrometerConfig,
    SpectrometerEngine,
    SAMPLE_RATES,
    _DRF_OK,
)

from .. state import astra_state, astra_sub, astra_cmd
from astradata.objects import *

# ── module-level singletons ───────────────────────────────────────────────────
_config = SpectrometerConfig()
_engine = SpectrometerEngine(_config)


# ── Plotly helpers ────────────────────────────────────────────────────────────

def _hex_to_rgba(h: str, a: float = 0.07) -> str:
    h = h.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


def _base_layout(**kw) -> dict:
    base = dict(
        template      = "plotly_dark",
        paper_bgcolor = "#1e293b",
        plot_bgcolor  = "#0f172a",
        font          = dict(color="#94a3b8", size=11),
        showlegend    = False,
        margin        = dict(l=58, r=18, t=14, b=46),
    )
    base.update(kw)
    return base


def _axis(title: str, **kw) -> dict:
    return dict(title=title, gridcolor="#334155", zerolinecolor="#475569", **kw)


def _make_psd(freqs: np.ndarray, psd: np.ndarray, psd_peak: np.ndarray, psd_avg: np.ndarray) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=freqs, y=psd,
        mode="lines",
        line=dict(color="#0ea5e9", width=1.2),
        fill="tozeroy",
        fillcolor=_hex_to_rgba("#0ea5e9", 0.07),
    ))
    fig.add_trace(go.Scatter(
        x=freqs, y=psd_peak,
        mode="lines",
        line=dict(color= "#777188", width=1.0),
        fill="tozeroy",
        fillcolor=_hex_to_rgba( "#777188", 0.07),
    ))
    fig.add_trace(go.Scatter(
        x=freqs, y=psd_avg,
        mode="lines",
        line=dict(color="#f59e0b", width=1.2),
        fill="tozeroy",
        fillcolor=_hex_to_rgba("#f59e0b", 0.07),
    ))
    fig.update_layout(
        **_base_layout(height=300),
        xaxis=_axis("Frequency (MHz)"),
        yaxis=_axis("Power (dBFS/Hz)"),
    )
    return fig


def _make_pvt(times: np.ndarray, power: np.ndarray) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=times, y=power,
        mode="lines",
        line=dict(color="#0ea5e9", width=1.2),
    ))
    fig.update_layout(
        **_base_layout(height=300),
        xaxis=_axis("Elapsed Time (s)"),
        yaxis=_axis("Band Power (dBFS)"),
    )
    return fig


def _make_waterfall(
    freqs: np.ndarray, elapsed: np.ndarray,
    wf: np.ndarray, colorscale: str = "Plasma"
) -> go.Figure:
    valid = wf[wf > -119.0]
    zmin  = float(np.percentile(valid,  5)) if valid.size else -100.0
    zmax  = float(np.percentile(valid, 99)) if valid.size else  -60.0
    fig   = go.Figure(go.Heatmap(
        z=wf, x=freqs, y=elapsed,
        colorscale=colorscale, zmin=zmin, zmax=zmax,
        colorbar=dict(
            title="dBFS/Hz", titleside="right", thickness=14,
            tickfont=dict(color="#94a3b8", size=10),
            titlefont=dict(color="#94a3b8", size=10),
        ),
    ))
    fig.update_layout(
        **_base_layout(height=400, margin=dict(l=58, r=82, t=14, b=46)),
        xaxis=_axis("Frequency (MHz)"),
        yaxis=_axis("Elapsed Time (s)"),
    )
    return fig


# ── page ──────────────────────────────────────────────────────────────────────

def create() -> None:

    @ui.page("/spectrometer")
    def spectrometer_page() -> None:

        _cs_state = {
            "value": "Plasma", 
            "snapshot": True, 
            "clear_plots": True,
            "subintegration_time" : 0.1,
            "integration_time" : 0.1,
            "psd_peak" : None,
            "psd_avg" : None,
            "psd_int_cnt" : 0

            }

        with frame("Radio Spectrometer"):

            # ══════════════════════════════════════════════════════════════════
            # STATUS BADGES
            # ══════════════════════════════════════════════════════════════════
            def _badge(icon_name: str, text: str, color: str) -> ui.label:
                with ui.row().classes(
                    "items-center gap-1 bg-[#1e293b] border border-[#334155] "
                    "rounded-lg px-3 py-1.5"
                ):
                    ui.icon(icon_name).classes(f"{color} text-sm")
                    return ui.label(text).classes(
                        "text-xs font-mono text-slate-300"
                    )

            with ui.column().classes("w-full gap-1 flex-wrap"):
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    m_conn  = _badge("power",              "SDR: —",           "text-sky-400")
                with ui.row().classes("w-full gap-1 flex-wrap"):                    
                    m_freq  = _badge("location_searching", "Peak: —",          "text-sky-400")
                    m_ppwr  = _badge("bolt",               "Peak: — dBFS/Hz",  "text-amber-400")
                    m_noise = _badge("noise_aware",        "Noise: — dBFS/Hz", "text-slate-400")
                    m_snr   = _badge("signal_cellular_alt","SNR: — dB",        "text-emerald-400")
                    m_df    = _badge("compress",           "Δf: — kHz",        "text-indigo-400")
                    m_tint  = _badge("timer",              "Tint: — s",        "text-rose-400")
                    m_cal   = _badge("science",            "Cal: off",         "text-violet-400")

            # ══════════════════════════════════════════════════════════════════
            # PSD  +  POWER-VS-TIME
            # ══════════════════════════════════════════════════════════════════
            with ui.row().classes("w-full gap-2"):
                with ui.card().classes(
                    "bg-[#1e293b] border border-[#334155] rounded-xl flex-1 min-w-0"
                ):
                    with ui.column().classes("p-2 gap-1 w-full"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("graphic_eq").classes("text-sky-400 text-lg")
                            ui.label("Power Spectral Density").classes(
                                "text-sm font-semibold text-slate-200"
                            )
                            ui.space()
                            ui.label("power  vs  frequency").classes(
                                "text-xs text-slate-500"
                            )
                        f0, p0 = _engine.get_psd()
                        psd_chart = ui.plotly(_make_psd(f0, p0, p0, p0)).classes("w-full")

                with ui.card().classes(
                    "bg-[#1e293b] border border-[#334155] rounded-xl flex-1 min-w-0"
                ):
                    with ui.column().classes("p-2 gap-1 w-full"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("show_chart").classes("text-amber-400 text-lg")
                            ui.label("Power vs Time").classes(
                                "text-sm font-semibold text-slate-200"
                            )
                            ui.space()
                            ui.label("total band power  vs  time").classes(
                                "text-xs text-slate-500"
                            )
                        t0, pv0 = _engine.get_power_vs_time()
                        pvt_chart = ui.plotly(_make_pvt(t0, pv0)).classes("w-full")

            # ══════════════════════════════════════════════════════════════════
            # WATERFALL
            # ══════════════════════════════════════════════════════════════════
            # with ui.card().classes(
            #     "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            # ):
            #     with ui.column().classes("p-4 gap-2 w-full"):
            #         with ui.row().classes("items-center gap-2"):
            #             ui.icon("gradient").classes("text-indigo-400 text-lg")
            #             ui.label("Waterfall").classes(
            #                 "text-sm font-semibold text-slate-200"
            #             )
            #             ui.space()
            #             ui.label("time × frequency  —  amplitude as colour").classes(
            #                 "text-xs text-slate-500"
            #             )
            #         fw0, el0, wf0 = _engine.get_waterfall()
            #         wf_chart = ui.plotly(
            #             _make_waterfall(fw0, el0, wf0)
            #         ).classes("w-full")

            # ══════════════════════════════════════════════════════════════════
            # LIVE REFRESH TIMER  (500 ms)
            # ══════════════════════════════════════════════════════════════════
            async def _refresh() -> None:


                async def _on_connect() -> None:
                    ok, msg = await _engine.connect(
                        "ip:192.168.2.1"
                    )

                    ui.notify(
                        msg,
                        type="positive" if ok else "negative",
                        position="top-right",
                    )

                if not _engine.is_connected:
                    await _on_connect()

                if not _engine.is_running:
                    _cs_state['clear_plots'] = True
                    return
                
                if _cs_state['snapshot']:
                    _cs_state['clear_plots'] = True
                    _cs_state['snapshot'] = False

                if _cs_state['clear_plots']:
                    _engine.clear_data()
                    psd_chart.data = []
                    pvt_chart.data = []
                    _cs_state['psd_peak'] = None
                    _cs_state['psd_avg'] = None
                    _cs_state['psd_int_cnt'] = 1
                    # wf_chart.data = []
                    _cs_state["clear_plots"] = False

                freqs, psd = _engine.get_psd()

                # check psd length, new length is a reset

                if((_cs_state['psd_peak'] is not None) and (_cs_state['psd_avg'] is not None)):
                    if (len(psd) != len(_cs_state['psd_peak'])
                        or (len(psd) != len(_cs_state['psd_avg']))
                        ):
                        _engine.clear_data()
                        psd_chart.data = []
                        pvt_chart.data = []
                        _cs_state['psd_peak'] = None
                        _cs_state['psd_avg'] = None
                        _cs_state['psd_int_cnt'] = 1

                # keep and compute a peak hold 
                if _cs_state['psd_peak'] is None:
                    _cs_state['psd_peak'] = psd
                else:
                    _cs_state['psd_peak'] = np.maximum(_cs_state['psd_peak'],psd)

                # moving average update, this way the display can update continously
                if _cs_state['psd_avg'] is None:
                    _cs_state['psd_avg'] = psd
                    _cs_state['psd_int_cnt'] = 1
                else:
                    if _cs_state['psd_int_cnt'] >= _cs_state['integration_time'] / _cs_state['subintegration_time']:
                        _cs_state['psd_avg'] = psd
                        _cs_state['psd_int_cnt'] = 1
                    else:
                        _cs_state['psd_avg'] = _cs_state['psd_avg'] + (psd - _cs_state['psd_avg'])/_cs_state['psd_int_cnt']
                        _cs_state['psd_int_cnt'] += 1
                
                psd_chart.figure["data"][0]["x"] = freqs
                psd_chart.figure["data"][0]["y"] = psd
                psd_chart.figure["data"][1]["x"] = freqs
                psd_chart.figure["data"][1]["y"] = _cs_state['psd_peak']
                psd_chart.figure["data"][2]["x"] = freqs
                psd_chart.figure["data"][2]["y"] = _cs_state['psd_avg']

                psd_chart.update()

                times, pvt = _engine.get_power_vs_time()
                pvt_chart.figure["data"][0]["x"] = times
                pvt_chart.figure["data"][0]["y"] = pvt
                pvt_chart.update()

                # f_wf, el_wf, wf = _engine.get_waterfall()
                # cs    = cs_sel.value
                # valid = wf[wf > -119.0]
                # zmin  = float(np.percentile(valid,  5)) if valid.size else -120.0
                # zmax  = float(np.percentile(valid, 99)) if valid.size else  -60.0
                # d = wf_chart.figure["data"][0]
                # d["z"] = wf; d["x"] = f_wf
                # d["y"] = el_wf
                # d["colorscale"] = cs; d["zmin"] = zmin; d["zmax"] = zmax
                # wf_chart.update()
                # _cs_state["value"] = cs
                # _cs_state["clear_plots"] = False

                # ── badges ────────────────────────────────────────────────────
                df_khz = (_config.sample_rate_MHz * 1e-3) / _config.fft_size
                pk_idx = int(np.argmax(psd))
                pk_pwr = float(psd[pk_idx])
                noise  = float(np.percentile(psd, 10))
                snr    = pk_pwr - noise

                m_conn .set_text(
                    f"SDR: ● {_config.pluto_uri}"
                )
                m_freq .set_text(f"Peak:  {freqs[pk_idx]:.4f} MHz")
                m_ppwr .set_text(f"Peak:  {pk_pwr:.1f} dBFS/Hz")
                m_noise.set_text(f"Noise: {noise:.1f} dBFS/Hz")
                m_snr  .set_text(f"SNR:   {snr:.1f} dB")
                m_df   .set_text(f"Δf:    {df_khz:.2f} kHz/bin")
                m_tint .set_text(f"Tsint:  {_config.subintegration_time:.3f} s")
                m_tint .set_text(f"Tint:  {_cs_state['integration_time']:.3f} s")
                m_cal  .set_text(f"Cal:   {cal_sel.value}")

            # ══════════════════════════════════════════════════════════════════
            # CONFIGURATION CARD
            # ══════════════════════════════════════════════════════════════════
            with ui.card().classes(
                "bg-[#1e293b] border border-[#334155] rounded-xl w-full"
            ):
                with ui.column().classes("p-2 gap-2 w-full"):

                    with ui.row().classes("items-center gap-2"):
                        ui.icon("radio").classes("text-sky-400 text-xl")
                        ui.label("Spectrometer Control") \
                            .classes("font-semibold text-white text-base")

                        dot   = ui.icon("circle").classes("text-slate-500 text-base")
                        d_lbl = ui.label("Stopped").classes(
                            "text-sm text-slate-400 w-20"
                        )
                        ui.space()

                        async def _start() -> None:
                            new_sr = int(sr_sel.value or 2)
                            if new_sr != _config.sample_rate_MHz:
                                await _engine.set_sample_rate(new_sr)

                            await _engine.update_config(
                                gain_db          = float(gain_sld.value),
                                fft_size         = int(fft_sel.value),
                            )
                            _cs_state['clear_plots'] = True
                            _engine.start()
                            dot.classes(
                                remove="text-slate-500 text-red-500",
                                add="text-emerald-400",
                            )
                            d_lbl.set_text("Running")

                        def _stop() -> None:
                            _engine.stop()
                            _cs_state['clear_plots'] = True
                            dot.classes(
                                remove="text-emerald-400 text-slate-500",
                                add="text-red-500",
                            )
                            d_lbl.set_text("Stopped")

                        snap_spinner = ui.spinner(size="sm", color="amber")
                        snap_spinner.set_visibility(False)

                        async def _on_snapshot() -> None:
                            dur = float(snap_dur_in.value or 5)
                            snap_btn.set_enabled(False)
                            snap_spinner.set_visibility(True)
                            d_lbl.set_text(f"Record for {dur} seconds")
                            ok, result = await _engine.take_snapshot(dur)
                            _cs_state['snapshot'] = True
                            _cs_state['clear_plots'] = True
                            snap_spinner.set_visibility(False)
                            snap_btn.set_enabled(True)
                            d_lbl.set_text(
                                "Running" if _engine.is_running else "Stopped"
                            )
                            if ok:
                                ui.notify(
                                    f"📷 Snapshot saved → {result}",
                                    type="positive",
                                    position="top-right",
                                    multi_line=True,
                                )
                            else:
                                ui.notify(
                                    f"Snapshot failed: {result}",
                                    type="negative",
                                    position="top-right",
                                )
                        ui.button("▶  Start", on_click=_start).classes(
                            "bg-emerald-600 hover:bg-emerald-500 text-white text-sm"
                        )
                        ui.button("⏹  Stop", on_click=_stop).classes(
                            "bg-red-700 hover:bg-red-600 text-white text-sm"
                        )

                        ui.separator().classes("bg-slate-700 w-px h-6 mx-1")

                        snap_dur_in = (
                            ui.number(
                                "Dur (s)", value=5.0,
                                min=1, max=600, step=1, format="%.0f",
                            )
                            .props("dark dense")
                            .classes("w-24")
                        )
                        snap_btn = (
                            ui.button(
                                "Snapshot",
                                icon="photo_camera",
                                on_click=_on_snapshot,
                            )
                            .classes(
                                "bg-amber-700 hover:bg-amber-600 text-white text-sm"
                            )
                        )
                        snap_spinner  # already declared above


                    # ── row 2: frequency + sample rate ────────────────────────
                    with ui.row().classes("flex-wrap gap-5 items-end w-full"):

                        # Frequency
                        with ui.column().classes("gap-1 min-w-52"):
                            ui.label("Center Frequency (MHz)").classes(
                                "text-xs text-slate-400 font-medium"
                            )
                            with ui.row().classes("items-end gap-2"):

                                async def _on_set_freq() -> None:
                                    MHz = int(float(freq_in.value or 1420.0))
                                    await _engine.set_frequency(MHz)
                                    _cs_state['clear_plots'] = True
                                freq_in = (
                                    ui.number(
                                        value=_config.center_freq_MHz,
                                        min=70, max=6000,
                                        step=0.1, format="%.3f",
                                        label="MHz",
                                        on_change = _on_set_freq,
                                    )
                                    .props("dark dense")
                                    .classes("min-w-40")
                                )

                        # Sample rate
                        with ui.column().classes("gap-1 min-w-52"):
                            ui.label("Sample Rate").classes(
                                "text-xs text-slate-400 font-medium"
                            )
                            async def _on_set_srate() -> None:
                                    MHz = int(float(sr_sel.value or 2.0))
                                    await _engine.set_sample_rate(MHz)
                                    _cs_state['clear_plots'] = True
                                    ui.notify(
                                        f"Sample Rate → {MHz:.3f} MSPS",
                                        type="positive", position="top-right",
                                    )

                            sr_sel = (
                                ui.select(
                                    SAMPLE_RATES,
                                    value=_config.sample_rate_MHz,
                                    label="Sample Rate",
                                    on_change=_on_set_srate,
                                )
                                .props("dark dense")
                                .classes("w-full")
                            )
                        async def _on_set_fft() -> None:
                            fft_bins = int(float(fft_sel.value or 1024))

                            await _engine.update_config(
                                fft_size         = int(fft_sel.value),
                            )                            
                            _cs_state['clear_plots'] = True
                            ui.notify(
                                f"FFT Bins → {fft_bins:.0f}",
                                type="positive", position="top-right",
                            )

                        fft_sel = (
                            ui.select(
                                {
                                    256:  "256 pts  (~390 kHz/bin @ 1 MHz SR)",
                                    512:  "512 pts  (~200 kHz/bin)",
                                    1024: "1024 pts (~100 kHz/bin)",
                                    2048: "2048 pts (~50 kHz/bin)",
                                    4096: "4096 pts (~24 kHz/bin)",
                                    8192: "8192 pts (~12 kHz/bin)",
                                },
                                value=_config.fft_size,
                                label="FFT Size / Spectral Resolution",
                                on_change=_on_set_fft,
                            )
                            .classes("min-w-72").props("dark dense")
                        )

                        async def _on_set_int() -> None:
                            int_time = float(int_in.value or 0.1)

                            _cs_state['integration_time'] = int_in.value
                            _cs_state['clear_data'] = True

                            ui.notify(
                                f"Integration Time → {int_time:.2f}",
                                type="positive", position="top-right",
                            )

                        int_in = (
                            ui.number(
                                "Integration Time (s)",
                                value=_cs_state['integration_time'],
                                min=0.01, max=60.0,
                                step=0.05, format="%.3f",
                                on_change = _on_set_int,
                            )
                            .classes("min-w-52").props("dark dense")
                        )

                        # ── row 3: gain slider ────────────────────────────────────
                        with ui.column().classes("gap-1 w-full"):
                            with ui.row().classes("items-center justify-between"):
                                ui.label("Hardware Gain  (0 – 73 dB)").classes(
                                    "text-xs text-slate-400 font-medium"
                                )
                                gain_badge = ui.label(
                                    f"{_config.gain_db:.0f} dB"
                                ).classes("text-xs font-mono text-indigo-300")

                            gain_sld = (
                                ui.slider(
                                    min=0, max=73,
                                    step=1, value=int(_config.gain_db),
                                )
                                .props("color=indigo dense label")
                                .classes("w-full")
                            )
                            gain_sld.on(
                                "update:model-value",
                                lambda _: gain_badge.set_text(
                                    f"{gain_sld.value:.0f} dB"
                                ),
                            )

                            async def _on_gain_change() -> None:
                                db = float(gain_sld.value or 50)
                                gain_badge.set_text(f"{db:.0f} dB")
                                await _engine.set_gain(db)
                                _cs_state['clear_plots'] = True
                            # Fire on release (not on every drag tick)
                            gain_sld.on("change", lambda _: asyncio.create_task(
                                _on_gain_change()
                            ))

                    ui.separator().classes("bg-slate-700/50")

                    # ── calibration ───────────────────────────────────────────
                    with ui.row().classes("flex-wrap gap-5 items-end w-full"):
                        with ui.column().classes("gap-1"):
                            ui.label("RF Calibrator").classes(
                                "text-xs text-slate-400 font-medium"
                            )
                            async def _on_calibrate() -> None:
                                cmd = AstraSetNoiseDiodeCommand()
                                cmd.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                                cmd.mode = cal_sel.value or "DISABLE"
                                await astra_cmd.send(cmd,AstraSetNoiseDiodeCommand,'astra/ai/command')

                                ui.notify(
                                    f"RF Calibrator {cal_sel.value}  ",
                                    type="positive", position="top-right",
                                )

                            cal_sel = (
                                ui.select(
                                    ["DISABLE", "ENABLE", "PULSE"],
                                    value="DISABLE",
                                    label="Mode",
                                    on_change=_on_calibrate,
                                )
                                .props("dark dense")
                                .classes("min-w-36")
                            )
                        with ui.column().classes("gap-1"):
                            ui.label("Remove Background").classes(
                                "text-xs text-slate-400 font-medium"
                            )
                            rm_bg_sel = (
                                ui.select(
                                    ["off", "on"],
                                    value="off",
                                    label="Mode",
                                )
                                .props("dark dense")
                                .classes("min-w-36")
                            )
                        with ui.column().classes("gap-1"):
                            ui.label("Scale to Calibration").classes(
                                "text-xs text-slate-400 font-medium"
                            )
                            scale_sel = (
                                ui.select(
                                    ["off", "on"],
                                    value="off",
                                    label="Mode",
                                )
                                .props("dark dense")
                                .classes("min-w-40")
                            )

                        ui.space()

                    ui.separator().classes("bg-slate-700/50")

            ui.timer(0.1, _refresh)