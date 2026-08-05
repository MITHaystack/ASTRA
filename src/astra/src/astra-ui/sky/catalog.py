"""
VisibleCatalog — asyncio edition
==================================
Computes alt/az for stars and DSOs using spherical trigonometry driven by
skyfield's Greenwich Apparent Sidereal Time (t.gast).

Avoids wgs84.latlon().at(t).observe() — that API returns a Geocentric
position object which does not have an observe() method in skyfield 1.46+.
t.gast requires only the timescale (no ephemeris / .bsp download).

asyncio.Lock guards the one-time Hipparcos load.
CPU-bound work runs in asyncio.to_thread.
"""

from __future__ import annotations

import os
import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

# ── module-level Hipparcos state ──────────────────────────────────────────────

_hip_load_lock: asyncio.Lock = asyncio.Lock()
_hip_loaded:    bool         = False
_hip_df                      = None   # pandas DataFrame once loaded
_sf_ts                       = None   # shared skyfield Timescale


# ── sky object ────────────────────────────────────────────────────────────────

@dataclass
class SkyObject:
    name:       str
    obj_type:   str
    ra_deg:     float        # J2000 RA  degrees
    dec_deg:    float        # J2000 Dec degrees
    az:         float        # current Alt-Az (degrees)
    alt:        float
    magnitude:  Optional[float]
    catalog_id: str   = ""
    px:         float = 0.0  # image pixel position (set by build())
    py:         float = 0.0


# ── built-in DSO catalog ──────────────────────────────────────────────────────
# (name, type, ra_deg J2000, dec_deg J2000, magnitude | None)

_BUILTIN_DSOS: list[tuple] = [
    # ── radio calibrators & famous radio sources ──────────────────────────────
    ("Cassiopeia A",           "SupernovaRemnant", 350.866,  58.815, None),
    ("Cygnus A",               "RadioGalaxy",      299.868,  40.734, None),
    ("Taurus A (M1)",          "SupernovaRemnant",  83.633,  22.015,  8.4),
    ("Virgo A (M87)",          "RadioGalaxy",      187.706,  12.391,  8.6),
    ("Sagittarius A*",         "GalacticCenter",   266.417, -29.008, None),
    ("Centaurus A (NGC 5128)", "RadioGalaxy",      201.365, -43.019,  6.8),
    ("Hercules A (3C 348)",    "RadioGalaxy",      252.783,   4.993, None),
    ("3C 273",                 "Quasar",           187.277,   2.052, 12.9),
    ("3C 286",                 "Quasar",           202.784,  30.509, 17.3),
    ("3C 48",                  "Quasar",            24.424,  33.160, 16.2),
    ("3C 147",                 "Quasar",            85.649,  49.852, 16.9),
    ("Fornax A (NGC 1316)",    "RadioGalaxy",       50.674, -37.208,  8.5),
    ("Perseus A (NGC 1275)",   "RadioGalaxy",       49.951,  41.512, 11.9),
    ("M84 (3C 272.1)",         "RadioGalaxy",      186.266,  12.887,  9.1),
    ("NGC 1068 (3C 71)",       "Seyfert",           40.670,  -0.013,  8.9),
    # ── nebulae & supernova remnants ──────────────────────────────────────────
    ("M1  Crab Nebula",        "SupernovaRemnant",  83.633,  22.015,  8.4),
    ("M8  Lagoon Nebula",      "Nebula",           271.033, -24.383,  6.0),
    ("M17 Omega Nebula",       "Nebula",           275.217, -16.183,  6.0),
    ("M20 Trifid Nebula",      "Nebula",           270.620, -23.035,  9.0),
    ("M27 Dumbbell Nebula",    "PlanetaryNebula",  299.901,  22.721,  7.4),
    ("M42 Orion Nebula",       "Nebula",            83.822,  -5.391,  4.0),
    ("M57 Ring Nebula",        "PlanetaryNebula",  283.396,  33.029,  8.8),
    ("M97 Owl Nebula",         "PlanetaryNebula",  168.700,  55.019,  9.9),
    ("NGC 7293 Helix",         "PlanetaryNebula",  337.410, -20.837,  7.3),
    ("NGC 6543 Cat's Eye",     "PlanetaryNebula",  269.639,  66.633,  8.1),
    ("NGC 6960 Veil Nebula W", "SupernovaRemnant", 312.180,  30.716, None),
    ("NGC 6992 Veil Nebula E", "SupernovaRemnant", 314.260,  31.722, None),
    ("NGC 7000 N. America",    "EmissionNebula",   314.000,  44.300, None),
    ("IC  1805 Heart Nebula",  "EmissionNebula",    38.175,  61.451, None),
    ("IC  1848 Soul Nebula",   "EmissionNebula",    43.175,  60.402, None),
    ("NGC 2244 Rosette",       "EmissionNebula",    97.778,   4.933,  4.8),
    ("IC  443  Jellyfish",     "SupernovaRemnant",  94.310,  22.530, None),
    # ── galaxies ──────────────────────────────────────────────────────────────
    ("M31 Andromeda Galaxy",   "Galaxy",            10.684,  41.269,  3.4),
    ("M33 Triangulum Galaxy",  "Galaxy",            23.462,  30.660,  5.7),
    ("M51 Whirlpool Galaxy",   "Galaxy",           202.470,  47.195,  8.4),
    ("M81 Bode's Galaxy",      "Galaxy",           148.888,  69.065,  6.9),
    ("M82 Cigar Galaxy",       "Galaxy",           148.970,  69.681,  8.4),
    ("M101 Pinwheel Galaxy",   "Galaxy",           210.802,  54.349,  7.9),
    ("M104 Sombrero Galaxy",   "Galaxy",           189.997, -11.623,  8.0),
    ("NGC 253 Sculptor",       "Galaxy",            11.888, -25.288,  7.1),
    ("NGC 4565 Needle",        "Galaxy",           189.086,  25.988,  9.6),
    ("NGC 4631 Whale",         "Galaxy",           190.533,  32.541,  9.0),
    # ── open clusters ─────────────────────────────────────────────────────────
    ("M45 Pleiades",           "OpenCluster",       56.871,  24.105,  1.6),
    ("M44 Beehive",            "OpenCluster",      130.025,  19.621,  3.1),
    ("M35",                    "OpenCluster",       92.268,  24.333,  5.1),
    ("NGC 869 h Per",          "OpenCluster",       34.747,  57.132,  5.3),
    ("NGC 884 χ Per",          "OpenCluster",       35.430,  57.138,  6.1),
    # ── globular clusters ─────────────────────────────────────────────────────
    ("M13 Hercules Cluster",   "GlobularCluster",  250.423,  36.461,  5.8),
    ("M3",                     "GlobularCluster",  205.549,  28.377,  6.2),
    ("M5",                     "GlobularCluster",  229.638,   2.081,  5.6),
    ("M22",                    "GlobularCluster",  279.100, -23.905,  5.1),
    ("M92",                    "GlobularCluster",  259.280,  43.136,  6.4),
    ("NGC 5139 Omega Cen",     "GlobularCluster",  201.697, -47.480,  3.9),
]


# ── GAST-based alt/az conversion ──────────────────────────────────────────────

def _radec_to_altaz(
    ra_deg:  float,
    dec_deg: float,
    lat_deg: float,
    lon_deg: float,
    gast_h:  float,        # Greenwich Apparent Sidereal Time (hours)
) -> tuple[float, float]:
    """
    Convert J2000 RA/Dec to topocentric Alt/Az using spherical trigonometry.

    Parameters
    ----------
    ra_deg, dec_deg : J2000 coordinates in degrees
    lat_deg, lon_deg: observer geodetic coordinates
    gast_h          : skyfield ``t.gast`` — Greenwich Apparent Sidereal Time
                      in decimal hours (includes nutation, no .bsp needed)

    Returns
    -------
    (alt_degrees, az_degrees)  — alt: −90..+90, az: 0..360 (N=0, E=90)
    """
    lst_h  = (gast_h + lon_deg / 15.0) % 24.0   # Local Sidereal Time (hours)
    ha_deg = (lst_h * 15.0 - ra_deg) % 360.0     # Hour Angle (degrees)

    lat_r = math.radians(lat_deg)
    ha_r  = math.radians(ha_deg)
    dec_r = math.radians(dec_deg)

    # Altitude
    sin_alt = (math.sin(lat_r) * math.sin(dec_r) +
               math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r))
    alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))

    # Azimuth
    cos_alt = math.cos(math.radians(alt))
    if cos_alt < 1e-10:
        return alt, 0.0
    cos_az = ((math.sin(dec_r) - math.sin(lat_r) * sin_alt) /
              (math.cos(lat_r) * cos_alt))
    az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    if math.sin(ha_r) > 0:
        az = 360.0 - az
    return alt, az % 360.0


def _radec_to_altaz_vec(
    ra_arr:  np.ndarray,   # degrees, shape (N,)
    dec_arr: np.ndarray,   # degrees, shape (N,)
    lat_deg: float,
    lon_deg: float,
    gast_h:  float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Vectorised version of _radec_to_altaz for the Hipparcos star array.
    Returns (alt_deg, az_deg) arrays, both shape (N,).
    """
    lst_h   = (gast_h + lon_deg / 15.0) % 24.0
    ha_deg  = (lst_h * 15.0 - ra_arr) % 360.0

    lat_r  = math.radians(lat_deg)
    ha_r   = np.radians(ha_deg)
    dec_r  = np.radians(dec_arr)

    sin_alt = (math.sin(lat_r) * np.sin(dec_r) +
               math.cos(lat_r) * np.cos(dec_r) * np.cos(ha_r))
    sin_alt = np.clip(sin_alt, -1.0, 1.0)
    alt_arr = np.degrees(np.arcsin(sin_alt))

    cos_alt = np.cos(np.radians(alt_arr))
    # Guard against division by zero at the zenith/nadir
    cos_alt = np.where(np.abs(cos_alt) < 1e-10, 1e-10, cos_alt)

    cos_az  = ((np.sin(dec_r) - math.sin(lat_r) * sin_alt) /
               (math.cos(lat_r) * cos_alt))
    cos_az  = np.clip(cos_az, -1.0, 1.0)
    az_arr  = np.degrees(np.arccos(cos_az))
    az_arr  = np.where(np.sin(ha_r) > 0, 360.0 - az_arr, az_arr)
    az_arr  = az_arr % 360.0

    return alt_arr, az_arr


# ── lazy Hipparcos loader ─────────────────────────────────────────────────────

def _load_hipparcos_blocking() -> None:
    """
    Load the Hipparcos catalogue — blocking, intended for asyncio.to_thread.

    Uses a Loader rooted at ~/.skyfield so the file is downloaded once and
    cached there permanently, regardless of the process working directory.
    """
    global _hip_df, _sf_ts
    try:
        from skyfield.api import Loader
        from skyfield.data import hipparcos

        # Persistent cache directory — created automatically if absent
        cache_dir = os.path.expanduser("~/.skyfield")
        os.makedirs(cache_dir, exist_ok=True)

        loader = Loader(cache_dir)
        ts     = loader.timescale()
        _sf_ts = ts

        with loader.open(hipparcos.URL) as f:
            df = hipparcos.load_dataframe(f)

        _hip_df = df[df["magnitude"].notna()].copy()
        print(
            f"[catalog] Hipparcos: {len(_hip_df):,} stars loaded"
            f" (cache: {cache_dir})"
        )
    except Exception as exc:
        print(f"[catalog] Hipparcos unavailable ({exc}) — DSOs only")
        _hip_df = None


async def _ensure_hipparcos_loaded() -> None:
    global _hip_loaded
    async with _hip_load_lock:
        if not _hip_loaded:
            await asyncio.to_thread(_load_hipparcos_blocking)
            _hip_loaded = True


# Visible Catalog
# ── catalog builder ───────────────────────────────────────────────────────────

class VisibleCatalog:
    """
    Builds a list of SkyObjects visible in the current SkyConfig field.

    Coordinate conversion uses t.gast (Greenwich Apparent Sidereal Time)
    from skyfield's timescale — accurate to ~0.1° for display purposes and
    requires no planetary ephemeris (.bsp) file.
    """

    async def build(self, config) -> list[SkyObject]:
        await _ensure_hipparcos_loaded()
        return await asyncio.to_thread(self._build_sync, config)

    def _build_sync(self, config) -> list[SkyObject]:
        from .projection import sky_to_pixel, angular_sep

        dt = (datetime.now(timezone.utc)
              if config.use_current_time
              else config.manual_dt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Obtain GAST once — shared by both DSO and star loops
        gast_h = self._gast(dt)

        objects: list[SkyObject] = []
        objects += self._dso_list(config, gast_h)
        if _hip_df is not None:
            objects += self._star_list(config, gast_h)

        # Project to pixels; keep only objects inside the FOV
        R     = config.resolution
        fov   = config.fov
        az_c  = config.az
        alt_c = config.alt
        visible: list[SkyObject] = []

        for obj in objects:
            sep = angular_sep(obj.az, obj.alt, az_c, alt_c)
            if sep > fov * 0.53:
                continue
            px, py = sky_to_pixel(obj.az, obj.alt, az_c, alt_c, fov, R, R)
            if px is None:
                continue
            obj.px = px
            obj.py = py
            visible.append(obj)

        return visible

    # ── GAST helper ───────────────────────────────────────────────────────────

    @staticmethod
    def _gast(dt: datetime) -> float:
        """
        Return the Greenwich Apparent Sidereal Time in decimal hours.
        Uses the cached skyfield Timescale if already loaded, otherwise
        constructs one from the persistent ~/.skyfield cache.
        """
        try:
            from skyfield.api import Loader
            import os
            if _sf_ts is not None:
                return float(_sf_ts.from_datetime(dt).gast)
            cache_dir = os.path.expanduser("~/.skyfield")
            os.makedirs(cache_dir, exist_ok=True)
            ts = Loader(cache_dir).timescale()
            return float(ts.from_datetime(dt).gast)
        except Exception:
            # Fallback: GMST from Julian Date (no nutation correction)
            jd      = (
                (dt - datetime(2000, 1, 1, 12, tzinfo=timezone.utc))
                .total_seconds() / 86400.0 + 2451545.0
            )
            t       = (jd - 2451545.0) / 36525.0
            gmst_deg = (
                280.46061837
                + 360.98564736629 * (jd - 2451545.0)
                + 0.000387933 * t ** 2
                - t ** 3 / 38710000.0
            ) % 360.0
            return gmst_deg / 15.0

    # ── DSO list ──────────────────────────────────────────────────────────────

    def _dso_list(self, config, gast_h: float) -> list[SkyObject]:
        """
        Compute alt/az for the built-in DSO catalog using GAST-based
        spherical trig.  No ephemeris required.
        """
        try:
            result: list[SkyObject] = []
            for name, obj_type, ra_d, dec_d, mag in _BUILTIN_DSOS:
                alt, az = _radec_to_altaz(
                    ra_d, dec_d,
                    config.lat, config.lon,
                    gast_h,
                )
                if alt < -3.0:
                    continue
                result.append(SkyObject(
                    name       = name,
                    obj_type   = obj_type,
                    ra_deg     = ra_d,
                    dec_deg    = dec_d,
                    az         = az,
                    alt        = alt,
                    magnitude  = mag,
                    catalog_id = name,
                ))
            return result
        except Exception as exc:
            print(f"[catalog] DSO compute error: {exc}")
            return []

    # ── Hipparcos star list (vectorised) ──────────────────────────────────────

    def _star_list(self, config, gast_h: float) -> list[SkyObject]:
        """
        Compute alt/az for Hipparcos stars using vectorised GAST-based
        spherical trig.  No ephemeris required.
        """
        try:
            lim  = config.limiting_magnitude
            df_v = _hip_df[_hip_df["magnitude"] <= lim].copy()
            if df_v.empty:
                return []
            if len(df_v) > 6_000:
                df_v = df_v.nsmallest(6_000, "magnitude")

            ra_arr  = df_v["ra_degrees"].values.astype(np.float64)
            dec_arr = df_v["dec_degrees"].values.astype(np.float64)

            alt_arr, az_arr = _radec_to_altaz_vec(
                ra_arr, dec_arr,
                config.lat, config.lon,
                gast_h,
            )

            result: list[SkyObject] = []
            for i, (hip_id, row) in enumerate(df_v.iterrows()):
                if alt_arr[i] < -2.0:
                    continue
                result.append(SkyObject(
                    name       = f"HIP {hip_id}",
                    obj_type   = "Star",
                    ra_deg     = float(row["ra_degrees"]),
                    dec_deg    = float(row["dec_degrees"]),
                    az         = float(az_arr[i]),
                    alt        = float(alt_arr[i]),
                    magnitude  = float(row["magnitude"]),
                    catalog_id = f"HIP {hip_id}",
                ))
            return result
        except Exception as exc:
            print(f"[catalog] star list error: {exc}")
            return []

    # ── nearest-object lookup ─────────────────────────────────────────────────

    @staticmethod
    def find_nearest(
        px:      float,
        py:      float,
        objects: list[SkyObject],
    ) -> Optional[SkyObject]:
        if not objects:
            return None
        best_d2, best = float("inf"), None
        for obj in objects:
            d2 = (obj.px - px) ** 2 + (obj.py - py) ** 2
            if d2 < best_d2:
                best_d2, best = d2, obj
        return best

# ── mock config so we can reuse VisibleCatalog._dso_list / _star_list ─────────

class _CatalogConfig:
    """Duck-type for the config object consumed by VisibleCatalog internals."""
    def __init__(
        self,
        lat:               float,
        lon:               float,
        elevation_m:       float,
        limiting_magnitude: float,
    ) -> None:
        self.lat               = lat
        self.lon               = lon
        self.elevation_m       = elevation_m
        self.limiting_magnitude = limiting_magnitude

class FullSkyCatalog:
    """
    Builds a list of all sky objects visible above the horizon (alt > −5°)
    without any FOV restriction.

    No pixel coordinates are computed — only Az/Alt and RA/Dec are stored.
    Objects are ready for use in sky2 click-to-select.
    """

    _delegate = VisibleCatalog()   # reuse _dso_list, _star_list, _gast

    # ── async build ───────────────────────────────────────────────────────────

    async def build(
        self,
        lat:               float,
        lon:               float,
        elevation_m:       float,
        use_current_time:  bool,
        manual_dt:         datetime,
        limiting_magnitude: float,
    ) -> list[SkyObject]:
        await _ensure_hipparcos_loaded()
        return await asyncio.to_thread(
            self._build_sync,
            lat, lon, elevation_m,
            use_current_time, manual_dt,
            limiting_magnitude,
        )

    # ── sync build (thread pool) ──────────────────────────────────────────────

    def _build_sync(
        self,
        lat:               float,
        lon:               float,
        elevation_m:       float,
        use_current_time:  bool,
        manual_dt:         datetime,
        limiting_magnitude: float,
    ) -> list[SkyObject]:
        # Resolve observation time
        if use_current_time:
            dt = datetime.now(timezone.utc)
        else:
            dt = manual_dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        gast_h = self._delegate._gast(dt)
        cfg    = _CatalogConfig(lat, lon, elevation_m, limiting_magnitude)

        objects: list[SkyObject] = []

        # DSOs (built-in catalog)
        objects += self._delegate._dso_list(cfg, gast_h)

        # Hipparcos stars up to limiting magnitude
        if _hip_df is not None:
            objects += self._delegate._star_list(cfg, gast_h)

        # Keep only objects above the horizon
        return [o for o in objects if o.alt > -5.0]

    # ── nearest-object lookup ─────────────────────────────────────────────────

    @staticmethod
    def find_nearest_altaz(
        az:          float,
        alt:         float,
        objects:     list[SkyObject],
        max_sep_deg: float = 10.0,
    ) -> Optional[SkyObject]:
        """
        Return the catalog object with the smallest great-circle angular
        separation from (az, alt), within max_sep_deg degrees.
        Returns None if no object is within the tolerance.
        """
        if not objects:
            return None

        a1r  = math.radians(az)
        e1r  = math.radians(alt)
        s1a  = math.sin(e1r)
        c1a  = math.cos(e1r)

        best_sep = float(max_sep_deg)
        best_obj = None

        for obj in objects:
            a2r = math.radians(obj.az)
            e2r = math.radians(obj.alt)
            cos_c = max(-1.0, min(1.0,
                s1a * math.sin(e2r)
                + c1a * math.cos(e2r) * math.cos(a1r - a2r)
            ))
            sep = math.degrees(math.acos(cos_c))
            if sep < best_sep:
                best_sep = sep
                best_obj = obj

        return best_obj


# ── coordinate helpers (used by page) ─────────────────────────────────────────

def cartesian_to_altaz(x: float, y: float, z: float) -> tuple[float, float]:
    """
    Inverse of _altaz_to_cartesian from sky2 page.
    THREE.js convention: Y=up, Az 0=North=+Z, Az 90=East=+X.
    """
    r   = math.sqrt(x * x + y * y + z * z)
    if r < 1e-9:
        return 0.0, 0.0
    alt = math.degrees(math.asin(max(-1.0, min(1.0, y / r))))
    az  = math.degrees(math.atan2(x, z)) % 360.0
    return az, alt


