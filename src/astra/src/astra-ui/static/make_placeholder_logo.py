"""
Generates placeholder MIT Haystack Observatory logo PNGs into this directory.
Run once:  poetry run python astra/static/make_placeholder_logo.py

Replace the generated files with the real logo at any time; the app hot-reloads.
"""

from __future__ import annotations

import os
import sys

# allow running from any working directory
HERE = os.path.dirname(os.path.abspath(__file__))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


def _draw_dish(ax, cx, cy, r, color, lw=1.2):
    """Stylised parabolic dish glyph."""
    t = np.linspace(np.pi, 2 * np.pi, 120)
    x = cx + r * np.cos(t)
    y = cy + r * 0.38 * np.sin(t)
    ax.plot(x, y, color=color, lw=lw, solid_capstyle="round")
    # support strut
    ax.plot([cx, cx], [cy - r * 0.38, cy - r * 0.55],
            color=color, lw=lw * 0.8, solid_capstyle="round")
    # focus point
    ax.plot(cx, cy + r * 0.13, "o",
            color=color, markersize=r * 18, zorder=5)


def _make(bg: str, fg: str, filename: str) -> None:
    fig, ax = plt.subplots(figsize=(3.6, 0.9), facecolor=bg)
    ax.set_xlim(0, 3.6)
    ax.set_ylim(0, 0.9)
    ax.set_facecolor(bg)
    ax.axis("off")

    # ── dish glyph ────────────────────────────────────────────────────────────
    _draw_dish(ax, cx=0.44, cy=0.50, r=0.30, color=fg, lw=1.8)

    # ── MIT wordmark ──────────────────────────────────────────────────────────
    ax.text(
        0.84, 0.72, "MIT",
        color=fg, fontsize=9.5, fontweight="bold",
        va="center", ha="left", fontfamily="monospace",
        transform=ax.transData,
    )

    # ── Haystack Observatory text ─────────────────────────────────────────────
    ax.text(
        0.84, 0.36, "Haystack Observatory",
        color=fg, fontsize=6.2, fontweight="normal",
        va="center", ha="left",
        transform=ax.transData,
        alpha=0.90,
    )

    out = os.path.join(HERE, filename)
    fig.savefig(out, dpi=160, bbox_inches="tight",
                facecolor=bg, transparent=(bg == "none"))
    plt.close(fig)
    print(f"  wrote  {out}")


if __name__ == "__main__":
    print("Generating placeholder logos …")
    _make(bg="#0f172a", fg="#e2e8f0", filename="haystack_logo_white.png")
    _make(bg="#ffffff", fg="#1e293b", filename="haystack_logo.png")
    print("Done.  Replace with the official logo whenever you like.")