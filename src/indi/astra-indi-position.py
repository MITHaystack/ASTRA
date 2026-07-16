"""
    astra-indi-position.py

    Command line routine to connect to antenna controller via INDI and output the mount pointing.

    Attempts to pull the current IMU telemetry by default via MQTT.

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

    title = "astra-indi-position"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Print the orienation of the ASTRA telescope mount."
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
        "-g",
        "--gps",
        action="store_true",
        dest="gps",
        default=False,
        help="Uses the GPS telemetry to set mount position if available.",
    )

    parser.add_argument(
        "-i",
        "--imu",
        action="store_true",
        dest="imu",
        default=False,
        help="Uses the IMU telemetry to sync the mount if available.",
    )

    parser.add_argument(
        "-n",
        "--num",
        dest="num",
        default=1,
        type=int,
        help="The number of times to print with a delay in between.",
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
    
    raise RuntimeError(f"Failed to get text '{text_name}' after {max_retries} attempts.")

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
    
    raise RuntimeError(f"Failed to get number '{num_name}' after {max_retries} attempts.")


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

    loop_cnt = 0

    while True:
        if loop_cnt >= options.num:
            break
        loop_cnt += 1

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
    
    
        # get coordinate EQUATORIAL_EOD_COORD property
        eq_prop = get_number_with_retry(mount,"EQUATORIAL_EOD_COORD")
        
        if not eq_prop.isValid():
            print("Property EQUATORIAL_EOD_COORD not valid")
     
        # compute AZ and EL for current pointing
        astro_location = astropy.coordinates.EarthLocation.from_geodetic(lat=lat,lon=lon,height=alt)
        astro_time = astropy.time.Time(utc_time, scale='utc', location=astro_location)
        if options.verbose:
            print("apparent sidreal time", astro_time.sidereal_time('apparent'))
        altaz_frame = astropy.coordinates.AltAz(obstime=astro_time, location=astro_location)
        radec_coord = astropy.coordinates.SkyCoord(ra=eq_prop[0].value*astropy.units.hour,dec=eq_prop[1].value*astropy.units.deg,frame='icrs')
        altaz_coord = radec_coord.transform_to(altaz_frame)

        daz = (altaz_coord.az.deg) - imu_az
        dalt = (altaz_coord.alt.deg) - imu_el
        print(f"{utc_time}| {altaz_coord.az.deg:06.3f}Az,{altaz_coord.alt.deg:05.3f}El | {radec_coord.ra.hour:06.3f}h, {radec_coord.dec.deg:06.3f}deg | IMU {imu_az:06.3f}Az,{imu_el:05.3f}El / {daz:05.2f},{dalt:04.2f}")

        time.sleep(1)