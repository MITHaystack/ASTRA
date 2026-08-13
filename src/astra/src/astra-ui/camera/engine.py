"""
CameraEngine — asyncio edition
================================
Streaming runs as an asyncio.Task.
All blocking SDK calls run in asyncio.to_thread.
State mutations (self._latest_frame, self._fps) happen only in the
event loop after to_thread returns — no locks required.
"""

from __future__ import annotations

import asyncio
import ctypes
import io
import platform
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional
import time as _time

import numpy as np
from PIL import Image


# ── QHYCCD constants & control IDs ───────────────────────────────────────────

QHYCCD_SUCCESS      = 0x00000000
QHYCCD_ERROR        = 0xFFFFFFFF
QHYCCD_NO_NEW_FRAME = 0xE5012C2C


class CONTROL_ID(IntEnum):
    CONTROL_GAIN        = 6
    CONTROL_OFFSET      = 7
    CONTROL_EXPOSURE    = 8
    CONTROL_TRANSFERBIT = 10
    CONTROL_USBTRAFFIC  = 12
    CONTROL_WBR         = 2
    CONTROL_WBB         = 3
    CONTROL_WBG         = 4


# ── configuration ─────────────────────────────────────────────────────────────

@dataclass
class CameraConfig:
    exposure_us:      int   = 100_000
    gain:             int   = 10
    offset:           int   = 10
    bit_depth:        int   = 16
    usb_traffic:      int   = 40
    wb_r:             float = 1.0
    wb_g:             float = 1.0
    wb_b:             float = 1.0
    bayer_pattern:    str   = "RGGB"
    display_scale:    float = 1.0
    jpeg_quality:     int   = 84
    stream_fps_limit: float = 20.0
    use_simulation:   bool  = True


# ── frame payload ─────────────────────────────────────────────────────────────

@dataclass
class FrameData:
    raw:         np.ndarray
    rgb:         np.ndarray
    jpeg_bytes:  bytes
    width:       int
    height:      int
    bpp:         int
    timestamp:   float
    frame_index: int
    stats:       dict


# ── engine ────────────────────────────────────────────────────────────────────

class CameraEngine:

    SIM_W = 1936
    SIM_H = 1096

    def __init__(self, config: CameraConfig | None = None) -> None:
        self.config        = config or CameraConfig()
        self._lib:         Optional[ctypes.CDLL]     = None
        self._handle:      Optional[ctypes.c_void_p] = None
        self._mem_buf:     Optional[ctypes.Array]    = None
        self._cam_id_buf   = ctypes.create_string_buffer(64)

        self._connected    = False
        self._streaming    = False
        self._stream_task: Optional[asyncio.Task]    = None
        self._latest_frame: Optional[FrameData]      = None
        self._frame_index  = 0
        self._fps_times:   deque[float] = deque(maxlen=60)
        self._fps          = 0.0

        self._sim_stars    = _gen_sim_stars(n=90, seed=42)
        self._try_load_sdk()

    # ── SDK loader ────────────────────────────────────────────────────────────

    def _try_load_sdk(self) -> None:
        names: dict[str, list[str]] = {
            "Linux":   ["libqhyccd.so", "libqhyccd.so.23"],
            "Darwin":  ["libqhyccd.dylib"],
            "Windows": ["qhyccd.dll", "qhyccd64.dll"],
        }
        for name in names.get(platform.system(), []):
            try:
                lib = ctypes.CDLL(name)
                _setup_prototypes(lib)
                self._lib = lib
                self.config.use_simulation = False
                return
            except OSError:
                pass
        self.config.use_simulation = True

    # ── public state ──────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def frame_index(self) -> int:
        return self._frame_index

    def get_latest_frame(self) -> Optional[FrameData]:
        return self._latest_frame

    # ── connection ────────────────────────────────────────────────────────────

    async def connect(self) -> tuple[bool, str]:
        if self.config.use_simulation:
            self._connected = True
            return True, "Connected to simulated QHY5III715C (SDK not found)"
        ok, msg = await asyncio.to_thread(self._hw_connect)
        if ok:
            self._connected = True
        return ok, msg

    def _hw_connect(self) -> tuple[bool, str]:
        """Blocking SDK initialisation — runs in thread pool."""
        try:
            if self._lib.InitQHYCCDResource() != QHYCCD_SUCCESS:
                return False, "InitQHYCCDResource() failed"
            n = self._lib.ScanQHYCCD()
            if n == 0:
                return False, "No QHY cameras detected"
            self._lib.GetQHYCCDId(0, self._cam_id_buf)
            handle = self._lib.OpenQHYCCD(self._cam_id_buf)
            if not handle:
                return False, "OpenQHYCCD() returned null"
            self._handle = handle
            self._lib.SetQHYCCDStreamMode(handle, 0)
            self._lib.InitQHYCCD(handle)
            self._lib.SetQHYCCDResolution(handle, 0, 0, self.SIM_W, self.SIM_H)
            self._hw_apply_params()
            mem = self._lib.GetQHYCCDMemLength(handle)
            self._mem_buf = ctypes.create_string_buffer(mem)
            return True, f"Connected: {self._cam_id_buf.value.decode()}"
        except Exception as exc:
            return False, f"connect() error: {exc}"

    async def disconnect(self) -> None:
        if self._streaming:
            await self.stop_streaming()
        if self._handle and not self.config.use_simulation:
            await asyncio.to_thread(self._hw_disconnect)
        self._handle    = None
        self._connected = False

    def _hw_disconnect(self) -> None:
        try:
            self._lib.CloseQHYCCD(self._handle)
            self._lib.ReleaseQHYCCDResource()
        except Exception:
            pass

    # ── parameter setters ─────────────────────────────────────────────────────

    def _hw_apply_params(self) -> None:
        if self.config.use_simulation or not self._handle:
            return
        c  = self.config
        fn = self._lib.SetQHYCCDParam
        h  = self._handle
        self._lib.SetQHYCCDBitsMode(h, c.bit_depth)
        fn(h, CONTROL_ID.CONTROL_EXPOSURE,   float(c.exposure_us))
        fn(h, CONTROL_ID.CONTROL_GAIN,       float(c.gain))
        fn(h, CONTROL_ID.CONTROL_OFFSET,     float(c.offset))
        fn(h, CONTROL_ID.CONTROL_USBTRAFFIC, float(c.usb_traffic))
        fn(h, CONTROL_ID.CONTROL_WBR,        c.wb_r)
        fn(h, CONTROL_ID.CONTROL_WBG,        c.wb_g)
        fn(h, CONTROL_ID.CONTROL_WBB,        c.wb_b)

    def set_exposure(self, us: int) -> None:
        self.config.exposure_us = int(us)
        if not self.config.use_simulation and self._handle:
            self._lib.SetQHYCCDParam(self._handle, CONTROL_ID.CONTROL_EXPOSURE, float(us))

    def set_gain(self, v: int) -> None:
        self.config.gain = int(v)
        if not self.config.use_simulation and self._handle:
            self._lib.SetQHYCCDParam(self._handle, CONTROL_ID.CONTROL_GAIN, float(v))

    def set_offset(self, v: int) -> None:
        self.config.offset = int(v)
        if not self.config.use_simulation and self._handle:
            self._lib.SetQHYCCDParam(self._handle, CONTROL_ID.CONTROL_OFFSET, float(v))

    def set_wb(self, r: float, g: float, b: float) -> None:
        self.config.wb_r, self.config.wb_g, self.config.wb_b = r, g, b
        if not self.config.use_simulation and self._handle:
            fn = self._lib.SetQHYCCDParam
            h  = self._handle
            fn(h, CONTROL_ID.CONTROL_WBR, r)
            fn(h, CONTROL_ID.CONTROL_WBG, g)
            fn(h, CONTROL_ID.CONTROL_WBB, b)

    # ── single-frame snapshot ─────────────────────────────────────────────────

    async def capture_single(self) -> Optional[FrameData]:
        """Non-blocking snapshot — SDK/simulation runs in thread pool."""
        if not self._connected:
            return None
        fn  = self._simulate_frame if self.config.use_simulation else self._hw_single
        raw = await asyncio.to_thread(fn)
        if raw is None:
            return None
        frame = await asyncio.to_thread(self._process, raw)
        self._latest_frame = frame          # assignment in event loop
        return frame

    def _hw_single(self) -> Optional[np.ndarray]:
        try:
            if self._lib.ExpQHYCCDSingleFrame(self._handle) != QHYCCD_SUCCESS:
                return None
            w, h, bpp, ch = (ctypes.c_uint32() for _ in range(4))
            ret = self._lib.GetQHYCCDSingleFrame(
                self._handle,
                ctypes.byref(w), ctypes.byref(h),
                ctypes.byref(bpp), ctypes.byref(ch),
                self._mem_buf,
            )
            if ret != QHYCCD_SUCCESS:
                return None
            wv, hv, bv = w.value, h.value, bpp.value
            dtype = np.uint16 if bv == 16 else np.uint8
            return (np.frombuffer(self._mem_buf.raw[: wv * hv * (bv // 8)], dtype=dtype)
                      .reshape(hv, wv).copy())
        except Exception as exc:
            print(f"[camera] _hw_single error: {exc}")
            return None

    # ── streaming ─────────────────────────────────────────────────────────────

    async def start_streaming(self) -> tuple[bool, str]:
        if not self._connected:
            return False, "Not connected"
        if self._stream_task and not self._stream_task.done():
            return True, "Already streaming"

        if not self.config.use_simulation:
            ok = await asyncio.to_thread(self._hw_begin_live)
            if not ok:
                return False, "BeginQHYCCDLive() failed"

        self._streaming = True
        self._fps_times.clear()
        self._stream_task = asyncio.create_task(
            self._stream_loop(), name="camera-stream"
        )
        return True, "Streaming"

    def _hw_begin_live(self) -> bool:
        """Switch SDK to live mode — blocking, runs in thread pool."""
        try:
            if self._handle:
                self._lib.CloseQHYCCD(self._handle)
            h = self._lib.OpenQHYCCD(self._cam_id_buf)
            self._lib.SetQHYCCDStreamMode(h, 1)
            self._lib.InitQHYCCD(h)
            self._lib.SetQHYCCDResolution(h, 0, 0, self.SIM_W, self.SIM_H)
            self._handle = h
            self._hw_apply_params()
            self._mem_buf = ctypes.create_string_buffer(
                self._lib.GetQHYCCDMemLength(h)
            )
            return self._lib.BeginQHYCCDLive(h) == QHYCCD_SUCCESS
        except Exception as exc:
            print(f"[camera] _hw_begin_live error: {exc}")
            return False

    async def stop_streaming(self) -> None:
        self._streaming = False
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        self._stream_task = None
        if not self.config.use_simulation and self._handle:
            await asyncio.to_thread(self._hw_stop_live)

    def _hw_stop_live(self) -> None:
        try:
            self._lib.StopQHYCCDLive(self._handle)
            self._lib.CloseQHYCCD(self._handle)
            h = self._lib.OpenQHYCCD(self._cam_id_buf)
            self._lib.SetQHYCCDStreamMode(h, 0)
            self._lib.InitQHYCCD(h)
            self._lib.SetQHYCCDResolution(h, 0, 0, self.SIM_W, self.SIM_H)
            self._handle  = h
            self._hw_apply_params()
            self._mem_buf = ctypes.create_string_buffer(
                self._lib.GetQHYCCDMemLength(h)
            )
        except Exception as exc:
            print(f"[camera] _hw_stop_live error: {exc}")

    async def _stream_loop(self) -> None:
        """Async streaming task — frame acquisition and processing in thread pool."""
        loop     = asyncio.get_running_loop()
        interval = 1.0 / max(1.0, self.config.stream_fps_limit)
        try:
            while self._streaming:
                t0  = loop.time()
                fn  = (self._simulate_frame
                       if self.config.use_simulation
                       else self._hw_live)
                raw = await asyncio.to_thread(fn)
                if raw is not None:
                    frame = await asyncio.to_thread(self._process, raw)
                    # State mutations in event loop — no lock needed
                    self._latest_frame = frame
                    now = loop.time()
                    self._fps_times.append(now)
                    if len(self._fps_times) >= 2:
                        self._fps = ((len(self._fps_times) - 1) /
                                     (self._fps_times[-1] - self._fps_times[0]))
                elapsed = loop.time() - t0
                await asyncio.sleep(max(0.0, interval - elapsed))
        except asyncio.CancelledError:
            pass

    def _hw_live(self) -> Optional[np.ndarray]:
        try:
            w, h, bpp, ch = (ctypes.c_uint32() for _ in range(4))
            ret = self._lib.GetQHYCCDLiveFrame(
                self._handle,
                ctypes.byref(w), ctypes.byref(h),
                ctypes.byref(bpp), ctypes.byref(ch),
                self._mem_buf,
            )
            if ret in (QHYCCD_NO_NEW_FRAME, QHYCCD_ERROR):
                return None
            wv, hv, bv = w.value, h.value, bpp.value
            dtype = np.uint16 if bv == 16 else np.uint8
            return (np.frombuffer(self._mem_buf.raw[: wv * hv * (bv // 8)], dtype=dtype)
                      .reshape(hv, wv).copy())
        except Exception as exc:
            print(f"[camera] _hw_live error: {exc}")
            return None

    # ── image processing pipeline (runs in thread pool) ───────────────────────

    def _process(self, raw: np.ndarray) -> FrameData:
        h, w  = raw.shape
        bpp   = 16 if raw.dtype == np.uint16 else 8
        stretched = _auto_stretch(raw)
        rgb_half  = _debayer(stretched, self.config.bayer_pattern)
        rgb_wb    = _apply_wb(rgb_half, self.config.wb_r,
                              self.config.wb_g, self.config.wb_b)
        sc = self.config.display_scale
        if sc != 1.0:
            dw     = max(1, int(rgb_wb.shape[1] * sc))
            dh     = max(1, int(rgb_wb.shape[0] * sc))
            rgb_d  = np.array(Image.fromarray(rgb_wb).resize(
                (dw, dh), Image.LANCZOS), dtype=np.uint8)
        else:
            rgb_d = rgb_wb
        buf = io.BytesIO()
        Image.fromarray(rgb_d).save(buf, format="JPEG",
                                     quality=self.config.jpeg_quality)
        self._frame_index += 1
        return FrameData(
            raw=raw, rgb=rgb_d, jpeg_bytes=buf.getvalue(),
            width=w, height=h, bpp=bpp,
            timestamp=_time.time(), frame_index=self._frame_index,
            stats=_compute_stats(raw, bpp),
        )

    # ── simulation (runs in thread pool) ─────────────────────────────────────

    def _simulate_frame(self) -> np.ndarray:
        cfg     = self.config
        H, W    = self.SIM_H, self.SIM_W
        max_val = float((1 << cfg.bit_depth) - 1)
        exp_s   = cfg.exposure_us / 1e6
        gain_l  = 1.0 + cfg.gain * 0.09
        sky     = cfg.offset + 80.0 * exp_s * gain_l
        img     = np.full((H, W), sky, dtype=np.float32)
        for xs, ys, flux, fwhm in self._sim_stars:
            cx, cy = int(xs * W), int(ys * H)
            sigma  = fwhm / 2.355
            r      = max(4, int(sigma * 5))
            x0, x1 = max(0, cx - r), min(W, cx + r + 1)
            y0, y1 = max(0, cy - r), min(H, cy + r + 1)
            gy, gx = np.ogrid[y0:y1, x0:x1]
            peak   = flux * exp_s * gain_l
            if peak < 0.5:
                continue
            img[y0:y1, x0:x1] += (
                peak * np.exp(-((gx - cx) ** 2 + (gy - cy) ** 2)
                               / (2.0 * sigma ** 2))
            )
        img = np.random.poisson(np.clip(img, 0, max_val)).astype(np.float32)
        img += np.random.normal(0.0, 3.5 + cfg.gain * 0.08, img.shape)
        bayer = img.copy()
        bayer[0::2, 0::2] *= cfg.wb_r * 1.04
        bayer[0::2, 1::2] *= cfg.wb_g * 1.10
        bayer[1::2, 0::2] *= cfg.wb_g * 1.10
        bayer[1::2, 1::2] *= cfg.wb_b * 0.87
        dtype = np.uint16 if cfg.bit_depth == 16 else np.uint8
        return np.clip(bayer, 0, max_val).astype(dtype)


# ── pure helper functions ─────────────────────────────────────────────────────

def _gen_sim_stars(n: int, seed: int = 42) -> list[tuple]:
    rng    = np.random.default_rng(seed)
    xs     = rng.uniform(0.02, 0.98, n)
    ys     = rng.uniform(0.02, 0.98, n)
    fluxes = rng.exponential(4_000.0, n) + 200.0
    fwhms  = rng.uniform(1.8, 4.0, n)
    return list(zip(xs.tolist(), ys.tolist(), fluxes.tolist(), fwhms.tolist()))


def _auto_stretch(arr: np.ndarray, lo: float = 0.5, hi: float = 99.8) -> np.ndarray:
    flat = arr.ravel().astype(np.float32)
    vlo  = float(np.percentile(flat, lo))
    vhi  = float(np.percentile(flat, hi))
    if vhi <= vlo:
        vhi = vlo + 1.0
    return np.clip((arr.astype(np.float32) - vlo) / (vhi - vlo) * 255.0,
                   0, 255).astype(np.uint8)


def _debayer(mono8: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    h, w  = mono8.shape
    rgb   = np.empty((h // 2, w // 2, 3), dtype=np.uint8)
    m     = mono8.astype(np.uint16)
    if pattern == "RGGB":
        rgb[:, :, 0] = m[0::2, 0::2]
        rgb[:, :, 1] = (m[0::2, 1::2] + m[1::2, 0::2]) >> 1
        rgb[:, :, 2] = m[1::2, 1::2]
    elif pattern == "BGGR":
        rgb[:, :, 2] = m[0::2, 0::2]
        rgb[:, :, 1] = (m[0::2, 1::2] + m[1::2, 0::2]) >> 1
        rgb[:, :, 0] = m[1::2, 1::2]
    elif pattern == "GRBG":
        rgb[:, :, 0] = m[0::2, 1::2]
        rgb[:, :, 1] = (m[0::2, 0::2] + m[1::2, 1::2]) >> 1
        rgb[:, :, 2] = m[1::2, 0::2]
    else:
        rgb[:, :, 2] = m[0::2, 1::2]
        rgb[:, :, 1] = (m[0::2, 0::2] + m[1::2, 1::2]) >> 1
        rgb[:, :, 0] = m[1::2, 0::2]
    return rgb


def _apply_wb(rgb: np.ndarray, r: float, g: float, b: float) -> np.ndarray:
    out = rgb.astype(np.float32)
    out[:, :, 0] = np.clip(out[:, :, 0] * r, 0, 255)
    out[:, :, 1] = np.clip(out[:, :, 1] * g, 0, 255)
    out[:, :, 2] = np.clip(out[:, :, 2] * b, 0, 255)
    return out.astype(np.uint8)


def _compute_stats(raw: np.ndarray, bpp: int) -> dict:
    flat  = raw.ravel().astype(np.float32)
    counts, edges = np.histogram(flat, bins=256, range=(0, (1 << bpp) - 1))
    return {
        "min": float(raw.min()), "max": float(raw.max()),
        "mean": float(flat.mean()), "std": float(flat.std()),
        "hist_counts": counts.tolist(), "hist_edges": edges[:-1].tolist(),
    }


def _setup_prototypes(lib: ctypes.CDLL) -> None:
    u32  = ctypes.c_uint32;  u8  = ctypes.c_uint8
    vp   = ctypes.c_void_p;  cp  = ctypes.c_char_p
    dbl  = ctypes.c_double;  pu32 = ctypes.POINTER(u32)
    lib.InitQHYCCDResource.restype          = u32
    lib.ReleaseQHYCCDResource.restype       = u32
    lib.ScanQHYCCD.restype                  = u32
    lib.OpenQHYCCD.restype                  = vp;  lib.OpenQHYCCD.argtypes   = [cp]
    lib.CloseQHYCCD.restype                 = u32; lib.CloseQHYCCD.argtypes  = [vp]
    lib.SetQHYCCDStreamMode.restype         = u32; lib.SetQHYCCDStreamMode.argtypes = [vp, u8]
    lib.InitQHYCCD.restype                  = u32; lib.InitQHYCCD.argtypes   = [vp]
    lib.GetQHYCCDId.restype                 = u32; lib.GetQHYCCDId.argtypes  = [u32, cp]
    lib.SetQHYCCDParam.restype              = u32; lib.SetQHYCCDParam.argtypes = [vp, ctypes.c_int, dbl]
    lib.SetQHYCCDResolution.restype         = u32; lib.SetQHYCCDResolution.argtypes = [vp, u32, u32, u32, u32]
    lib.GetQHYCCDMemLength.restype          = u32; lib.GetQHYCCDMemLength.argtypes  = [vp]
    lib.ExpQHYCCDSingleFrame.restype        = u32; lib.ExpQHYCCDSingleFrame.argtypes = [vp]
    lib.GetQHYCCDSingleFrame.restype        = u32; lib.GetQHYCCDSingleFrame.argtypes = [vp, pu32, pu32, pu32, pu32, cp]
    lib.BeginQHYCCDLive.restype             = u32; lib.BeginQHYCCDLive.argtypes      = [vp]
    lib.StopQHYCCDLive.restype              = u32; lib.StopQHYCCDLive.argtypes       = [vp]
    lib.GetQHYCCDLiveFrame.restype          = u32; lib.GetQHYCCDLiveFrame.argtypes   = [vp, pu32, pu32, pu32, pu32, cp]
    lib.SetQHYCCDBitsMode.restype           = u32; lib.SetQHYCCDBitsMode.argtypes    = [vp, u32]