"""
SkyRenderer — asyncio edition
================================
Renders a horizon-centred star chart using starplot (BLUE_LIGHT + MAP style).
Falls back to a plain matplotlib scatter plot only when starplot cannot be
imported or HorizonPlot cannot be constructed.

Constructor strategy
--------------------
_create_plot() attempts construction in this order:

  Pass 1  — required kwargs only (lat, lon, dt, azimuth, altitude, fov)
             This is the safest call; starplot's defaults are used.
  Pass 2  — add optional kwargs one at a time, keeping those that work.
  Pass 3  — retry with legacy az/alt spelling if azimuth/altitude are
             rejected by name.

Style is applied AFTER a successful construction via p.style = …
rather than in the constructor, avoiding the 'float is not
subscriptable' error that some starplot versions raise when a
PlotStyle object is passed directly to __init__.
"""

from __future__ import annotations

import asyncio
import importlib
import io
import os
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime, UTC, timezone
from typing import Optional

import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from skyfield import api
from skyfield.constants import tau

## -- visibility helper


def _calculate_lst(dt: datetime, lon_deg: float) -> float:
    """Computes Local Sidereal Time (in hours, 0-24) given a UTC datetime

    and longitude in degrees (positive East, negative West).
    """
    # 1. Calculate Julian Date (JD) for the given UTC datetime
    year = dt.year
    month = dt.month
    day = dt.day
    hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

    if month <= 2:
        year -= 1
        month += 12

    A = math.floor(year / 100.0)
    B = 2 - A + math.floor(A / 4.0)
    JD = (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + B
        - 1524.5
        + hour / 24.0
    )

    # 2. Compute centuries from J2000.0
    T = (JD - 2451545.0) / 36525.0

    # 3. Compute Greenwich Mean Sidereal Time (GMST) in degrees
    # Formula from IAU 1982 / Meeus Astronomical Algorithms
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (JD - 2451545.0)
        + 0.000387933 * T**2
        - (T**3) / 38710000.0
    )

    # Normalize GMST to 0-360 degrees
    gmst_deg = gmst_deg % 360.0

    # 4. Compute Local Sidereal Time (LST) = GMST + Longitude (East positive)
    lst_deg = (gmst_deg + lon_deg) % 360.0

    # Convert degrees to hours (0-24 hours)
    lst_hours = lst_deg / 15.0

    return lst_hours

def _visible_sky(lat, lon, dt_utc=None):

    # Calculate LST for given location and time
    # Visible sky is LST +/- 6 hours modulo 24 hours
    lst_hours = _calculate_lst(dt_utc, lon)
    
    # Calculate visible Declination range
    # Objects within 90 degrees of your latitude are above the horizon
    dec_min = max(-85.0, lat - 90.0)
    dec_max = min(85.0, lat + 90.0)
    
    return lst_hours, dec_min, dec_max


# ── starplot ──────────────────────────────────────────────────────────────────
_SP_OK       = True

import starplot
from starplot import MapPlot, HorizonPlot, ZenithPlot, Orthographic, Miller, Observer, _   # type: ignore
from starplot.styles import PlotStyle, extensions   # type: ignore

@dataclass
class SkyConfig:
    # Observer
    lat:          float = 42.6233
    lon:          float = -71.4882
    elevation_m:  float = 131.0

    # Time
    use_current_time: bool     = True
    manual_dt:        datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Overlay toggles
    show_constellation_lines:  bool = True
    show_constellation_labels: bool = True
    show_milky_way:            bool = True
    show_nebula:               bool = False
    show_open_clusters:        bool = False
    show_altaz_grid:           bool = True
    show_radec_grid:           bool = False

    # Limiting magnitude for the full-sky map
    limiting_magnitude: float = 3.5

    # Render quality
    resolution: int = 1800   # pixels of the square output PNG
    scale: float = 1.0 


class FullSkyRenderer:
    """
    Singleton async renderer for the full-sky stereographic map.
    Writes PNG to a temp directory; serves via /static/sky/fullsky.png.
    """

    PNG_FILENAME = "fullsky.png"

    def __init__(self, config: SkyConfig, static_dir: str) -> None:
        self.config        = config
        self.static_dir    = static_dir
        self.output_path   = os.path.join(static_dir, self.PNG_FILENAME)
        self.output_url    = "/static/sky/fullsky.png"

        self._task:        Optional[asyncio.Task] = None
        self._is_rendering = False
        self._pending      = False
        self._render_count = 0
        self._last_dur     = 0.0
        self._last_error   = ""

        os.makedirs(static_dir, exist_ok=True)

        # Write a placeholder PNG immediately
        _write_placeholder(self.output_path)

    @property
    def is_rendering(self) -> bool:
        return self._is_rendering

    @property
    def render_count(self) -> int:
        return self._render_count

    @property
    def last_dur(self) -> float:
        return self._last_dur

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def using_starplot(self) -> bool:
        return _SP_OK

    @property
    def version(self) -> str:
        return starplot.__version__

    def render_async(self) -> None:
        """Schedule a background render; queues one pending if busy."""
        if self._is_rendering:
            self._pending = True
            return
        self._task = asyncio.create_task(
            self._do_render(), name="sky-render"
        )

    async def _do_render(self) -> None:
        self._is_rendering = True
        self._pending      = False
        loop = asyncio.get_running_loop()
        t0   = loop.time()
        try:
            fn  = self._render_starplot if _SP_OK else self._render_fallback
            await asyncio.to_thread(fn)
        except Exception as exc:
            traceback.print_exc()
            self._last_error = str(exc)
            await asyncio.to_thread(_write_placeholder,
                                    self.output_path,
                                    f"Render error:\n{exc}")
        else:
            self._last_error = ""
        self._last_dur     = loop.time() - t0
        self._render_count += 1
        self._is_rendering  = False
        if self._pending:
            self.render_async()

    # ── starplot full-sky stereographic render (thread pool) ─────────────────

    def _render_starplot(self) -> None:
        cfg = self.config
        dt  = self._effective_dt()

        # ── style: MAP extension for the Orion-map look ───────────────────────
        style = PlotStyle().extend(
            extensions.BLUE_NIGHT,
            extensions.MAP,
        )

        # ── find the ZENITH projection ─────────────────────────────────
        
        print(f"[sky] rendering sky plot"
              f"res={cfg.resolution}  mag≤{cfg.limiting_magnitude}")
        dtn = datetime.now(UTC)
        obs = Observer(dt = dtn, lat=cfg.lat, lon = cfg.lon)
        lst, dec_min, dec_max = _visible_sky(cfg.lat, cfg.lon, dtn)
        ra_min = max(0.0, lst - 6.0)
        ra_max = min(24.0,lst + 6.0)

        print("project fov ", lst, ra_min, ra_max, dec_min, dec_max)
        
        # p = MapPlot(
        #     projection=Miller(),
        #     ra_min = ra_min,
        #     ra_max = ra_max,
        #     dec_min = dec_min,
        #     dec_max = dec_max,
        #     style=style,
        #     limiting_magnitude = cfg.limiting_magnitude,
        #     resolution = cfg.resolution,
        #     autoscale = True
        # )
        # p = ZenithPlot(
        #     observer=obs,
        #     style=style,
        #     limiting_magnitude = cfg.limiting_magnitude,
        #     resolution = cfg.resolution,
        #     scale = cfg.scale,
        #     autoscale = True
        # )

        # ── constructor: probe kwargs progressively ───────────────────────────
        p = MapPlot(
            projection         = Miller(),
            lat                = cfg.lat,
            lon                = cfg.lon,
            dt                 = dtn,
            dec_min            = dec_min,
            dec_max            = dec_max,
            style              = style,
            limiting_magnitude = cfg.limiting_magnitude,
            resolution         = cfg.resolution,
            autoscale          = True, 
        )

        # ── layers ────────────────────────────────────────────────────────────
        p.stars(where=[_.magnitude < cfg.limiting_magnitude], bayer_labels=True, where_labels=[_.magnitude < 3.5])

        p.horizon()
        p.ecliptic(num_labels=2)

        p.planets(true_size=False)
        p.moon(true_size=False, show_phase=True)
        p.sun(true_size = False)

        if cfg.show_milky_way:
            p.milky_way()

        if cfg.show_open_clusters:
            p.open_clusters(where=[_.magnitude < cfg.limiting_magnitude])
            
        if cfg.show_nebula:
            p.nebula(where=[_.magtitude < cfg.limiting_magnitude])
 
        if cfg.show_constellation_lines:
            p.constellations()
            p.constellation_borders()

        if cfg.show_constellation_labels:
            p.constellation_labels()

        if cfg.show_altaz_grid:
            p.gridlines()

        if cfg.show_radec_grid:
            p.radec_gridlines()

        _export_plot(p, self.output_path)

    def _render_fallback(self) -> None:
        """Matplotlib placeholder when starplot is unavailable."""
        _write_placeholder(
            self.output_path,
            f"starplot {_SP_VERSION} — unavailable\n"
            "brew install libiio && poetry install"
        )

    def _effective_dt(self) -> datetime:
        if self.config.use_current_time:
            return datetime.now(timezone.utc)
        dt = self.config.manual_dt
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── module helpers ────────────────────────────────────────────────────────────


def _export_plot(plot, out_path: str) -> None:
    """Export starplot figure to PNG file."""
    buf = io.BytesIO()
    try:
        plot.export(buf, format="png")
        buf.seek(0)
        data = buf.read()
        if data:
            with open(out_path, "wb") as f:
                f.write(data)
            return
    except Exception:
        pass
    # temp-file fallback
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        plot.export(tmp)
        import shutil
        shutil.move(tmp, out_path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _write_placeholder(path: str, message: str = "Rendering…") -> None:
    """Write a dark placeholder PNG to the given path."""
    fig, ax = plt.subplots(figsize=(10, 10), facecolor="#020810")
    ax.set_facecolor("#020810")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    rng = np.random.default_rng(42)
    ax.scatter(rng.uniform(0, 1, 800), rng.uniform(0, 1, 800),
               s=rng.uniform(0.1, 3.0, 800), c="white",
               alpha=rng.uniform(0.05, 0.7, 800), linewidths=0)
    ax.text(0.5, 0.5, message, ha="center", va="center",
            color="#475569", fontsize=12, style="italic",
            transform=ax.transAxes, multialignment="center")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig.savefig(path, format="png", dpi=100,
                bbox_inches="tight", facecolor="#020810")
    plt.close(fig)