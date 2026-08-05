# ASTRA static assets

Place the following files here:

| File | Description |
|------|-------------|
| `haystack_logo.png`       | MIT Haystack Observatory logo — full colour (for light backgrounds) |
| `haystack_logo_white.png` | White / reversed version (for the dark header and drawer)           |

Download the official logo from:
  https://www.haystack.mit.edu/about/media-resources/

If neither file is present the UI falls back to a programmatically generated
SVG placeholder rendered by `astra/static/make_placeholder_logo.py`.

Run the placeholder generator once after `poetry install`:

    poetry run python astra/static/make_placeholder_logo.py