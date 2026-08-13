from pathlib import Path

from nicegui import app, ui

from .state import astra_sub, astra_cmd, motion_history, imu_history, gps_history

from .pages import (
    antenna, settings, spectrometer, camera, sky, calibration,
)

@app.on_startup
async def _startup() -> None:

    # MongoDB history interface startup
    await motion_history.initialize()
    await imu_history.initialize()
    await gps_history.initialize()

    # ASTRA state subscriber — single aiomqtt task for all pages
    await astra_sub.start()
    await astra_cmd.start()

    print("[startup] ASTRA initialised")


def main() -> None:
    app.add_static_files(
        url_path        = "/static",
        local_directory = str(Path(__file__).parent / "static"),
    )

    antenna.create()
    settings.create()
    spectrometer.create()
    camera.create()
    sky.create()

    ui.run(
        title  = "ASTRA",
        port   = 8080,
        dark   = True,
        show   = False,
        reload = True,
        favicon= "🔭",
    )


if __name__ == "__main__":
    main()