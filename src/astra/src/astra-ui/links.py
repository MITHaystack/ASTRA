"""
External link registry for ASTRA.

Edit the URLs here; the navigation sidebar and any other page that imports
this module will pick up the changes automatically.
"""

# astra/links.py
import socket

# Tool Links
MARIMO_URL  = "localhost:2718"          # change port if needed
STELLARIUM_URL = "https://stellarium-web.org/"
ASTROMETRY_URL = "https://nova.astrometry.net/"

# ── GitHub Pages ───────────────────────────────────────────────────────────────
# Replace the org/repo slug once your Pages site is live.
_GITHUB_IO_BASE = "https://MITHaystack.github.io/ASTRA"

DOCS_URL    = f"{_GITHUB_IO_BASE}"
LESSONS_URL = f"{_GITHUB_IO_BASE}/lessons"
HELP_URL    = f"{_GITHUB_IO_BASE}/help"
ABOUT_URL   = f"{_GITHUB_IO_BASE}/about"
LICENSE_URL   = f"{_GITHUB_IO_BASE}/about/LICENSE.md"
HAYSTACK_URL = f"https://www.haystack.mit.edu"