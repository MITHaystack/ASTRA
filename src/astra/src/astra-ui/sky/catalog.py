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
from scipy.spatial import KDTree
import cartopy.crs as ccrs

_SP_OK       = False
_Star        = None
_DSO         = None
_BIG_SKY_MAG9    = None
_OPEN_NGC        = None
_SP_VERSION  = "not found"

try:
    from starplot.models import Star as _Star, DSO as _DSO   # type: ignore
    from starplot.data.catalogs import (                      # type: ignore
        BIG_SKY_MAG9 as _BIG_SKY_MAG9,
        OPEN_NGC     as _OPEN_NGC,
    )
    from starplot import _ 
    import starplot as _sp
    _SP_VERSION = getattr(_sp, "__version__", "unknown")
    _SP_OK = True
    print(
        f"[catalog] starplot {_SP_VERSION} — "
        f"Star + DSO models loaded  "
        f"(BIG_SKY_MAG9 + OPEN_NGC)"
    )
except Exception as _sp_err:
    print(f"[catalog] starplot models unavailable: {_sp_err} — builtin DSOs only")

# ── optional skyfield timescale (for GAST) ─────────────────────────────────────
_sf_ts = None
try:
    from skyfield.api import Loader as _sf_Loader   # type: ignore
    import os as _os
    _cache_dir = _os.path.expanduser("~/.skyfield")
    _os.makedirs(_cache_dir, exist_ok=True)
    _sf_ts = _sf_Loader(_cache_dir).timescale()
    print("[catalog] skyfield timescale loaded")
except Exception as _ts_err:
    print(f"[catalog] skyfield unavailable: {_ts_err} — GMST fallback active")


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

def _gast(dt: datetime) -> float:
    """
    Return Greenwich Apparent Sidereal Time in decimal hours.
    Uses skyfield if available, otherwise falls back to GMST approximation.
    """
    try:
        if _sf_ts is not None:
            return float(_sf_ts.from_datetime(dt).gast)
    except Exception:
        pass
    # GMST fallback (accurate to ~0.01° for display)
    jd  = (
        (dt - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds()
        / 86400.0 + 2451545.0
    )
    t   = (jd - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t ** 2
        - t ** 3 / 38710000.0
    ) % 360.0
    return gmst_deg / 15.0


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

# ── RA/Dec formatting helpers (used by sky pages) ─────────────────────────────
def format_ra(ra_deg: float) -> str:
    ra = ra_deg / 15.0
    h  = int(ra)
    m_ = (ra - h) * 60.0
    m  = int(m_)
    s  = (m_ - m) * 60.0
    return f"{h:02d}h {m:02d}m {s:05.2f}s"


def format_dec(dec_deg: float) -> str:
    sign  = "+" if dec_deg >= 0 else "−"
    d_abs = abs(dec_deg)
    d     = int(d_abs)
    m_    = (d_abs - d) * 60.0
    m     = int(m_)
    s     = (m_ - m) * 60.0
    return f"{sign}{d:02d}° {m:02d}′ {s:04.1f}″"

# ── starplot DSO type → readable string ──────────────────────────────────────

def _dso_type_name(dso_type) -> str:
    """Convert a starplot DsoType enum value to a display string."""
    try:
        name = str(dso_type.name if hasattr(dso_type, "name") else dso_type)
        return name.replace("_", " ").title()
    except Exception:
        return "DSO"


def _dso_catalog_id(obj) -> str:
    """Build a human-readable catalog ID for a starplot DSO object."""
    try:
        messier = getattr(obj, "messier", None)
        if messier:
            return f"M{messier}"
        ngc = getattr(obj, "ngc", None)
        if ngc:
            return f"NGC {ngc}"
        ic = getattr(obj, "ic", None)
        if ic:
            return f"IC {ic}"
        name = getattr(obj, "name", None)
        if name:
            return str(name)
    except Exception:
        pass
    return f"DSO {obj.ra:.2f}"


def _dso_display_name(obj) -> str:
    """Best display name for a starplot DSO."""
    try:
        messier = getattr(obj, "messier", None)
        name    = getattr(obj, "name",    None)
        if name and messier:
            return f"M{messier} {name}"
        if name:
            return str(name)
        if messier:
            return f"M{messier}"
        ngc = getattr(obj, "ngc", None)
        if ngc:
            return f"NGC {ngc}"
        ic = getattr(obj, "ic", None)
        if ic:
            return f"IC {ic}"
    except Exception:
        pass
    return f"DSO RA {obj.ra:.1f}°"


def _star_display_name(obj) -> str:
    """Best display name for a starplot Star."""
    try:
        name  = getattr(obj, "name",              None)
        bayer = getattr(obj, "bayer_designation",  None)
        flam  = getattr(obj, "flamsteed_designation", None)
        hip   = getattr(obj, "hip",               None)
        if name:
            return str(name)
        if bayer:
            return str(bayer)
        if flam:
            return str(flam)
        if hip:
            return f"HIP {hip}"
    except Exception:
        pass
    return f"Star RA {obj.ra:.1f}°"

# ── catalog class ─────────────────────────────────────────────────────────────

class SkyCatalog:
    """
    Unified sky catalog builder + nearest-object finder.

    Usage::

        catalog = SkyCatalog()

        # Build a list of currently visible objects:
        objects = await catalog.build(
            lat=42.6, lon=-71.5, elevation_m=131,
            use_current_time=True,
            manual_dt=datetime.now(timezone.utc),
            limiting_magnitude=6.5,
        )

        # Find nearest object to a clicked sky position:
        obj = SkyCatalog.find_nearest_altaz(az, alt, objects, max_sep_deg=10)
    """

    def __init__(self):
        self._catalog = None
        self._gast_h = None
        self._obj_index = None
        self._pixel_tree = None

    # --- pixel space mapping'
    # Note the 0.45 is from the ZenithPlot map scaling
    def _altaz_to_norm_pixel(self, az_d, alt_d, cx=0.5, cy=0.5, mxr=0.45):

        az_r = np.deg2rad(az_d)
        alt_r = np.deg2rad(alt_d)

        zd = (np.pi / 2.0) - alt_r

        if zd > (np.pi / 2.0):
            return None, None

        r = mxr * np.tan(zd / 2.0)
        x = cx + r * np.sin(az_r)
        y = cy - r * np.cos(az_r)

        return 1.0-x, y



    def _radec_to_norm_pixel(self, ra_deg, dec_deg, gast_hours, lat_deg, lon_deg, img_width=1.0, img_height=1.0, max_zenith_deg=90):
        """
        Transforms RA/Dec celestial coordinates into flat pixel coordinates 
        for a Zenith Chart using Cartopy.
        """
        #print(f" radec2np : {ra_deg} {dec_deg} {gast_hours} {lat_deg} {lon_deg}")

        # 1. Calculate Local Sidereal Time (LST) in degrees
        gast_deg = gast_hours * 15.0
        lst_deg = (gast_deg + lon_deg) % 360.0

        raw_lon = ra_deg - gast_deg
        adj_lon = ((raw_lon + 180) % 360) - 180

        # 2. Map Celestial Sphere coordinates to Earth-like Geography (PlateCarree equivalents)
        # Right Ascension increases Eastward, Local Hour Angle maps RA onto Longitude.
        # LHA = LST - RA. To align with a standard zenith map:
        star_lon = adj_lon
        star_lat = dec_deg

        #print(f". radec2np : {star_lon} {star_lat}")

        # 3. Define the source coordinate frame (Geodetic / Unprojected Sky)
        source_crs = ccrs.Geodetic()

        # 4. Define the Zenith Plot Projection centered exactly on the Observer's Zenith
        # Zenith Map centers: Longitude = LST, Latitude = Observer's Latitude
        target_crs = ccrs.Stereographic(
            central_longitude=lst_deg, 
            central_latitude=lat_deg
        )

        # 5. Transform celestial position into native projection space (planar meters)
        projected_point = target_crs.transform_point(star_lon, star_lat, source_crs)
        x_meters, y_meters = projected_point[0], projected_point[1]

        # Handle points behind the horizon / out of structural projection boundaries
        if np.isnan(x_meters) or np.isnan(y_meters):
            return None  # Point is outside projection visibility

        #print(f". radec2np : {x_meters} {y_meters}")

        # 6. Calculate Planar Bounding Limits in Meters based on max zenith degree cutoff
        # 1 degree roughly equals 111,319.49 meters on a spherical model
        meters_per_degree = 6371007.2 * np.pi / 180.0 
        max_radius_meters = max_zenith_deg * meters_per_degree

        # 7. Map planar meters linearly to the designated Pixel Grid dimensions
        # Assuming center of image (width/2, height/2) corresponds to (0,0) meters
        pixel_x = (img_width / 2.0) + (x_meters / max_radius_meters) * (img_width / 2.0)
        
        # Invert Y-axis because pixel screens count (0,0) from the top-left corner
        pixel_y = (img_height / 2.0) - (y_meters / max_radius_meters) * (img_height / 2.0)

        #print(f". radec2np : {pixel_x, pixel_y}")

        # Optional: Filter out stars outside the valid canvas frame boundary
        if 0 <= pixel_x <= img_width and 0 <= pixel_y <= img_height:
            return pixel_x, pixel_y
        
        return None

    # ── async entry point ─────────────────────────────────────────────────────

    async def build(
        self,
        lat:               float,
        lon:               float,
        elevation_m:       float,
        use_current_time:  bool,
        manual_dt:         datetime,
        limiting_magnitude: float = 6.5,
    ) -> list[SkyObject]:
        """
        Build and return the full list of sky objects visible above −5° altitude.
        Blocking work runs in asyncio.to_thread so the event loop is not blocked.
        """
        return await asyncio.to_thread(
            self._build_sync,
            lat, lon, elevation_m,
            use_current_time, manual_dt,
            limiting_magnitude,
        )

    # ── synchronous build (runs in thread pool) ───────────────────────────────

    def _build_sync(
        self,
        lat:               float,
        lon:               float,
        elevation_m:       float,
        use_current_time:  bool,
        manual_dt:         datetime,
        limiting_magnitude: float,
    ) -> list[SkyObject]:
        # Resolve observation datetime
        if use_current_time:
            dt = datetime.now(timezone.utc)
        else:
            dt = manual_dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        gast_h = _gast(dt)
        self._gast_h = gast_h
        objects: list[SkyObject] = []

        # 1 — Built-in DSOs (always included)
        objects.extend(
            self._builtin_dsos(lat, lon, gast_h, limiting_magnitude)
        )

        # 2 — Starplot stars from BIG_SKY_MAG9
        if _SP_OK and _Star is not None and _BIG_SKY_MAG9 is not None:
            objects.extend(
                self._starplot_stars(lat, lon, gast_h, limiting_magnitude)
            )

        # 3 — Starplot DSOs from OPEN_NGC
        #if _SP_OK and _DSO is not None and _OPEN_NGC is not None:
        #    objects.extend(
        #        self._starplot_dsos(lat, lon, gast_h, limiting_magnitude)
        #    )

        # Filter to objects above the horizon
        self._catalog = [o for o in objects if o.alt > -5.0]

        # compute pixel location for ZenithPlot via forward mapping in normalized pixel space
        self._obj_index = []
        pixel_list = np.empty((0,2))

        for obj in self._catalog:
            try:
                #xpix,ypix = self._radec_to_norm_pixel(obj.ra_deg, obj.dec_deg, self._gast_h, lat, lon)
                xpix,ypix = self._altaz_to_norm_pixel(obj.az, obj.alt)
            except:
                #print(f"problem radec to pixel for object {obj}")
                continue
            #print(f"object {obj.name} maps to {xpix},{ypix}")
            if xpix is None or ypix is None:
                continue

            # fill in the pixel value for the object
            obj.px = xpix
            obj.py = ypix

            pair = np.array([xpix, ypix])
            pixel_list = np.vstack([pixel_list,pair])
            self._obj_index.append(obj)

        # store as a KD-tree for fast lookup
        self._pixel_tree = KDTree(pixel_list)

        return self._catalog

    # ── source loaders ────────────────────────────────────────────────────────

    def _builtin_dsos(
        self,
        lat:               float,
        lon:               float,
        gast_h:            float,
        limiting_magnitude: float,
    ) -> list[SkyObject]:
        """Load the hand-curated _BUILTIN_DSOS with current alt/az."""
        result: list[SkyObject] = []
        for name, obj_type, ra_d, dec_d, mag in _BUILTIN_DSOS:
            # Include even faint objects from the builtin list —
            # they are all important radio / named sources
            alt, az = _radec_to_altaz(ra_d, dec_d, lat, lon, gast_h)
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

    def _starplot_stars(
        self,
        lat:               float,
        lon:               float,
        gast_h:            float,
        limiting_magnitude: float,
    ) -> list[SkyObject]:
        """
        Load stars from starplot BIG_SKY_MAG9 up to limiting_magnitude.
        Uses vectorised alt/az computation for speed.
        """
        try:
            stars = _Star.find(
                catalog = _BIG_SKY_MAG9,
                where   = [_.magnitude <= limiting_magnitude],
            )
            if not stars:
                return []

            ra_arr  = np.array([s.ra  for s in stars], dtype=np.float64)
            dec_arr = np.array([s.dec for s in stars], dtype=np.float64)

            alt_arr, az_arr = _radec_to_altaz_vec(
                ra_arr, dec_arr, lat, lon, gast_h
            )

            result: list[SkyObject] = []
            for i, s in enumerate(stars):
                alt = float(alt_arr[i])
                az  = float(az_arr[i])
                # Pre-filter to above horizon for speed
                if alt < -1.0:
                    continue

                # create entry
                disp_name = _star_display_name(s)
                hip       = getattr(s, "hip", None)
                cat_id    = f"HIP {hip}" if hip else disp_name
                result.append(SkyObject(
                    name       = disp_name,
                    obj_type   = "Star",
                    ra_deg     = float(s.ra),
                    dec_deg    = float(s.dec),
                    az         = az,
                    alt        = alt,
                    magnitude  = float(s.magnitude) if s.magnitude is not None else None,
                    catalog_id = cat_id,
                ))
            return result

        except Exception as exc:
            print(f"[catalog] starplot star load error: {exc}")
            return []

    def _starplot_dsos(
        self,
        lat:               float,
        lon:               float,
        gast_h:            float,
        limiting_magnitude: float,
    ) -> list[SkyObject]:
        """
        Load DSOs from starplot OPEN_NGC up to limiting_magnitude.
        Objects with no magnitude are included (many bright DSOs lack mag data).
        """
        try:
            # Query: magnitude <= limit, OR magnitude is None (unknown/extended)
            dsos = _DSO.find(
                catalog = _OPEN_NGC,
                where   = [
                    (_.magnitude <= limiting_magnitude)
                ],
            )
            if not dsos:
                return []

            ra_arr  = np.array([d.ra  for d in dsos], dtype=np.float64)
            dec_arr = np.array([d.dec for d in dsos], dtype=np.float64)

            alt_arr, az_arr = _radec_to_altaz_vec(
                ra_arr, dec_arr, lat, lon, gast_h
            )

            result: list[SkyObject] = []
            for i, d in enumerate(dsos):
                alt = float(alt_arr[i])
                az  = float(az_arr[i])
                if alt < -5.0:
                    continue
                mag = getattr(d, "magnitude", None)
                result.append(SkyObject(
                    name       = _dso_display_name(d),
                    obj_type   = _dso_type_name(getattr(d, "type", "DSO")),
                    ra_deg     = float(d.ra),
                    dec_deg    = float(d.dec),
                    az         = az,
                    alt        = alt,
                    magnitude  = float(mag) if mag is not None else None,
                    catalog_id = _dso_catalog_id(d),
                ))
            return result

        except Exception as exc:
            print(f"[catalog] starplot DSO load error: {exc}")
            return []

    # ── nearest-object query ──────────────────────────────────────────────────

    def find_nearest_object(self, pix_x, pix_y, res_val, scale_val):
        if self._pixel_tree is None or self._obj_index is None:
            return None

        # convert to normalized pixel space
        npix_x = (pix_x / scale_val) / (res_val)
        npix_y = (pix_y / scale_val) / (res_val)

        search_pixel = np.array([npix_x, npix_y])
        #print(f"search pixel is {pix_x},{pix_y} as {npix_x} {npix_y}")

        distance, index = self._pixel_tree.query(search_pixel)
        
        nobj = self._obj_index[index]

        #print(f"nobj is {nobj.name}")

        return nobj
        

    @staticmethod
    def find_nearest_altaz(
        az:          float,
        alt:         float,
        objects:     list[SkyObject],
        max_sep_deg: float = 2.0,
    ) -> Optional[SkyObject]:
        """
        Return the catalog object with the smallest great-circle angular
        separation from (az, alt), within max_sep_deg degrees.
        Returns None if no object falls within the tolerance.
        """
        if not objects:
            return None

        e1r = math.radians(alt)
        a1r = math.radians(az)
        s1  = math.sin(e1r)
        c1  = math.cos(e1r)

        best_sep = float(max_sep_deg)
        best_obj: Optional[SkyObject] = None

        for obj in objects:
            e2r   = math.radians(obj.alt)
            a2r   = math.radians(obj.az)
            cos_c = max(-1.0, min(1.0,
                s1 * math.sin(e2r)
                + c1 * math.cos(e2r) * math.cos(a1r - a2r)
            ))
            sep = math.degrees(math.acos(cos_c))
            if sep < best_sep:
                best_sep = sep
                best_obj = obj

        return best_obj