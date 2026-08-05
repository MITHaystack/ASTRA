
import board
import displayio
import terminalio
import busio
import time
import asyncio
import queue
import usb_cdc
import json
import math
import traceback
import adafruit_gps
import adafruit_bno055
import adafruit_pcf8574
from adafruit_display_text import label
from i2cdisplaybus import I2CDisplayBus
import digitalio
import adafruit_displayio_sh1107

i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
gps = adafruit_gps.GPS_GtopI2C(i2c, debug=True)  # Use I2C interface
gps.send_command(b"PMTK314,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0")
gps.send_command(b"PMTK220,1000")
gps.update()

print(gps.timestamp_utc)
print(gps.satellites)
print(gps.has_fix)
print(gps.latitude)
print(gps.longitude)
print(gps.altitude_m)
print(gps.nmea_sentence)
