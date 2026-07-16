"""
    astra-indi-sync.py

    Command line routine to connect to antenna controller via INDI and sync the mount pointing manually.

    Attempts to pull the current IMU telemetry by default via MQTT. Command line for other sync positions.

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

    title = "astra-indi-sync"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Synchronize orienation of the ASTRA telescope mount."
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
        default="AZ-GTi Alt-Az Wired",
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
        "-az",
        "--azimuth",
        dest="az",
        default=0.0,
        type=float,
        help="The antenna azimuth for synchronization.",
    )

    parser.add_argument(
        "-el",
        "--elevation",
        dest="el",
        default=0.0,
        type=float,
        help="The antenna elevation for synchronization.",
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
        "-p",
        "--park",
        action="store_true",
        dest="park",
        default=False,
        help="Uses sync position to also set the park position, then park.",
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

    #connect_prop = get_switch_with_retry(mount, "CONNECTION")

    #if connect_prop:
        # Set the CONNECTION_CONNECT switch to ON
    #    connect_prop[0].s = PyIndi.ISS_ON 
    #    connect_prop[1].s = PyIndi.ISS_OFF
    
    # Send the new state to the INDI server
    #pic.sendNewSwitch(connect_prop)


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
        utc_time = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
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
        target_az = imu_az + mag_dec
        target_el = imu_el

        if options.verbose:
            print(f"adjusting for magnetic declination of {mag_dec}")
 

    else:
        print(f"data from imu not found, object was type {imu_data['event']}")
        print(f"defaulting to {options.az} az and {options.el} el")
        target_az = options.az
        target_el = options.el
        has_imu = False

    # pull az and el
    az = target_az
    el = target_el

    # check for real outliers
    if az < -359.9 or az > 359.9:
        print("Azimuth outside valid range, default to 0.0")
        az = 0.0
    
    if el < -5.0:
        print("Elevation is below a nominal low level of -5.0 deg, level unit and resync.")
        print("default to elevation 0.0")
        el = 0.0

    if el > 90.0:
        print("Antenna cannot point greater than 90.0 elevation, default to elevation 0.0")
        el = 0.0

    print(f"Set mount time to {utc_time}")

    utc_prop = get_text_with_retry(mount,"TIME_UTC")
    if utc_prop:
        utc_time = utc_time.replace("+00:00","")
        utc_time = utc_time.replace("Z","")
        # UTC offset
        lt = datetime.datetime.now()
        lt_utc = datetime.datetime.now(datetime.timezone.utc)
        lwtz = lt.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo)
        offset = lwtz.utcoffset().total_seconds()
        offset_hr = int(offset/3600.0)
        utc_prop[0].text = utc_time
        utc_prop[1].text = f"{offset_hr}"
        pic.sendNewText(utc_prop)
        if options.verbose:
            print("sent UTC time to mount")

    if has_fix:
        print(f"Set mount position to GPS position ({lat} lat, {lon} lon, {alt} alt)")
    else:
        print(f"Set mount position to default Haystack position ({lat} lat, {lon} lon, {alt} alt)")

    location_prop = get_number_with_retry(mount,"GEOGRAPHIC_COORD")
    if location_prop:
        location_prop[0].value = lat 
        location_prop[1].value = lon % 360.0
        location_prop[2].value = alt
        pic.sendNewNumber(location_prop)
        if options.verbose:
            print("sent location to mount.")

    # compute RA and DEC for current pointing
    astro_location = astropy.coordinates.EarthLocation.from_geodetic(lat=lat,lon=lon,height=alt)
    astro_time = astropy.time.Time(utc_time, scale='utc', location=astro_location)
    print("apparent sidreal time", astro_time.sidereal_time('apparent'))
    altaz_frame = astropy.coordinates.AltAz(obstime=astro_time, location=astro_location)
    altaz_coord = astropy.coordinates.SkyCoord(alt=el*astropy.units.deg,az=az*astropy.units.deg, frame = altaz_frame)
    eq_coord = altaz_coord.transform_to('icrs')

    if options.verbose:
        print(f"{az} Az {el}El to {eq_coord.ra.hour}h RA {eq_coord.dec.deg}d DEC")

    if has_imu:
        print(f"Synchronize mount to IMU orientation {az} AZ {el} EL.")
    else:
        print(f"Synchronize mount to orientation {az} AZ {el} EL.")

    #azel_prop = mount.getProperty("HORIZONTAL_COORD")

    #if not azel_prop.isValid():
    #    print("Property HORIZONTAL_COORD not valid")

    #azel_prop[1].setValue(az)
    #azel_prop[0].setValue(el)
    #print(azel_prop)

    # get coordinate EQUATORIAL_EOD_COORD property
    eq_prop = get_number_with_retry(mount,"EQUATORIAL_EOD_COORD")
    
    if not eq_prop.isValid():
        print("Property EQUATORIAL_EOD_COORD not valid")
    
    eq_prop[0].value = eq_coord.ra.hour
    eq_prop[1].value = eq_coord.dec.deg

    # set with ON_COORD_SET
    # switch for trigger of sync on write
    onset_prop = get_switch_with_retry(mount,"ON_COORD_SET")

    if not onset_prop.isValid():
        print("Property ON_COORD_SET not valid")

    print(onset_prop[0].name)
    print(onset_prop[1].name)
    print(onset_prop[2].name)
    onset_prop[0].s = PyIndi.ISS_OFF
    onset_prop[1].s = PyIndi.ISS_OFF
    onset_prop[2].s = PyIndi.ISS_ON

    pic.sendNewSwitch(onset_prop)
    time.sleep(0.1)
    pic.sendNewNumber(eq_prop)

    if options.park:
        print(f"set mount park position to {az} AZ {el} EL. ")


    # read back INDI configuration and print
