"""
Orthographic sky projection
============================
Maps sky coordinates (az, alt) ↔ image pixel coordinates (px, py).

Centre of projection is (az_c, alt_c).  FOV is the full angular *diameter*
of the displayed field in degrees.  Image is W×H pixels; the FOV fits within
min(W, H).

References
----------
Snyder, J.P. (1987) Map Projections – A Working Manual, USGS pp. 145–153.
"""

from __future__ import annotations
import math
from typing import Optional


def sky_to_pixel(
    az:      float,
    alt:     float,
    az_c:    float,
    alt_c:   float,
    fov_deg: float,
    W:       int,
    H:       int,
) -> tuple[Optional[float], Optional[float]]:
    """
    Orthographic projection of (az, alt) onto image pixel (px, py).
    Returns (None, None) when the point is behind the tangent plane or
    outside the FOV circle.
    """
    az_r   = math.radians(az)
    alt_r  = math.radians(alt)
    az_cr  = math.radians(az_c)
    alt_cr = math.radians(alt_c)
    daz    = az_r - az_cr

    cos_c = (math.sin(alt_cr) * math.sin(alt_r) +
             math.cos(alt_cr) * math.cos(alt_r) * math.cos(daz))
    if cos_c < 0.0:
        return None, None                      # behind the tangent plane

    sep = math.acos(max(-1.0, min(1.0, cos_c)))
    if math.degrees(sep) > fov_deg * 0.51:
        return None, None                      # outside FOV

    # Orthographic projection components (Snyder eq. 20-3, 20-4)
    x =  math.cos(alt_r) * math.sin(daz)
    y = (math.cos(alt_cr) * math.sin(alt_r) -
         math.sin(alt_cr) * math.cos(alt_r) * math.cos(daz))

    # Scale so that sin(fov/2) maps to half the short side
    half  = min(W, H) * 0.5
    scale = half / math.sin(math.radians(fov_deg * 0.5))

    px = W * 0.5 + scale * x
    py = H * 0.5 - scale * y   # image y increases downward

    return px, py


def pixel_to_sky(
    px:      float,
    py:      float,
    az_c:    float,
    alt_c:   float,
    fov_deg: float,
    W:       int,
    H:       int,
) -> tuple[float, float]:
    """Inverse orthographic projection."""
    az_cr  = math.radians(az_c)
    alt_cr = math.radians(alt_c)

    half  = min(W, H) * 0.5
    scale = half / math.sin(math.radians(fov_deg * 0.5))

    x =  (px - W * 0.5) / scale
    y = -(py - H * 0.5) / scale   # flip y back

    rho = math.sqrt(x * x + y * y)
    if rho < 1e-9:
        return az_c, alt_c

    rho = min(rho, 1.0)
    c   = math.asin(rho)

    alt_r = math.asin(
        math.cos(c) * math.sin(alt_cr) +
        y * math.sin(c) * math.cos(alt_cr) / rho
    )
    az_r = az_cr + math.atan2(
        x * math.sin(c),
        rho * math.cos(alt_cr) * math.cos(c) - y * math.sin(alt_cr) * math.sin(c),
    )
    return math.degrees(az_r) % 360.0, math.degrees(alt_r)


def angular_sep(az1: float, alt1: float, az2: float, alt2: float) -> float:
    """Great-circle angular separation between two alt-az points (degrees)."""
    a1r, e1r = math.radians(az1), math.radians(alt1)
    a2r, e2r = math.radians(az2), math.radians(alt2)
    cos_c = (math.sin(e1r) * math.sin(e2r) +
             math.cos(e1r) * math.cos(e2r) * math.cos(a1r - a2r))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_c))))


def _pixel_to_altaz(px: float, py: float, res: int, scale:float) -> tuple[float, float]:
    """Image pixel → (az_deg, alt_deg).  North is up (−y direction)."""
    R_h = res / 2.0 * scale # horizon radius
    cx = cy = res / 2.0 # map center
    dx =  px - cx
    dy = -(py - cy)          # flip: image y increases downward
    r   = math.sqrt(dx * dx + dy * dy)
    alt = 90.0 * (1.0 - r / R_h)   # r=0→90°, r=res/2→0°, r=res→−90°

    if alt < 0:
        alt = 0.0

    # West = 90, North = 0
    az  = (math.degrees(math.atan2(dx, dy))) 
    az =  az % 360.
    
    return az, alt


def _altaz_to_vec(az_deg: float, alt_deg: float) -> tuple[float, float, float]:
    """Az/Alt → unit vector (THREE.js: Y=up, N=+Z, E=+X)."""
    az  = math.radians(az_deg)
    alt = math.radians(alt_deg)
    return (
        math.cos(alt) * math.sin(az),
        math.sin(alt),
        math.cos(alt) * math.cos(az),
    )


def _altaz_to_sphere(az_deg: float, alt_deg: float) -> tuple[float, float, float]:
    x, y, z = _altaz_to_vec(az_deg, alt_deg)
    return x * _R, y * _R, z * _R


# ── formatting helpers (also used by commander) ───────────────────────────────

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