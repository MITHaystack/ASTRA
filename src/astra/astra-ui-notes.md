# 1 — Generate placeholder logos (do this once after poetry install)
poetry run python astra/static/make_placeholder_logo.py

# 2 — (Optional) Replace with the real logo:
#     Download from https://www.haystack.mit.edu/about/media-resources/
#     and overwrite the two generated files:
cp ~/Downloads/haystack_logo_white.png  astra/static/haystack_logo_white.png
cp ~/Downloads/haystack_logo.png        astra/static/haystack_logo.png

# 3 — Start / hot-reload picks up the files automatically
poetry run astra

# Install new deps (starplot, skyfield, paho-mqtt)
poetry install

# Start — hot-reload is active
poetry run astra