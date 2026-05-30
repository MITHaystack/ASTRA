"""
    rpi-ai-control.py

    This is CircuitPython code for the Adafruit Feather Wing RP2040 board (). This code expects the RP2040 to be connected via
    pin headers to the Adafruit OLED 128x64 feather (4650) add on, a Adafruit 9-DOF Absolute Orientation IMU using the BNO055 (4646)
    using I2C, an Adafruit Mini GPS PA1010D (4415) via I2C, and a PCF8574 GPIO breakout (5545) via I2C which controls the enable of a 5V to 12V
    DC / DC converter and biases an RF noise diode source. 

"""

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

# devices - GNSS / GPS, 9 DoF IMU, GPIO
import adafruit_gps
import adafruit_bno055
import adafruit_pcf8574

# devices - 128x64 OLED display
# can try import bitmap_label below for alternative
from adafruit_display_text import label
from i2cdisplaybus import I2CDisplayBus
import digitalio

import adafruit_displayio_sh1107

VERSION = "v1.0.0a-20260530"


"""
    Convert euler to azimuth / altitude
    Assumes a sensor orientation with board top upward in case and adafruit logo to back near cover side.
"""
def quat_to_az_el(q):
    w,x,y,z = q
    vx = 1.0 - 2.0 * y**2 - 2.0 * z**2
    vy = 2.0 * x * y + 2.0 * w * z
    vz = 2.0 * x * z - 2.0 * w * y
    azimuth = math.atan2(vx,vy)
    elevation = math.asin(vz)
    return math.degrees(azimuth), math.degrees(elevation)


"""
    Connect to the USB cdc path for console output and data.
    Requires a host side process to manage the associated commands and telemetry.
"""
# Needs to be in boot.py
def connect_usb_cdc():
    # grab the data serial interface
    usb_serial = usb_cdc.data
    # set timeouts to avoid blocking
    usb_serial.timeout = 0.01
    usb_serial.write_timeout = 0.05
    return usb_serial

"""
    Use the I2C bus on the RP2040 via Stemma QT to connect to the GPS.
"""
def connect_gps(logQ):
    try:
        i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
        gps = adafruit_gps.GPS_GtopI2C(i2c, debug=False)  # Use I2C interface
    except Exception as e:
        e_event = {'event':'exception','source':'connect_gps','value':f"{e}"}
        logQ.put(e_event)
        gps = None
        
    return gps

"""
    Get an update from the GPS and translate the telemetry into an associated
    python dictionary object. This will ultimately get serialized to json and
    sent back to the host. 
"""
def telemetry_gps(gps):
    gps.update()

    gps_utc_time = "{:02}-{:02}-{:02}T{:02}:{:02}:{:02}Z".format(  
                    gps.timestamp_utc.tm_year,  
                    gps.timestamp_utc.tm_mon,  
                    gps.timestamp_utc.tm_mday, 
                    gps.timestamp_utc.tm_hour,  
                    gps.timestamp_utc.tm_min,  
                    gps.timestamp_utc.tm_sec) # no time but UTC in ISO8601

    gps_data = {
        'event' : 'gps-data',
        'utc'   : gps_utc_time,
        'adata' : gps.isactivedata,
        'fix'   : gps.has_fix,
        'fixQ'  : gps.fix_quality,
        'fixQ3d': gps.fix_quality_3d,
        'sats'  : gps.satellites,
        'track_angle_deg' : gps.track_angle_deg,
        'speed' : gps.speed_kmh,
        'hdil'  : gps.horizontal_dilution,
        'hgeoid': gps.height_geoid,
        'pdop'  : gps.pdop,
        'vdop'  : gps.vdop,
        'latitude'  : gps.latitude,
        'longitude' : gps.latitude,
        'altitude'  : gps.altitude_m,
        'nmea': gps.nmea_sentence
    }

    return gps_data

"""
    Use the I2C bus on the RP2040 via Stemma QT to connect to the BNO055 9 DoF IMU.
"""
def connect_imu(logQ):
    try:
        i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller

        imu = adafruit_bno055.BNO055_I2C(i2c)

        imu.accel_range = 0 # 2G
        imu.mode = adafruit_bno055.NDOF_MODE

    except Exception as e:
        e_event = {'event':'exception','source':'connect_imu','value':f"{e}"}
        logQ.put(e_event)
        imu = None
    
    return imu

"""
    Get an update from the IMU and translate the telemetry into an associated
    python dictionary object. This will ultimately get serialized to json and
    sent back to the host. 
"""
def telemetry_imu(imu):

    # read at once to keep consistent
    euler = imu.euler
    quaternion = imu.quaternion
    pointing = quat_to_az_el(quaternion)

    imu_data = {
        'event' : 'imu-data',
        'temperature' : imu.temperature,
        'calibrated' : imu.calibrated,
        'cal-status' : imu.calibration_status,
        'euler'      : euler,
        'pointing'   : pointing,
        'gravity'    : imu.gravity,
        'gyro'       : imu.gyro,
        'acceleration' : imu.acceleration,
        'linear_acceleration' : imu.linear_acceleration,
        'magnetic'  : imu.magnetic,
        'quaternion' : quaternion,
    }

    return imu_data

"""
    Use the I2C bus on the RP2040 via Stemma QT to connect to the PCF8574 GPIO chip.
"""
def connect_gpio(logQ):
    #print("connect gpio")
    try:
        i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
        diode_gpio = adafruit_pcf8574.PCF8574(i2c)
    except Exception as e:
        e_event = {'event':'exception','source':'connect_gpio','value':f"{e}"}
        logQ.put(e_event)
        diode_gpio = None
    
    return diode_gpio

"""
    Thread that gathers GPS telemetry at a specified rate
    and pushes it to the telemetry queue. Errors are logged to 
    the log queue. 
"""
async def gps_telemetry(telemetryQ,logQ, i2cSBL, gps,gps_period):
    while True:
        #print("update gps_telemetry")
        # GPS
        try:
            async with i2cSBL:
                gps_t = telemetry_gps(gps)
            await telemetryQ.put(gps_t)
        except Exception as e:
            e_event = {'event':'exception','source':'gps_telemetry','value':f"{e}"}
            await logQ.put(e_event)

        await asyncio.sleep(gps_period)

"""
    Thread that gathers IMU telemetry at a specified rate
    and pushes it to the telemetry queue. Errors are logged to 
    the log queue. 
"""
async def imu_telemetry(telemetryQ,logQ,i2cSBL,imu,imu_period):
    while True:
        #print("update imu_telemetry")
        # IMU
        try:
            async with i2cSBL:
                imu_t = telemetry_imu(imu)
            await telemetryQ.put(imu_t)
        except Exception as e:
            e_event = {'event':'exception','source':'imu_telemetry','value':f"{e}"}
            await logQ.put(e_event)
 
        await asyncio.sleep(imu_period)


"""
    Thread that handles noise diode commands. Currently
    this includes static enable, disable, and a pulse alternating 
    at the diode period.
"""
async def noise_diode_handler(diodeQ, logQ, i2cSBL, diode_gpio, diode_period):

    diode_state = 'DISABLE'
    diode_pulse_state = 0
   
    while True:
        #print("update noise_diode_handler")

        # noise diode
        try:
            try:
                ndata = diodeQ.get_nowait()
                if ndata['value'] == 'ENABLE':
                    diode_state = 'ENABLE'
                    status = {'event':'status', 'source':'noise_diode_handler', 'value':f"diode enable"}
                elif ndata['value'] == 'DISABLE':
                    diode_state = 'DISABLE'
                    status = {'event':'status', 'source':'noise_diode_handler', 'value':f"diode disable"}
                elif ndata['value'] == 'PULSE':
                    diode_state = 'PULSE'
                    status = {'event':'status', 'source':'noise_diode_handler', 'value':f"diode pulse"}
                else:
                    status = {'event':'status', 'source':'noise_diode_handler', 'value':f"unknown command {ndata['value']}"}

                await logQ.put(status)

            except:
                pass
            
            # lock I2C bus
            async with i2cSBL:
                # handle the state behavior
                if diode_state == 'ENABLE':
                    # turn on the diode
                    diode_gpio.write_gpio(0x01)
                elif diode_state == 'DISABLE':
                    # turn off the diode
                    diode_gpio.write_gpio(0x00)
                elif diode_state == 'PULSE':
                    # toggle the diode on and off at the update rate
                    if diode_pulse_state == 0:
                        diode_pulse_state = 1
                        diode_gpio.write_gpio(0x01)
                    else:
                        diode_pulse_state = 0
                        diode_gpio.write_gpio(0x00)
            
        except Exception as e:
            e_event = {'event':'exception','source':'noise_diode_handler','value':f"{e}"}
            await logQ.put(e_event)

        await asyncio.sleep(diode_period)

"""
    Connect to the OLED display using Use the I2C bus on the RP2040. This is actually hard 
    wired via the pin conections between the RP2040 feather and the OLED wing board. 
"""
def connect_display(logQ):

    try:
        displayio.release_displays()
        # oled_reset = board.D9

        # Use for I2C
        b_i2c = board.I2C()  # uses board.SCL and board.SDA
        # i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
        display_bus = I2CDisplayBus(b_i2c, device_address=0x3C)

        # SH1107 is vertically oriented 64x128
        WIDTH = 128
        HEIGHT = 64
        display = adafruit_displayio_sh1107.SH1107(display_bus, width=WIDTH, height=HEIGHT) 
       
    except Exception as e:
        e_event = {'event':'exception','source':'connect_display','value':f"{e}"}
        logQ.put(e_event)
        
    return display

"""
    Thread that handles display commands. Currently
    this includes a single basic output method. 
"""
async def display_handler(displayQ, logQ, display, display_period):

    # startup splash
    splash = displayio.Group()
    display.root_group = splash
    
    text_area = label.Label(terminalio.FONT, text="ASTRA", scale=2, color=0xFFFFFF, x=8, y=8)
    splash.append(text_area)
    text_area = label.Label(terminalio.FONT, text="MIT", color=0xFFFFFF, x=8, y=34)
    splash.append(text_area)
    text_area = label.Label(terminalio.FONT, text="Haystack Observatory", color=0xFFFFFF, x=8, y=44)
    splash.append(text_area)
    text_area = label.Label(terminalio.FONT, text=VERSION, color=0xFFFFFF, x=8, y=54)
    splash.append(text_area)
    
    # command based output
    while True:
        #print("update display_handler")
        output_data = None
        display_state = "STANDBY"

        # display
        try:
            try:
                ddata = displayQ.get_nowait()
                if ddata['value'] == 'OUTPUT':
                    display_state = 'OUTPUT'
                    output_data = ddata['data']
                    status = {'event':'status', 'source':'display_handler', 'value':f"output data {output_data}"}
                else:
                    display_state = 'STANDBY'
                    status = {'event':'status', 'source':'display_handler', 'value':f"unknown command {ndata['value']}"}
    
                # report handler status
                await logQ.put(status)

            except:
                pass

            # handle the state behavior
            if display_state == 'OUTPUT':
                out_text = output_data
                text_area = label.Label(terminalio.FONT, text=out_text, color=0xFFFFFF, x=8, y=8)
                splash.append(text_area)

        except Exception as e:
            e_event = {'event':'exception','source':'display_handler','value':f"{e}"}
            await logQ.put(e_event)

        await asyncio.sleep(display_period)
    
"""
    The command handler takes in an event if available and dispatches it to the
    appropriate handler. 
"""
async def command_handler(eventQ, logQ, diodeQ, displayQ, cmd_period):
    while True:
        #print("update command handler")
        try:
            cmd = eventQ.get_nowait()
            if cmd['event'] == 'noise_diode':
                await diodeQ.put(cmd)
            elif cmd['event'] == 'print':
                print(cmd['value'])
            elif cmd['event'] == 'display':
                await displayQ.put(cmd)
            
            status = {'event':'status', 'source':'command_handler', 'value':f"dispatched {cmd}"}
            await logQ.put(status)

        except:
            pass


        await asyncio.sleep(cmd_period)

"""
    The usb communications thread takes telemetry and log information and outputs it
    to the USB CDC data interface. Incoming data are also read in a single line format
    and the associated command is converted from a json to python object and queued for
    command processing. The associated timeouts of the usb_cdc interface are assumed to be
    set to prvent blocking. If the bus is not connected telemetry and log data are output to the 
    REPL as normal print out of the associated objects. No attempt to read a command is made
    for a disconnected bus. 
"""
async def usb_communications(telemetryQ, eventQ, logQ, usb_serial, com_period):
    while True:
        #print("update usb_communications")
        # send telemetry if available
        try:
            tdata = telemetryQ.get_nowait()
            if tdata is not None:
                tdata_json = json.dumps(tdata)
                if usb_serial.connected:
                    usb_serial.write(tdata_json)
                    usb_serial.write("\n")
                else:
                    print(tdata)
        except Exception as e:
            pass

        # send log data if available
        try:
            ldata = logQ.get_nowait()
            if ldata is not None:
                ldata_json = json.dumps(ldata)
                if usb_serial.connected:
                    usb_serial.write(ldata_json)
                    usb_serial.write("\n")
                else:
                    print(ldata)
        except:
            pass

        # get a python dictionary command as a json object
        try:
            if usb_serial.connected:
                try:
                    line = usb_serial.readline()
                except:
                    pass
                if line is not None and len(line) > 0:
                    cmd = json.loads(line)
                    await eventQ.put(cmd)
        except ValueError as e:
                print(f"JSON syntax error: {line}")
        except Exception as e:
                e_event = {'event':'exception','source':'usb_communications','value':f"{e}"}
                await logQ.put(e_event)

        await asyncio.sleep(com_period)

"""
    Primary Thread Startup 
"""
async def main():
    print("rp-ai-control startup")

    print("create async control")
    eventQ = queue.Queue()
    telemetryQ = queue.Queue()
    logQ = queue.Queue()
    diodeQ = queue.Queue()
    displayQ = queue.Queue()
    i2cSBL = asyncio.Lock()

    print("set update periods")
    # set update periods in seconds
    com_period = 0.1
    gps_period = 1.0
    imu_period = 1.0
    cmd_period = 0.1
    diode_period = 1.0
    display_period = 1.0
 
    # connect data path via USB, expects serial handler device on other end
    # some of this happens in boot.py, timeouts get set here...
    print("connect usb serial")
    usb_serial = connect_usb_cdc()
 
    print("activate interfaces")
    # activate the display interface
    display = connect_display(logQ)
    # activate the GPS interface
    gps = connect_gps(logQ)
    # activate the IMU interface
    imu = connect_imu(logQ)
    # activate the GPIO interface
    diode_gpio = connect_gpio(logQ)

    print("setup asyncio tasks")
    clients = [asyncio.create_task(usb_communications(telemetryQ, eventQ, logQ, usb_serial, com_period))]
    clients.append(asyncio.create_task(gps_telemetry(telemetryQ, logQ, i2cSBL, gps, gps_period)))
    clients.append(asyncio.create_task(imu_telemetry(telemetryQ, logQ, i2cSBL, imu, imu_period)))
    clients.append(asyncio.create_task(command_handler(eventQ, logQ, diodeQ, displayQ, cmd_period)))
    clients.append(asyncio.create_task(noise_diode_handler(diodeQ, logQ, i2cSBL, diode_gpio, diode_period)))
    clients.append(asyncio.create_task(display_handler(displayQ, logQ, display, display_period)))

    print("run")

    await asyncio.gather(*clients)


asyncio.run(main())