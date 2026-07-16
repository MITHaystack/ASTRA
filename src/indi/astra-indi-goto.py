"""
    astra-indi-goto.py

    Command line routine to connect to antenna controller via INDI and set the mount pointing manually.

"""
import argparse
import os
import sys
import traceback

import time
import datetime
import astropy
import asyncio
import aiomqtt
import PyIndi
import json

import pywmm

def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "astra-indi-goto"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Goto a provided position using the ASTRA telescope mount."
    desc = "\n".join(
        (
            "*" * width,
            "*{0:^{1}}*".format(title, width - 2),
            "*{0:^{1}}*".format(copyright, width - 2),
            "*{0:^{1}}*".format("", width - 2),
            "*{0:^{1}}*".format(shortdesc, width - 2),
            "*" * width,
        )
    )

    parser = argparse.ArgumentParser(
        description=desc,
        prefix_chars="-",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "-d",
        "--dev",
        dest="dev",
        default="Skywatcher Alt-Az",
        help=(
            "The INDI device associated with the antenna control."
        ),
    )

    parser.add_argument(
        "-m",
        "--mqtt",
        dest="mqtt",
        default="localhost",
        help=(
            "The MQTT host associated with the antenna IMU information."
        ),
    )

    parser.add_argument(
        "-c",
        "--chan",
        dest="chan",
        default="astra/ai/telemetry",
        help=(
            "The MQTT channel associated with the antenna IMU information."
        ),
    )

    parser.add_argument(
        "-s",
        "--slew",
        dest="goto_mode",
        action="store_true",
        default=False,
        help=(
            "Set the goto mode to slew instead of track."
        ),
    )


    parser.add_argument(
        "-az",
        "--azimuth",
        dest="az",
        type=float,
        help="The antenna azimuth for goto.",
    )

    parser.add_argument(
        "-el",
        "--elevation",
        dest="el",
        type=float,
        help="The antenna elevation for goto.",
    )

    parser.add_argument(
        "-ra",
        "--right-ascension",
        dest="ra",
        type=float,
        help="The antenna right ascension for goto.",
    )

    parser.add_argument(
        "-dec",
        "--declination",
        dest="dec",
        type=float,
        help="The antenna declination for goto.",
    )

    parser.add_argument(
        "-g",
        "--gps",
        action="store_true",
        dest="gps",
        default=False,
        help="Uses the GPS telemetry for the mount position if available.",
    )

    parser.add_argument(
        "-i",
        "--imu",
        action="store_true",
        dest="imu",
        default=False,
        help="Uses the IMU telemetry for motion status the mount if available.",
    )
    
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        default=False,
        help="Makes the output information more verbose.",
    )

    options = parser.parse_args()

    return options

async def mqtt_get_event(options, telemetry_type):
    
    tdata = None

    async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
            await mqtt_client.subscribe(options.chan + '/' + telemetry_type)
            try:
                async for message in mqtt_client.messages():
                    if options.verbose:
                        print("got telemetry: ", message)

                    if message is not None:
                        tdata = json.loads(message.payload.decode('utf-8'))
                        break

            except aiomqtt.ConnectError as err:
                print(f"Unable to connect to {options.mqtt} and get imu telemetry from {options.chan}")
                
            except json.JSONDecodeError as err:
                print(f"Problem decoding json command object, {message}")

            except Exception as err:
                print(f"exception getting IMU telemetry {err}")

    return tdata

# Indi helpers
def get_switch_with_retry(device, switch_name, max_retries=3, delay=2):
    """
    Attempts to get a switch property from an INDI device, retrying upon failure.
    """
    for attempt in range(max_retries):
        try:
            switch_prop = device.getSwitch(switch_name)
            if switch_prop:
                return switch_prop
        except Exception as e:
            print(f"Attempt {attempt + 1}: Failed to retrieve {switch_name}. Retrying in {delay}s... Error: {e}")
        
        time.sleep(delay)
    
    raise RuntimeError(f"Failed to get switch '{switch_name}' after {max_retries} attempts.")


def get_text_with_retry(device, text_name, max_retries=3, delay=2):
    """
    Attempts to get a text property from an INDI device, retrying upon failure.
    """
    for attempt in range(max_retries):
        try:
            text_prop = device.getText(text_name)
            if text_prop:
                return text_prop
        except Exception as e:
            print(f"Attempt {attempt + 1}: Failed to retrieve {text_name}. Retrying in {delay}s... Error: {e}")
        
        time.sleep(delay)
    
    raise RuntimeError(f"Failed to get switch '{text_name}' after {max_retries} attempts.")

def get_number_with_retry(device, num_name, max_retries=3, delay=2):
    """
    Attempts to get a number property from an INDI device, retrying upon failure.
    """
    for attempt in range(max_retries):
        try:
            num_prop = device.getNumber(num_name)
            if num_prop:
                return num_prop
        except Exception as e:
            print(f"Attempt {attempt + 1}: Failed to retrieve {num_name}. Retrying in {delay}s... Error: {e}")
        
        time.sleep(delay)
    
    raise RuntimeError(f"Failed to get switch '{num_name}' after {max_retries} attempts.")


#
# MAIN PROGRAM
#

# Setup Defaults
if __name__ == "__main__":
    """
    Needed to add main function to use outside functions outside of module.
    """

    # Parse the Command Line for configuration
    options = parse_command_line()

    if options.verbose:
        print("options: {0}".format(options))


    # connect to mount via INDI

    pic = PyIndi.BaseClient()
    pic.setServer("localhost", 7624)
    pic.connectServer()
    time.sleep(0.25)

    # This assumes a skywatcher AzEl GTi for the moment
    # needs to be tied to a variable eventually
    mount = pic.getDevice(options.dev)
    time.sleep(0.25)

    #if not mount:
    #    print(f"Mount {options.dev} not found")
    #    sys.exit(1)

    # connect to mqtt and pull imu and gps information
    try:
        imu_data = None
        gps_data = None
        # attempt to connect to the MQTT channel and pull the latest IMU telemetry object     
        if options.imu:
            imu_data = asyncio.run(mqtt_get_event(options,'ai-imu-data'))
            if options.verbose:
                print(imu_data)

        if options.gps:
            gps_data = asyncio.run(mqtt_get_event(options,'ai-gps-data'))
            if options.verbose:
                print(gps_data)


    except Exception as e:
        print("Problem connecting to MQTT server and getting IMU telemetry information ")
        traceback.print_exc()
        sys.exit()

    if gps_data is not None and gps_data['event'] == 'ai-gps-data':
        if options.verbose:
            print("got gps data")
        utc_time = gps_data['utc']
        has_fix = gps_data['fix']
        lat = gps_data['latitude']
        lon = gps_data['longitude']
        alt = gps_data['altitude']

    else:
        utc_time = datetime.datetime.now().isoformat(timespec="seconds")
        has_fix = 0
        # default to Haystack for the moment
        lat = 42.622729
        lon = -71.488404
        alt = 130.0


    if imu_data is not None and imu_data['event'] == 'ai-imu-data':
        if options.verbose:
            print("got imu data")
        imu_az, imu_el = imu_data['pointing']
        has_imu = True
        # remove declination as the IMU reads in magnetic coordinates
        cyear = datetime.datetime.now().year
        wmm = pywmm.WMMv2()
        mag_dec = wmm.get_declination(lat, lon, cyear, alt/1E3)
        imu_az = imu_az + mag_dec
 
        if options.verbose:
            print(f"adjusting for magnetic declination of {mag_dec}")

    if (options.az and options.el) is not None:
        target_az = options.az
        target_el = options.el
        target_type = 'azel'
        # check for real outliers
        if target_az < -359.9 or target_az > 359.9:
            print("Azimuth outside valid range, default to 0.0")
            target_az = 0.0
        
        if target_el < -5.0:
            print("Elevation is below a nominal low level of -5.0 deg, level unit and resync.")
            print("default to elevation 0.0")
            target_el = 0.0

        if target_el > 90.0:
            print("Antenna cannot point greater than 90.0 elevation, default to elevation 0.0")
            target_el = 0.0

    elif (options.ra and options.dec) is not None:
        target_ra = options.ra
        target_dec = options.dec
        target_type='radec'
    else:
        print(f"unknown AZEL or RADEC goto target {options.az}AZ,{options.el}EL or {options.ra}RA,{options.dec}DEC")
        sys.exit(1)

    if target_type == 'azel':

        # compute RA and DEC for current pointing
        astro_location = astropy.coordinates.EarthLocation.from_geodetic(lat=lat,lon=lon,height=alt)
        astro_time = astropy.time.Time(utc_time, scale='utc', location=astro_location)
        print("apparent sidreal time", astro_time.sidereal_time('apparent'))
        altaz_frame = astropy.coordinates.AltAz(obstime=astro_time, location=astro_location)
        altaz_coord = astropy.coordinates.SkyCoord(alt=target_el*astropy.units.deg,az=target_az*astropy.units.deg, frame = altaz_frame)
        eq_coord = altaz_coord.transform_to('icrs')
        ra_target = eq_coord.ra.hour
        dec_target = eq_coord.dec.deg

    elif target_type == 'radec':
            pass
    else:
        print("Unknown motion target.")
        sys.exit(1)
        
    if options.verbose:
        print(f"goto {eq_coord.ra.hour}h RA {eq_coord.dec.deg}d DEC")

    # get coordinate EQUATORIAL_EOD_COORD property
    eq_prop = get_number_with_retry(mount,"EQUATORIAL_EOD_COORD")
    
    if not eq_prop.isValid():
        print("Property EQUATORIAL_EOD_COORD not valid")
    
    eq_prop[0].value = ra_target
    eq_prop[1].value = dec_target

    # set with ON_COORD_SET
    # switch for trigger of sync on write
    onset_prop = get_switch_with_retry(mount,"ON_COORD_SET")

    if not onset_prop.isValid():
        print("Property ON_COORD_SET not valid")

    print(onset_prop[0].name)
    print(onset_prop[1].name)
    print(onset_prop[2].name)
    if not options.goto_mode:
        if options.verbose:
            print("goto and track")
        onset_prop[0].s = PyIndi.ISS_ON
        onset_prop[1].s = PyIndi.ISS_OFF
        onset_prop[2].s = PyIndi.ISS_OFF
    elif options.goto_mode:
        if options.verbose:
            print("goto slew")
        onset_prop[0].s = PyIndi.ISS_OFF
        onset_prop[1].s = PyIndi.ISS_ON
        onset_prop[2].s = PyIndi.ISS_OFF
    else:
        print(f"unknown mode option {options.mode}")
        sys.exit(1)

    if options.verbose:
        print(f"send {ra_target}h RA {dec_target}deg DEC")
    pic.sendNewSwitch(onset_prop)
    time.sleep(0.1)
    pic.sendNewNumber(eq_prop)

