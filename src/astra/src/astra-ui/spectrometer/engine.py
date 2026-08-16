"""
SpectrometerEngine — Analog Devices PlutoSDR via libiio
========================================================
Streams complex IQ data from an AD9361-based PlutoSDR, computes a
windowed Welch-averaged power spectral density, maintains a rolling
waterfall spectrogram, and tracks total band power versus time.

Hardware path
-------------
Requires system libiio + pylibiio Python binding.

  macOS : brew install libiio && poetry install -E sdr
  Linux : sudo apt install libiio-dev && poetry install -E sdr

Snapshot
--------
Captures a burst of IQ samples and writes them to DigitalRF format in
/data/rf/captures/.  Requires:  poetry install -E drf

IIO attribute mapping
---------------------
  center_freq_hz   →  ad9361-phy  altvoltage0  frequency
  sample_rate_hz   →  ad9361-phy  voltage0     sampling_frequency
                                               rf_bandwidth
  gain_db          →  ad9361-phy  voltage0     hardwaregain
                                               gain_control_mode = manual
  IQ stream        ←  cf-ad9361-lpc  voltage0 (I) + voltage1 (Q)
"""

from __future__ import annotations

import asyncio
import os
import time as _time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

# ── libiio ────────────────────────────────────────────────────────────────────
import adi as _adi


# ── digital_rf (optional, for snapshot) ──────────────────────────────────────
import digital_rf as _drf   # type: ignore
_DRF_OK = True


# ── common sample rate options (used by both engine and page) ─────────────────
SAMPLE_RATES: dict[int, str] = {
    1:  " 1 MSPS  (1 MHz BW)",
    2:  " 2 MSPS  (2 MHz BW)",
    4:  " 4 MSPS  (4 MHz BW)",
    8:  " 8 MSPS  (8 MHz BW)",
    10: "10 MSPS (10 MHz BW)",
}

# Maximum IIO buffer size — keeps single refill ≤ ~131 ms at 2 MSPS
_MAX_BUF_SAMPLES = 16777216


# ── configuration ─────────────────────────────────────────────────────────────

@dataclass
class SpectrometerConfig:
    # SDR connection
    pluto_uri:        str   = "ip:192.168.2.1"

    # RF parameters
    center_freq_MHz:   int   = 1420   # MHz
    sample_rate_MHz:   int   = 2   # MHz
    gain_db:           float = 50.0          # dB, 0–73

    # Processing
    fft_size:         int   = 1024
    subintegration_time: float = 0.1          # seconds
    waterfall_rows:   int   = 128

    # Snapshot
    snapshot_dir:     str   = "/data/rf/"
    snapshot_chan:    str   = "ch0"
    snapshot_dur_s:   float = 5.0


# ── engine ────────────────────────────────────────────────────────────────────

class SpectrometerEngine:
    """
    Async-native spectrometer backend.

    All blocking IIO / computation work runs in asyncio.to_thread.
    State mutations happen only in the event loop — no locks needed.
    """

    def __init__(self, config: SpectrometerConfig | None = None) -> None:
        self.config = config or SpectrometerConfig()

        # ── IIO objects ───────────────────────────────────────────────────────
        self._sdr:      Optional[object] = None

        # ── task ──────────────────────────────────────────────────────────────
        self._task:      Optional[asyncio.Task] = None
        self._running    = False
        self._connected  = False

        # ── buffer geometry (recalculated when config changes) ────────────────
        self._buf_n_samples = 0
        self._n_ffts        = 0

        # ── output state (mutated only in event loop) ─────────────────────────
        self._freqs:      np.ndarray = np.zeros(self.config.fft_size)
        self._psd_l:    np.ndarray = np.full(self.config.fft_size, 1E-12)
        self._pvt_t:      deque[float] = deque(maxlen=256)
        self._pvt_p:      deque[float] = deque(maxlen=256)
        #self._waterfall:  np.ndarray  = np.full(
        #    (self.config.waterfall_rows, self.config.fft_size), -120.0
        #)
        #self._wf_elapsed: np.ndarray = np.zeros(self.config.waterfall_rows)
        self._t0          = _time.time()
        self._n_spectra   = 0

        self._recalc_buf_size()
        self._recalc_freqs()

    # ── public read-only state ────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_running(self) -> bool:
        return self._running and bool(self._task and not self._task.done())

    def get_psd(self) -> tuple[np.ndarray, np.ndarray]:
        return self._freqs.copy(), self._psd_l.copy()

    def get_power_vs_time(self) -> tuple[np.ndarray, np.ndarray]:
        if not self._pvt_t:
            return np.array([0.0]), np.array([-120.0])
        return np.array(self._pvt_t), np.array(self._pvt_p)

    def get_waterfall(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._freqs.copy(), self._wf_elapsed.copy(), self._waterfall.copy()
    
    def clear_data(self):
        if not self._running:
            self._reinit_output_buffers()


    # ── connection ────────────────────────────────────────────────────────────

    async def connect(self, uri: str | None = None) -> tuple[bool, str]:
        """Open libiio context and configure the AD9361.  Non-blocking."""
        if uri:
            self.config.pluto_uri = uri

        was_running = self.is_running
        if was_running:
            self.stop()

        ok, msg = await asyncio.to_thread(self._hw_connect)

        if ok:
            self._connected = True
        else:
            self._connected = False

        if was_running or ok:
            self.start()

        return ok, msg

    async def disconnect(self) -> None:
        self._connected          = False
        self.stop()
        await asyncio.to_thread(self._hw_disconnect)
 
    # ── parameter setters ─────────────────────────────────────────────────────

    async def set_frequency(self, MHz: int) -> None:
        self.config.center_freq_MHz = int(MHz)
        self._recalc_freqs()
        if self._sdr:
            await asyncio.to_thread(self._hw_set_frequency, int(MHz))

    async def set_gain(self, db: float) -> None:
        self.config.gain_db = float(db)
        if self._sdr:
            await asyncio.to_thread(self._hw_set_gain, float(db))

    async def set_sample_rate(self, MHz: int) -> None:
        was_running = self.is_running
        if was_running:
            self.stop()
            if self._task:
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), 2.0)
                except Exception:
                    pass

        self.config.sample_rate_MHz = int(MHz)
        self._recalc_freqs()
        self._recalc_buf_size()
        self._reinit_output_buffers()

        if self._sdr:
            await asyncio.to_thread(self._hw_set_sample_rate, int(MHz))

        if was_running:
            self.start()

    async def update_config(self, **kwargs) -> None:
        """Apply arbitrary config changes and restart if running."""
        print("sdr update config")
        was_running = self.is_running
        self.stop()
        if self._task:
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

        for key, val in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, val)

        print("sdr update config - redo buffers")
        self._recalc_buf_size()
        self._recalc_freqs()
        self._reinit_output_buffers()

        print("sdr update config - about to hw configure")
        if self._sdr:
            await asyncio.to_thread(self._hw_configure_all)
            print("sdr update hw config ok")

        print("sdr update - about to start")
        if was_running:
            self.start()
            print("sdr update - start again")

    # ── start / stop ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._t0      = _time.time()
        self._task    = asyncio.create_task(
            self._run(), name="spectrometer"
        )

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    # ── snapshot ──────────────────────────────────────────────────────────────

    async def take_snapshot(
        self, duration_s: float | None = None
    ) -> tuple[bool, str]:
        """
        Record IQ samples to DigitalRF format.
        Returns (ok, path_or_error_message).
        """
        if not _DRF_OK:
            return False, (
                "Snapshot requires digital-rf: "
                "poetry install -E drf"
            )

        dur      = float(duration_s or self.config.snapshot_dur_s)
        n        = int(self.config.sample_rate_MHz * 1E6 * dur)
        was_run  = self.is_running

        if was_run:
            self.stop()

        samples = await asyncio.to_thread(self._collect_n_samples, n)

        if was_run:
            self.start()

        if samples is None:
            return False, "Sample collection failed"

        ok, path = await asyncio.to_thread(
            self._write_drf_snapshot, samples, dur
        )
        return ok, path

    # ── async processing task ─────────────────────────────────────────────────

    async def _run(self) -> None:
        try:
            while self._running:
                result = await asyncio.to_thread(self._compute_integration)
                if result is not None and self._running:
                    psd_l, pvt_l, t_now = result
                    # All mutations in event loop — no locks needed
                    self._psd_l          = psd_l
                    self._pvt_t.append(t_now)
                    self._pvt_p.append(pvt_l)
                    # self._waterfall        = np.roll(self._waterfall,  1, axis=0)
                    # self._waterfall[0]     = psd
                    # self._wf_elapsed       = np.roll(self._wf_elapsed, 1)
                    # self._wf_elapsed[0]    = t_now
                    self._n_spectra       += 1
                await asyncio.sleep(0.02)   # yield to event loop
        except asyncio.CancelledError:
            pass

    # ── blocking compute (runs in thread pool) ────────────────────────────────

    def _compute_integration(self) -> Optional[tuple]:
        """
        Read one integration's worth of samples, compute windowed PSD.
        Blocking — call via asyncio.to_thread.
        """
        cfg    = self.config
        N      = cfg.fft_size
        sr     = cfg.sample_rate_MHz * int(1E6)
        n_ffts = self._n_ffts

        # Acquire samples
        n_samp  = n_ffts * N
        self._sdr.rx_buffer_size = n_samp

        samples = self._sdr.rx()

        if samples is None:
            return None

        # Welch-style PSD
        window    = np.hanning(N).astype(np.float32)
        win_power = float(np.sum(window ** 2))
        acc       = np.zeros(N, dtype=np.float64)

        actual = min(n_ffts, len(samples) // N)
        if actual == 0:
            return None

        for k in range(actual):
            chunk = samples[k * N:(k + 1) * N]
            acc  += np.abs(np.fft.fftshift(np.fft.fft(chunk * window))) ** 2
        acc /= actual

        psd_lin = np.maximum(acc / (win_power * sr), 1e-30)
        pvt_lin = np.maximum(np.mean(acc / (win_power*sr)), 1e-30)
        t_now  = _time.time() - self._t0
        
        return psd_lin, pvt_lin, t_now

    # ── SDR hardware methods (all blocking) ───────────────────────────────────

    def _hw_connect(self) -> tuple[bool, str]:
        try:
            try:
                sdr = _adi.Pluto(self.config.pluto_uri)
            except RuntimeError as e:
                return False, f"PlutoSDR not found: {self.config.pluto_uri}"
            
            self._sdr = sdr
            self._hw_configure_all()

            return True, f"PlutoSDR connected: {self.config.pluto_uri}"

        except Exception as exc:
            return False, f"Connect error: {exc}"

    def _hw_disconnect(self) -> None:
        try:
            self._sdr = None
        except Exception as exc:
            print(f"[spectrometer] PlutoSDR disconnect error: {exc}")

    def _hw_configure_all(self) -> None:
        """Push all config attributes to the AD9361."""
        try:
            print("get config")
            cfg   = self.config
           
            print("LO frequency")
            # LO frequency
            self._sdr.rx_lo = int(cfg.center_freq_MHz*1E6)
            print("set sample sample rate and bandwidth")
            # Sample rate + RF bandwidth (both to same value)
            self._sdr.sample_rate = int(cfg.sample_rate_MHz*1E6)
            self._sdr.rx_rf_bandwidth = int(cfg.sample_rate_MHz*1E6)
            print('set gain control mode')
            self._sdr.gain_control_mode_chan0 = 'manual'
            self._sdr.rx_hardwaregain_chan0 = int(cfg.gain_db)

        except Exception as exc:
            print(f"[spectrometer] configure error: {exc}")

    def _hw_set_frequency(self, MHz: int) -> None:
        try:
            self._sdr.rx_lo = int(MHz * 1E6)
        except Exception as exc:
            pass 
            #print(f"[spectrometer] set_frequency error: {exc}")

    def _hw_set_gain(self, db: float) -> None:
        try:
            self._sdr.rx_hardwaregain_chan0 = db
        except Exception as exc:
            print(f"[spectrometer] set_gain error: {exc}")

    def _hw_set_sample_rate(self, MHz: int) -> None:
        try:
            self._sdr.sample_rate = int(MHz * 1E6)
            self._sdr.rx_rf_bandwidth = int(MHz * 1E6)
        except Exception as exc:
            print(f"[spectrometer] set_sample_rate error: {exc}")


    def _refill_and_read(self) -> Optional[np.ndarray]:
        """
        Blocking IIO buffer read.
        Returns complex64 array or None on error.

        PlutoSDR data layout: interleaved int16 I,Q pairs
          raw = [I0, Q0, I1, Q1, …]   (2 * N int16 values for N IQ samples)
        AD9361 ADC is 12-bit, stored right-justified in signed 16-bit:
          value range ≈ −2048 … +2047  →  scale by 1/2048 to normalise
        """
        try:
            self._sdr.rx_buffer_size = self._buf_n_samples
            samples = self._sdr.rx()
            return samples
        except Exception as exc:
            print(f"[spectrometer] SDR read error: {exc}")
            return None

    # ── snapshot helpers (blocking, thread pool) ──────────────────────────────

    def _collect_n_samples(self, n: int) -> Optional[np.ndarray]:
        """Collect exactly n complex samples via repeated SDR refills"""
        chunks: list[np.ndarray] = []
        remaining = n

        while remaining > 0:
            want = min(remaining, self._buf_n_samples or n)

            # Use existing buffer (fixed size) and trim
            c = self._refill_and_read()
            if c is None:
                break
            chunk = c[:want]

            chunks.append(chunk)
            remaining -= len(chunk)

        if not chunks:
            return None
        combined = np.concatenate(chunks)
        return combined[:n]

    def _write_drf_snapshot(
        self, samples: np.ndarray, duration_s: float
    ) -> tuple[bool, str]:
        try:
            sr  = int(self.config.sample_rate_MHz * 1E6)
            ts  = datetime.now(timezone.utc)
            ts_str = ts.isoformat().replace("+00:00", "Z")

            # DigitalRF channel directory (auto-managed subdirectory structure)
            data_dir_name = f"astra@{ts_str}"
            ch_dir_name = "ch0"
            ch_dir  = os.path.join(self.config.snapshot_dir, data_dir_name, ch_dir_name)
            os.makedirs(ch_dir, exist_ok=True)

            start_sample = int(ts.timestamp() * sr)

            writer = _drf.DigitalRFWriter(
                directory                = ch_dir,
                dtype                    = np.complex64,
                subdir_cadence_secs      = 3600,
                file_cadence_millisecs   = max(1000, int(duration_s * 1000)),
                start_global_index       = start_sample,
                sample_rate_numerator    = sr,
                sample_rate_denominator  = 1,
                uuid_str                 = 'ASTRA',
                num_subchannels          = 1,
                is_complex               = True,
                compression_level        = 0,
                checksum                 = False,
                is_continuous            = True,
                marching_periods         = False,
            )

            writer.rf_write(samples.astype(np.complex64))
            writer.close()

            # Optional metadata
            try:
                meta_dir = os.path.join(ch_dir, "metadata")
                os.makedirs(meta_dir, exist_ok=True)
                mw = _drf.DigitalMetadataWriter(
                    metadata_dir           = meta_dir,
                    subdir_cadence_seconds = 3600,
                    file_cadence_seconds   = 3600,
                    sample_rate_numerator  = sr,
                    sample_rate_denominator= 1,
                    file_name              = "dmd",
                )
                mw.write(
                    sample_index = start_sample,
                    data_dict    = {
                        "center_freq_hz": int(self.config.center_freq_MHz*1E6),
                        "sample_rate_hz": sr,
                        "gain_db":        self.config.gain_db,
                        "duration_s":     duration_s,
                        "n_samples":      len(samples),
                        "source":         "PlutoSDR",
                        "timestamp":      ts.isoformat(),
                        "uri":            self.config.pluto_uri,
                    },
                )
            except Exception:
                pass   # metadata is optional

            print(f"[spectrometer] snapshot → {ch_dir}  ({len(samples):,} samples)")
            return True, ch_dir

        except Exception as exc:
            import traceback; traceback.print_exc()
            return False, str(exc)

    # ── geometry helpers ──────────────────────────────────────────────────────

    def _recalc_buf_size(self) -> None:
        """Compute buffer size and FFTs-per-integration from config."""
        N       = self.config.fft_size
        sr      = int(self.config.sample_rate_MHz * 1E6)
        desired = max(N, int(sr * self.config.subintegration_time))
        capped  = min(desired, _MAX_BUF_SAMPLES)
        aligned = max(N, (capped // N) * N)

        self._buf_n_samples = aligned
        self._n_ffts        = aligned // N

    def _recalc_freqs(self) -> None:
        sr = int(self.config.sample_rate_MHz * 1E6)
        cf = self.config.center_freq_MHz     # display in MHz
        N  = self.config.fft_size
        self._freqs = (
            cf + np.linspace(-sr / 2.0, sr / 2.0, N, endpoint=False) / 1e6
        )

    def _reinit_output_buffers(self) -> None:
        N = self.config.fft_size
        W = self.config.waterfall_rows
        self._psd        = np.full(N, -120.0, dtype=np.float64)
        self._psd_l    = np.full(N, 1E-12, dtype=np.float64)
        self._pvt_t      = deque(maxlen=512)
        self._pvt_p      = deque(maxlen=512)
        self._waterfall  = np.full((W, N), -120.0, dtype=np.float64)
        self._wf_elapsed = np.zeros(W, dtype=np.float64)
        self._t0         = _time.time()
        self._n_spectra  = 0