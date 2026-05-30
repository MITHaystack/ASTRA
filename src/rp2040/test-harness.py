# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
#
# SPDX-License-Identifier: Unlicense
"""
Author: Mark Roberts (mdroberts1243) from Adafruit code
This test will initialize the display using displayio and draw a solid white
background, a smaller black rectangle, miscellaneous stuff and some white text.

"""

import board
import displayio
import terminalio
import busio
import time
import adafruit_gps
import adafruit_bno055
from adafruit_bme280 import basic as adafruit_bme280
# can try import bitmap_label below for alternative
from adafruit_display_text import label
from i2cdisplaybus import I2CDisplayBus

import adafruit_displayio_sh1107

displayio.release_displays()
# oled_reset = board.D9

# Use for I2C
b_i2c = board.I2C()  # uses board.SCL and board.SDA
# i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
display_bus = I2CDisplayBus(b_i2c, device_address=0x3C)

# SH1107 is vertically oriented 64x128
WIDTH = 128
HEIGHT = 64
BORDER = 2

display = adafruit_displayio_sh1107.SH1107(display_bus, width=WIDTH, height=HEIGHT)

# Create a serial connection for the GPS connection using default speed and
# a slightly higher timeout (GPS modules typically update once a second).
# These are the defaults you should use for the GPS FeatherWing.
# For other boards set RX = GPS module TX, and TX = GPS module RX pins.
#uart = busio.UART(board.TX, board.RX, baudrate=9600, timeout=10)

# for a computer, use the pyserial library for uart access
# import serial
# uart = serial.Serial("/dev/ttyUSB0", baudrate=9600, timeout=10)

# If using I2C, we'll create an I2C interface to talk to using default pins
# i2c = board.I2C()  # uses board.SCL and board.SDA
i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
gps = adafruit_gps.GPS_GtopI2C(i2c, debug=False)  # Use I2C interface
bme280 = adafruit_bme280.Adafruit_BME280_I2C(b_i2c)
# Initialize the GPS module by changing what data it sends and at what rate.
# These are NMEA extensions for PMTK_314_SET_NMEA_OUTPUT and
# PMTK_220_SET_NMEA_UPDATERATE but you can send anything from here to adjust
# the GPS module behavior:
#   https://cdn-shop.adafruit.com/datasheets/PMTK_A11.pdf

# Turn on the basic GGA and RMC info (what you typically want)
#gps.send_command(b"PMTK314,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0")
# Turn on just minimum info (RMC only, location):
# gps.send_command(b'PMTK314,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0')
# Turn off everything:
# gps.send_command(b'PMTK314,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0')
# Tuen on everything (not all of it is parsed!)
gps.send_command(b'PMTK314,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0')

# Set update rate to once a second (1hz) which is what you typically want.
#gps.send_command(b"PMTK220,1000")
# Or decrease to once every two seconds by doubling the millisecond value.
# Be sure to also increase your UART timeout above!
gps.send_command(b'PMTK220,3000')
# You can also speed up the rate, but don't go too fast or else you can lose
# data during parsing.  This would be twice a second (2hz, 500ms delay):
# gps.send_command(b'PMTK220,500')

# Main loop runs forever printing the location, etc. every second.
cnt = 0
last_print = time.monotonic()
# Use these lines for I2C
#i2c = busio.I2C(board.SCL, board.SDA)
imu = adafruit_bno055.BNO055_I2C(i2c)

# User these lines for UART
# uart = busio.UART(board.TX, board.RX)
# sensor = adafruit_bno055.BNO055_UART(uart)

last_val = 0xFFFF


def temperature():
    global last_val  # pylint: disable=global-statement
    result = imu.temperature
    if abs(result - last_val) == 128:
        result = imu.temperature
        if abs(result - last_val) == 128:
            return 0b00111111 & result
    last_val = result
    return result


while True:
    print("Temp : {} C".format(imu.temperature))
    """
    print(
        "Temperature: {} degrees C".format(temperature())
    )  # Uncomment if using a Raspberry Pi
    """
    time.sleep(2)
    print("Acc: {}".format(imu.acceleration))
    print("Mag: {}".format(imu.magnetic))
    print("Gyr: {}".format(imu.gyro))
    time.sleep(2)
    print("Elr: {}".format(imu.euler))
    print("Qua: {}".format(imu.quaternion))
    time.sleep(2)
    print("LnA: {}".format(imu.linear_acceleration))
    print("G: {}".format(imu.gravity))
    time.sleep(2)

    print("\nTemp: %0.1f C" % bme280.temperature)
    print("RH: %0.1f %%" % bme280.humidity)
    print("P: %0.1f hPa" % bme280.pressure)
    time.sleep(2)

    # Make sure to call gps.update() every loop iteration and at least twice
    # as fast as data comes from the GPS unit (usually every second).
    # This returns a bool that's true if it parsed new data (you can ignore it
    # though if you don't care and instead look at the has_fix property).
    gps.update()
    # Every second print out current location details if there's a fix.
    current = time.monotonic()
    if current - last_print >= 1.0:
        last_print = current
        if not gps.has_fix:
            # Try again if we don't have a fix yet.
            print("Waiting for fix...{:03}".format(cnt))
            cnt = cnt + 1
            continue
        time.sleep(0.25)
        cnt = 0
        # We have a fix! (gps.has_fix is true)
        # Print out details about the fix like location, date, etc.
        print(
            "ts:{}-{}-{}T{:02}:{:02}:{:02}Z".format(  # noqa: UP032
                gps.timestamp_utc.tm_year,  # the fix time.  Note you might
                gps.timestamp_utc.tm_mon,  # Grab parts of the time from the
                gps.timestamp_utc.tm_mday,  # struct_time object that holds
                gps.timestamp_utc.tm_hour,  # not get all data like year, day,
                gps.timestamp_utc.tm_min,  # month!
                gps.timestamp_utc.tm_sec,
            )
        )
        print(f"lat: {gps.latitude:.4f} deg")
        print(f"lon: {gps.longitude:.4f} deg")
#        print(f"PLat: {gps.latitude_degrees} degs, {gps.latitude_minutes:2.3f} mins")
#        print(f"PLon: {gps.longitude_degrees} degs, {gps.longitude_minutes:2.3f} mins")

        print(f"alt:{gps.altitude_m}m")
        time.sleep(2)
        # Some attributes beyond latitude, longitude and timestamp are optional
        # and might not be present.  Check if they're None before trying to use!

        print(f"sat:{gps.satellites} fixQ: {gps.fix_quality}")
        print(f" sp:{gps.speed_kmh}kmh")
        print(f"tang:{gps.track_angle_deg}deg")
#        if gps.satellites is not None:
#            print(f"#sat: {gps.satellites}")
#        if gps.altitude_m is not None:
#            print(f"Alt: {gps.altitude_m} meters")
#        if gps.speed_kmh is not None:
#            print(f"Speed: {gps.speed_kmh} km/h")
#        if gps.track_angle_deg is not None:
#            print(f"Tangle: {gps.track_angle_deg} degrees")
#       if gps.horizontal_dilution is not None:
#            print(f"Hdil: {gps.horizontal_dilution}")
#        if gps.height_geoid is not None:
#            print(f"Hgeoid: {gps.height_geoid} meters")
        time.sleep(2)