"""
    astra-motion.py

    This software service interfaces with INDI based telescope mount drivers, the telemetry from the 
    ASTRA Antenna Interface Unit, outputs mount related MQTT telemetry, and accepts commands via MQTT. 

    The motion control program provides a message command API for mount synchronization, goto, tracking,
    and position stowing. 

"""

import asyncio
import argparse
import os
import sys
import traceback
import serial
import json

import numpy as np

from datetime import datetime, UTC, timezone
from pygeomag import GeoMag

from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u

from dataclasses import dataclass, asdict, fields
from typing import Optional

from loguru import logger
import aiomqtt

import azgti

## data and command objects
from astradata.objects import *

def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "astra-motion.py"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Service to control the ASTRA Antenna mount"
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
        default="/dev/ttyUSB0",
        help=(
            "The serial device associated with the antenna motion control interface."
        ),
    )
    
    parser.add_argument(
        "-m",
        "--mqtt",
        dest="mqtt",
        default="127.0.0.1",
        help=(
            "The mqtt device IP associated with the ASTRA message queue."
        ),
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

### Helper local methods

def _command_cleanup(cmd):
    # filter any object keys that should not be part of an update
    # these are inherent to the object class
    rkey = {'group','event','last_update_utc','update_count'}
    rcmd = {k: cmd[k] for k in cmd.keys() - rkey}
    return rcmd

def _to_decimal_year(dt: datetime) -> float:
    # Get the start of the current year and the next year
    start_of_this_year = datetime(dt.year, 1, 1, tzinfo=dt.tzinfo)
    start_of_next_year = datetime(dt.year + 1, 1, 1, tzinfo=dt.tzinfo)
    
    # Calculate durations using timedeltas
    year_elapsed = (dt - start_of_this_year).total_seconds()
    year_duration = (start_of_next_year - start_of_this_year).total_seconds()
    
    return dt.year + (year_elapsed / year_duration)

def _to_altaz_from_radec(tstamp, lat, lon, alt, ra_hr, ra_min, ra_sec, dec):
    try:
        print("to altaz : ", tstamp, lat, lon, alt, ra_hr, ra_min, ra_sec, dec)
        target = SkyCoord(ra=f"{ra_hr}h{ra_min}m{ra_sec}s",dec=dec*u.deg,frame='icrs')
        location = EarthLocation(lon=lon*u.deg,lat=lat*u.deg,height=alt*u.m)
        target_altaz = target.transform_to(AltAz(obstime=tstamp,location=location))

        tgt_az = float(target_altaz.az.to_value(u.deg))
        tgt_alt = float(target_altaz.alt.to_value(u.deg))

        # rotate to zero centered coordinate frame
        if tgt_az > 180.0:
            tgt_az = tgt_az - 360.0 

        if tgt_alt < 0.0:
            tgt_alt = 0.0

        if tgt_alt > 89.5:
            tgt_alt = 89.5

        print("to altaz :", tgt_az, tgt_alt)

    except Exception as e:
        print(e)
        traceback.print_exc() 
        return (0.0,0.0)

    return (tgt_az, tgt_alt)

def _apply_antenna_offsets(offsets, az, alt, azr, altr):
    return (az + offsets.offset_az, alt + offsets.offset_alt, azr + offsets.offset_azr, altr + offsets.offset_altr)

""" Check against a provided limits data object, return the value rounded down to the limit. """
def _apply_antenna_limits(limits, az, alt, azr, altr):
    chk_az = az
    chk_alt = alt
    chk_azr = azr
    chk_altr = altr
    
    # check azimuth limit
    if az > limits.az_cw_limit:
       chk_az = limits.az_cw_limit - 0.01
    
    if az < limits.az_ccw_limit:
        chk_az = limits.az_ccw_limit + 0.01

    # check altitude limit

    if alt > limits.alt_up_limit:
        chk_alt = limits.alt_up_limit - 0.01
    
    if alt < limits.alt_down_limit:
        chk_alt = limits.alt_down_limit + 0.01

    # check rate limits
    # rates are always positive except directly in the slew command
    if azr > limits.azr_limit:
        chk_azr = limits.azr_limit

    if azr < 0.0:
        chk_azr = 0.0

    if altr > limits.altr_limit:
        chk_altr = limits.altr_limit

    if altr < 0.0:
        chk_altr = 0.0

    # return bounded motion target tuple
    return (chk_az, chk_alt, chk_azr, chk_altr)

def _on_target(pnt, tgt_az, tgt_alt, az_err = 0.05, alt_err = 0.05):
    on_az = abs(pnt.pointing_az-tgt_az) < az_err
    on_alt = abs(pnt.pointing_alt - tgt_alt) < alt_err

    return on_az and on_alt

def _compute_declination(dyr, lat, lon, alt):
    gmag = GeoMag()
    decl = gmag.calculate(lat, lon, alt, dyr)
    return decl.d

"""
    Handle motion control of the mount. 
"""
async def antenna_motion_handler(options, mount, mount_lock, antenna_state, eventQ, telemetryQ, logQ, motion_period):
    # no initial connection
    event_cnt = 0
    loop_cnt = 0

    motion_state = 'standby' # standby, set-target, update-target, on-target, stow, stop, estop
    
    # motion start
    motion_start_point = {'az':0.0, 'alt':0.0}
    motion_start_time = datetime.now(timezone.utc).timestamp()
    motion_expected_time = 1.0
    send_motion_command = False

    motion_target = {
        'timestamp': datetime.now(timezone.utc).timestamp(),
        'tgt_az'   : 0.0,
        'tgt_alt'  : 0.0,
        'tgt_azr'  : 1.0,
        'tgt_altr' : 1.0
    }

    # IMU calibration motion command
    # state tracking, simple steps : start (0.0,0.0), up (0,85.0), left (-100.0,45.0), right (+100.0,45.0), center (45.0,45.0), end (0.0,0.0) 
    cal_state = {'state':'start'}

    # Slew motion command
    # state tracking
    slew_state = {
        'axis' : 0,
        'ccw' : False,
        'rate' : 1.0,
        'timeout' : 1.0,
    }

    while True:
        if options.verbose:
            print("update antenna motion handler")

        """ 
            Accept commands, validate them, and then setup for the specific state which will do the 
            actual motion control. Commands can override existing states and force transitions. That
            avoids deadlock conditions. 
        """
        try:
            cmd = eventQ.get_nowait() # the event is a dictionary form of a command object
            print("cmd -> ", cmd)
            if cmd is not None:
                match cmd['group']:
                    case 'astra-set-location-cmd':
                        print('got set location')
                        ccmd = _command_cleanup(cmd)
                        # validate
                        assert validate_command(ccmd,AstraSetLocationCommand)
                        # cleanup command
                        loc_data = ccmd
                        # compute the declination from the location and store it
                        dyr = _to_decimal_year(datetime.now())
                        decl = _compute_declination(dyr,loc_data['latitude'], loc_data['longitude'], loc_data['altitude'])
                        loc_data['declination'] = decl
                        # update 
                        await antenna_state.update('astra-location', loc_data)
                    case 'astra-set-offset-cmd':
                        print('got set offset')
                        ccmd = _command_cleanup(cmd)
                        # validate
                        assert validate_command(ccmd,AstraSetOffsetsCommand)
                        # cleanup command
                        off_data = ccmd
                        # update 
                        await antenna_state.update('astra-offsets', off_data)
                    case 'mount-sync-cmd':
                        print('got mount sync')
                        ccmd = _command_cleanup(cmd)
                         # validate
                        assert validate_command(ccmd,AstraSyncCommand)
                        # cleanup command
                        off_data = ccmd
                        # update 
                        if cmd['sync_telemetry']:
                            pos = await antenna_state.get('mount-position') # get latest position, updated via telemetry thread
                            antenna_pointing = antenna_state.get('antenna-pointing')
                            await antenna_pointing.sync_direct(pos['position_az'],pos['position_alt'],sync_data['sync_az'], sync_data['sync_alt'])
                        elif cmd['sync_imu']:
                            loc = await antenna_state.get('astra-location')
                            pos = await antenna_state.get('mount-position') # get latest position, updated via telemetry thread
                            imu_data = await antenna_state.get('imu') # get latest imu data, updated via telemetry thread
                            # compute the declination from the location
                            dyr = _to_decimal_year(datetime.now())
                            gmag = GeoMag()
                            decl = gmag.calculation(loc['latitude'], loc['longitude'], loc['altitude'],dyr)
                            # imu reads magnetic azimuth so we need to adjust for declination in the routine, neglect axial offsets
                            await antenna_pointing.sync_imu(pos['position_az'],pos['position_alt'], imu_data, decl.d, 0.0, 0.0)

                    case 'mount-stop-cmd':
                        print("got mount stop")
                        ccmd = _command_cleanup(cmd)
                        assert validate_command(ccmd,AstraStopCommand)
                        motion_state = 'stop'

                    case 'mount-estop-cmd':
                        print("got mount estop")
                        ccmd = _command_cleanup(cmd)
                        assert validate_command(ccmd,AstraEStopCommand)
                        motion_state = 'force-stop'

                    case 'mount-set-limits-cmd':
                        print("got set limits")
                        ccmd = _command_cleanup(cmd)
                        assert validate_command(ccmd,AstraSetLimitsCommand)
                        pass # for the moment do not implement this one, needs too much testing
 
                    case 'mount-set-rate-cmd':
                        print("got set rate")
                        ccmd = _command_cleanup(cmd)
                        assert validate_command(ccmd,AstraSetRateCommand)
                        rate_data = ccmd
                        await antenna_state.update('mount-rate',rate_data,True)
                    case 'astra-set-target-cmd':
                        print("got set target")
                        ccmd = _command_cleanup(cmd)
                        assert validate_command(ccmd,AstraSetTargetCommand)
                        tgt_data = ccmd
                        await antenna_state.update('astra-target',tgt_data,True)
                        motion_state = 'set-target'
                    case _:
                        print("got unknown cmd")
                        if options.verbose:
                            print(f"unknown antenna motion command {cmd['event']}")
      
        except (serial.SerialException, EOFError) as e:
                if options.verbose:
                    print("serial exception EOF error, attempt reconnect")
                asyncio.sleep(0.1)
                mount.reconnect()
                continue
        except (asyncio.queues.QueueEmpty) as e:
                #if options.verbose:
                #    print("command queue empty in antenna motion handler")
                # just pass through and let the other state machine stuff run
                pass
        except Exception as e:
            #if options.verbose:
            print(e)
            traceback.print_exc() 
            #else:
            #    pass
        
        """
            Implemement the state machine for controlling the antenna motion. Motion targets are set in the
            state machine to allow for filtering prior to command execution. So this is a separate of the
            targeting logic from the motion logic. Stop commands have immediate logic to halt the antenna.
        """
        try:
            pointing = await antenna_state.get('astra-pointing') 
            motion_start_point['az'] = pointing.pointing_az
            motion_start_point['alt'] = pointing.pointing_alt
            match motion_state:
                case 'standby':
                    #print('state = standby')
                    motion_start_time = datetime.now(timezone.utc).timestamp()
                    motion_state = 'standby'
                case 'stop':
                    print('state = stop')
                    motion_start_time = datetime.now(timezone.utc).timestamp()
                    async with mount_lock:
                        mount.stop_motion('1')
                        mount.stop_motion('2')       
                    motion_state = 'standby'
                case 'force-stop':
                    print('state = force stop')
                    motion_start_time = datetime.now(timezone.utc).timestamp()
                    async with mount_lock:
                        mount.force_stop_motion()
                    motion_state = 'standby'
                case 'set-target':
                    print('state = set target')
                    motion_start_time = datetime.now(timezone.utc).timestamp()
                    target = await antenna_state.get('astra-target')
                    match target.target_type:
                        case 'standby':
                            print('. target = standby')
                            motion_target['tgt_az'] = motion_start_point['az']
                            motion_target['tgt_alt'] = motion_start_point['alt']
                            motion_target['tgt_azr'] = 1.0
                            motion_target['tgt_altr'] = 1.0
                            motion_expected_time = 1.0
                            send_motion_command = True

                            motion_state = 'standby' # wait for a command

                        case 'stow':
                            print('. target = stow')
                            # no offsets for the stow command
                            # target is always zed zed, rate is always unity
                            motion_target['tgt_az'] = 0.0
                            motion_target['tgt_alt'] = 0.0
                            motion_target['tgt_azr'] = 1.0
                            motion_target['tgt_altr'] = 1.0

                            az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az'])
                            alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt'])

                            motion_expected_time = max(az_expected_time, alt_expected_time)
                            send_motion_command = True

                            motion_state = 'update-target'

                        case 'calibration':
                            # Start point for calibration is stow position
                            # but we use higher rates to help calibrate
                            # accelerometer. Sequence starts from zero zero
                            # so if already there that is fine...
                            print('. target = calibration')
                            cal_state['state'] = 'start'
                            motion_target['tgt_az'] = 0.0
                            motion_target['tgt_alt'] = 0.0
                            motion_target['tgt_azr'] = 5.0
                            motion_target['tgt_altr'] = 5.0 # ramp to full rate

                            az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                            alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']

                            send_motion_command = True
                            motion_expected_time = max(az_expected_time, alt_expected_time)
                            motion_state = 'update-target'

                        case 'altaz':
                            print('. target = altaz')
                            motion_target['tgt_az'] = target.target_info['target_az']
                            motion_target['tgt_alt'] = target.target_info['target_alt']
                            motion_target['tgt_azr'] = target.target_info['az_rate']
                            motion_target['tgt_altr'] = target.target_info['alt_rate']

                            az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                            alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']
                            
                            send_motion_command = True
                            motion_expected_time = max(az_expected_time, alt_expected_time)
                            motion_state = 'update-target'

                        case 'radec':
                            print('. target = radec !')
                            
                            loc = await antenna_state.get('astra-location')
                            rate = await antenna_state.get('mount-rate')
                            tgt_tstamp = target.timestamp
                            print(target.target_info)

                            tgt_ra_h = target.target_info['target_ra_h']
                            tgt_ra_m = target.target_info['target_ra_m']
                            tgt_ra_s = target.target_info['target_ra_s']
                            tgt_dec = target.target_info['target_dec']
                            track = target.target_info['track']
                        
                            print(f"radec: {tgt_tstamp}, {tgt_ra_h}, {tgt_ra_m}, {tgt_ra_s}, {tgt_dec}")

                            tgt_az, tgt_alt = _to_altaz_from_radec(tgt_tstamp, loc.latitude, loc.longitude, 
                                                             loc.altitude, tgt_ra_h, tgt_ra_m, tgt_ra_s, 
                                                             tgt_dec)
                            
                            print('. radec tgt_az ', tgt_az, ' tgt_alt ', tgt_alt)

                            motion_target['timestamp'] = tgt_tstamp
                            motion_target['tgt_az'] = tgt_az
                            motion_target['tgt_alt'] = tgt_alt
                            motion_target['tgt_azr'] = rate.az_rate
                            motion_target['tgt_altr'] = rate.alt_rate

                            print('. radec motion target ', tgt_az, tgt_alt, rate.az_rate, rate.alt_rate)

                            az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                            alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']

                            print('. radec about to senc command ', az_expected_time, alt_expected_time)
                        
                            send_motion_command = True
                            motion_expected_time = max(az_expected_time, alt_expected_time)
                            motion_state = 'update-target'                            
                            
                        case 'slew':
                            print('. target = slew')
                            # note slew direction changes need a stop in between
                            # currently this happens at the UI level!

                            print(target.target_info)

                            slew_state['axis'] = target.target_info['axis']
                            slew_state['ccw'] = target.target_info['ccw']
                            slew_state['rate'] = target.target_info['rate']
                            slew_state['timeout'] = target.target_info['timeout']

                            send_motion_command = True
                            motion_expected_time = target.target_info['timeout']
                            motion_state = 'update-target'

                        case 'object':
                            print('. target = object (no implemented)')
                            motion_state = 'standby'
                        case _:
                            print('. target = unknown')
                            motion_state = 'standby'

                case 'update-target':
                    print('implement target update')
                    target = await antenna_state.get('astra-target')
                    motion_update_time = datetime.now(timezone.utc).timestamp()
                    motion_duration = datetime.now(timezone.utc).timestamp() - motion_update_time

                    match target.target_type:
                        case 'standby':
                            print(".. update standby")
                            send_motion_command = False
                            pass
                        case 'stow':
                            print(".. update stow")
                            pointing = await antenna_state.get('astra-pointing') 

                            send_motion_command = False
                        
                            if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                motion_state = 'stop'
                            
                            if motion_duration > (motion_expected_time+1.0):
                                motion_state = 'stop'

                        case 'calibration':
                            print(".. update calibration")
                            pointing = await antenna_state.get('astra-pointing') 

                            match cal_state['state']:
                                case 'start':
                                    if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                        # goto up
                                        motion_target['tgt_az'] = 85.0
                                        motion_target['tgt_alt'] = 0.0

                                        motion_start_time = datetime.now(timezone.utc).timestamp()
                                        az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                                        alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']
                                        motion_expected_time = max(az_expected_time, alt_expected_time)

                                        cal_state = 'up'
                                    
                                        send_motion_command = True
                                    else:
                                        send_motion_command = False

                                    if motion_duration > (motion_expected_time+1.0):
                                        cal_state = 'end'
                                        motion_state = 'stop'
                                        
                                case 'up':
                                    if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                        # goto left
                                        motion_target['tgt_az'] = -100.0
                                        motion_target['tgt_alt'] = 45.0

                                        motion_start_time = datetime.now(timezone.utc).timestamp()
                                        az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                                        alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']
                                        motion_expected_time = max(az_expected_time, alt_expected_time)
                                        
                                        cal_state = 'left'
                                    
                                        send_motion_command = True
                                    else:
                                        send_motion_command = False

                                    if motion_duration > (motion_expected_time+1.0):
                                        cal_state = 'end'
                                        motion_state = 'stop'

                                case 'left':
                                    if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                        # goto right
                                        motion_target['tgt_az'] = 100.0
                                        motion_target['tgt_alt'] = 45.0

                                        motion_start_time = datetime.now(timezone.utc).timestamp()
                                        az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                                        alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']
                                        motion_expected_time = max(az_expected_time, alt_expected_time)
                                        
                                        cal_state = 'right'

                                        send_motion_command = True
                                    else:
                                        send_motion_command = False

                                    if motion_duration > (motion_expected_time+1.0):
                                        cal_state = 'end'
                                        motion_state = 'stop'

                                case 'right':
                                    if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                        # goto center
                                        motion_target['tgt_az'] = 0.0
                                        motion_target['tgt_alt'] = 45.0

                                        motion_start_time = datetime.now(timezone.utc).timestamp()
                                        az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                                        alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']
                                        motion_expected_time = max(az_expected_time, alt_expected_time)
                                        
                                        cal_state = 'center'

                                        send_motion_command = True
                                    else:
                                        send_motion_command = False

                                    if motion_duration > (motion_expected_time+1.0):
                                        cal_state = 'end'
                                        motion_state = 'stop'
                                        

                                case 'center':
                                    if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                        # goto end
                                        motion_target['tgt_az'] = 0.0
                                        motion_target['tgt_alt'] = 0.0

                                        motion_start_time = datetime.now(timezone.utc).timestamp()
                                        az_expected_time = abs(motion_start_point['az']-motion_target['tgt_az']) / motion_target['tgt_azr']
                                        alt_expected_time = abs(motion_start_point['alt']-motion_target['tgt_alt']) / motion_target['tgt_altr']
                                        motion_expected_time = max(az_expected_time, alt_expected_time)
                                        
                                        cal_state = 'end'

                                        send_motion_command = True
                                    else:
                                        send_motion_command = False

                                    if motion_duration > (motion_expected_time+1.0):
                                        cal_state = 'end'
                                        motion_state = 'stop'
                                        
                                case 'end':
                                    motion_target['tgt_az'] = 0.0
                                    motion_target['tgt_alt'] = 0.0
                                    motion_target['tgt_azr'] = 0.0
                                    motion_target['tgt_altr'] = 0.0
        
                                    send_motion_command = False

                                    motion_state = 'on-target'

                        case 'altaz':
                            print(".. update altaz")
                            if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                motion_state = 'on-target'

                            send_motion_command = False

                            if motion_duration > (motion_expected_time+1.0):
                                motion_state = 'stop'

                        case 'radec':
                            print(".. update radec")
                            # We will add tracking into this in a bit... that is why it is separate

                            if _on_target(pointing, motion_target['tgt_az'], motion_target['tgt_alt']):
                                motion_state = 'on-target'

                            send_motion_command = False

                            if motion_duration > (motion_expected_time+1.0):
                                motion_state = 'stop'

                        case 'slew':
                            print(".. update slew")

                            send_motion_command = False

                            if motion_duration > (motion_expected_time+1.0):
                                motion_state = 'stop'

                        case 'object':
                            print(".. update object")
                            # for the moment just stop / skip
                            # going to an object is to be implemented will want tracking with it...
                            send_motion_command = False
                            motion_state = 'stop'
                            
                        case _:
                            print(".. update unknown")
                            motion_state = 'stop'

                    if (motion_update_time - motion_start_time) > (motion_expected_time + 1.0):
                        print("motion timeout : ", motion_update_time - motion_start_time, " > ", motion_expected_time+1.0)
                        motion_state = 'stop'
                    
                case 'on-target':
                    print("implement on target")
                    target = await antenna_state.get('astra-target')
                    # on target halts motion and goes to standby for now
                    # may want tracking behavior with fine adjustment later
                       
                    motion_state = 'stop'

            ## Motion modifications and checks
            #print("motion check")
            tgt_az = motion_target['tgt_az']
            tgt_alt = motion_target['tgt_alt']
            tgt_azr = motion_target['tgt_azr']
            tgt_altr = motion_target['tgt_altr']
            
            # adjust for offset tracks
            #print("apply motion offsets")
            offsets = await antenna_state.get('astra-offsets')
            tgt_az, tgt_alt, tgt_azr, tgt_altr = _apply_antenna_offsets(offsets, tgt_az, tgt_alt, tgt_azr, tgt_altr)

            # check and impose motion limits
            #print("apply motion limits")
            limits = await antenna_state.get('mount-limits')
            tgt_az,tgt_alt,tgt_azr,tgt_altr = _apply_antenna_limits(limits, tgt_az, tgt_alt, tgt_azr, tgt_altr)

            ## implement low level motion commands

            #print("SMC : ", send_motion_command)
            # move based on states which will cause motion and motion type
            if send_motion_command:
                print("... send motion command ", tgt_az, tgt_alt, tgt_azr, tgt_altr)
                match motion_state:
                    case 'standby' | 'stop' | 'force-stop' | 'on-target':
                        # check if we still moving and issue another stop
                        print("... motion state = ", motion_state)
                        send_motion_command = False
                        
                        azmd = await antenna_state.get('mount-mode-az')
                        altmd = await antenna_state.get('mount-mode-alt')
                        if azmd.moving:
                            async with mount_lock:
                                mount.stop_motion('1')
                        if altmd.moving:
                            async with mount_lock:
                                mount.stop_motion('2')
                    
                    case 'set-target' | 'update-target':
                        target = await antenna_state.get('astra-target')
                        print("... motion state = ", motion_state)
                        send_motion_command = False

                        match target.target_type:
                            case 'stow' | 'calibration' | 'altaz' | 'radec':
                                print("... target type ", target.target_type)
                                async with mount_lock:
                                    mount.goto_position(tgt_az, tgt_alt, tgt_azr, tgt_altr)
                            case 'slew':
                                print("... target type ", target.target_type)
                                match slew_state['axis']: 
                                    case '1':
                                        print("... az slew")
                                        azsr = slew_state['rate']
                                        az_ccw = slew_state['ccw']
                                        if az_ccw:
                                            azsr = -azsr
                                        print(f"... az slew {az_ccw} {azsr}")

                                        async with mount_lock:
                                            mount.track_rate('1',azsr)
                                        print("... az slew complete")
                                    case '2':
                                        altsr = slew_state['rate']
                                        alt_ccw = slew_state['ccw']
                                        if alt_ccw:
                                            altsr = -altsr
                                        print(f"... alt slew {alt_ccw} {altsr}")
                                        async with mount_lock:
                                            mount.track_rate('2',altsr)
                                        print("... alt slew complete")

                                    case _:
                                        pass
                    case _:
                        send_motion_command = False                        
                        pass                    

        except (serial.SerialException, EOFError) as e:
                motion_state = 'standby'
                if options.verbose:
                    print("serial exception EOF error, attempt reconnect")
                asyncio.sleep(0.1)
                mount.reconnect()
                continue
        except Exception as e:
            motion_state = 'standby'
            #if options.verbose:
            traceback.print_exc() 
            print(e)
            #else:
            #    pass

        loop_cnt += 1

        await asyncio.sleep(motion_period)

"""
    Handle mount telemetry readout and state object update.
"""
async def antenna_telemetry_handler(options, mount, mount_lock, antenna_state, telemetryQ, logQ, position_period):
    # no initial connection
    event_cnt = 0

    while True:

        if options.verbose:
            print("update antenna telemetry handler")

         # grab a command from the queue, if available
        try:
            # get the update timestamp
            utc_timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

            # read from the mount itself, the only expect updates are the motion mode and position
            async with mount_lock:
                encoder = mount.get_motion_scaling() # update each time due to potential for disconnect
                motion_mode_az = mount.get_motion_mode('1')
                motion_mode_alt = mount.get_motion_mode('2')
                mount_position = mount.get_position()

            # update pointing with latest measurements
            # a more sophisticated pointing model could go here
            pointing = {
                'timestamp'       : mount_position['timestamp'],
                'pointing_az'     : mount_position['position_az'],
                'pointing_alt'    : mount_position['position_alt']
            }
            await antenna_state.update('astra-pointing', pointing)

            # update antenna state
            await antenna_state.update('mount-encoder', encoder)
            await antenna_state.update('mount-mode-az', motion_mode_az)
            await antenna_state.update('mount-mode-alt', motion_mode_alt)
            await antenna_state.update('mount-position', mount_position)

            ## telemetry generation 

            # slow rate telemetry for things that are very slow to change
            # commands may cause immediate state telemetry 
            if event_cnt % 10 == 0:
                await telemetryQ.put(antenna_state.calibration)
                await telemetryQ.put(antenna_state.location)
                await telemetryQ.put(antenna_state.encoder)
                await telemetryQ.put(antenna_state.sync)
                await telemetryQ.put(antenna_state.target)
                await telemetryQ.put(antenna_state.offsets)
                await telemetryQ.put(antenna_state.limits)

            # fast rate telemetry for mode and pointing
            # duplicate the imu or gps telemetry to avoid UI subscribing to two channels
            # these update moderately fast but this is for the UI primarily and not feedback
            if event_cnt % 4 == 0:
                await telemetryQ.put(antenna_state.position)
                await telemetryQ.put(antenna_state.rate)
                await telemetryQ.put(antenna_state.mode_az)
                await telemetryQ.put(antenna_state.mode_alt)
                await telemetryQ.put(antenna_state.imu_data)
                await telemetryQ.put(antenna_state.gps_data)

            # send latest pointing estimate at full rate
            await telemetryQ.put(antenna_state.pointing)

            # now check if configuration related info has changed, update local file info
            if event_cnt % 60 == 0:

                cfg_data = await serialize(antenna_state.location)

                with open("/data/config/astra-config.json","wb") as f:
                    f.write(cfg_data)
                    f.flush()

                #print('wrote config information')
                    
        except (serial.SerialException, EOFError) as e:
                if options.verbose:
                    print("serial exception EOF error, attempt reconnect")
                asyncio.sleep(0.1)
                mount.reconnect()
                continue
        except (asyncio.queues.QueueEmpty) as e:
                #if options.verbose:
                #   print("command queue empty in antenna telemetry handler")
                # just pass through and let the other state machine stuff run
                pass
        except Exception as e:
            #if options.verbose:
            print(e)
            traceback.print_exc() 
            #else:
            #    pass
    
        event_cnt += 1

        await asyncio.sleep(position_period)


"""
    Commands come in from the associated mqtt channel 'astra/motion/command' and
    are routed to the serial handler. 
"""
async def command_mqtt_handler(options, eventQ, logQ, cmd_period):

    while True:
        if options.verbose:
            print("update command handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883) as mqtt_client:
                await mqtt_client.subscribe("astra/motion/command/#")

                cmd = None
                try:
                    async for message in mqtt_client.messages:
                        if message is not None:
                            cmd = json.loads(message.payload.decode('utf-8'))
                            await eventQ.put(cmd)
                        if options.verbose:
                            print("sent command: ", message)
                except aiomqtt.MqttError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {cmd_period} seconds ...")
                    status = {'event':'exception', 'source':'command_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {cmd}")
                    status = {'event':'exception', 'source':'command_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'command_mqtt_handler', 'value':f"dispatched {cmd}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except (asyncio.queues.QueueEmpty) as e:
                #if options.verbose:
                #    print("command queue empty in command mqtt handler")
                # just pass through and let the other state machine stuff run
                pass
        
        except Exception as err:
            print(f"command loop global exception {err}")
            traceback.print_exc() 
            pass


        await asyncio.sleep(cmd_period)


"""
    Connects to the MQTT feed for telemetry from the ASTRA Antenna Interface. Pulls in the JSON
    telemetry objects and updates the antenna state object.  
"""
async def ai_mqtt_handler(options, antenna_state, logQ, telemetry_period):

    while True:
        if options.verbose:
            print("update AI telemetry mqtt handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/telemetry/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages:
                        if message is not None:
                            tdata = json.loads(message.payload.decode('utf-8'))
                            try:
                                match tdata['group']:
                                    case 'astra-imu-data':
                                        await antenna_state.update('astra-imu',tdata)
                                    case 'astra-gps-data':
                                        await antenna_state.update('astra-gps',tdata)

                                        cloc = await antenna_state.get('astra-location-data')
                                        if cloc.gps_location and tdata['fix']:
                                            dyr = _to_decimal_year(datetime.now())
                                            decl = _compute_declination(dyr,tdata['latitude'], tdata['longitude'], tdata['altitude'])
                                            gps_loc = {
                                                'latitude'        : tdata['latitude'],
                                                'longitude'       : tdata['longitude'],
                                                'altitude'        : tdata['altitude'],
                                                'declination'     : decl
                                            }

                                            await antenna_state.update('astra-location-data')

                                    case _:
                                        if options.verbose:
                                            print("unknown telemetry event {tdata}")
                            except Exception as err:
                                if options.verbose:
                                    print(f"Unknown telemetry input object from antenna interface {tdata}")

                        if options.verbose:
                            print("got telemetry: ", message)
                except aiomqtt.MqttError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {telemetry_period} seconds ...")
                    status = {'event':'exception', 'group':'astra-motion', 'source':'ai_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'group':'astra-motion', 'source':'ai_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'group':'astra-motion', 'source':'ai_mqtt_handler', 'value':f"dispatched {tdata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except (asyncio.queues.QueueEmpty) as e:
                #if options.verbose:
                #    print("command queue empty in ai mqtt handler")
                # just pass through and let the other state machine stuff run
                pass
        
        except Exception as err:
            print(f"AI telemetry loop global exception {err}")
            traceback.print_exc() 

        await asyncio.sleep(telemetry_period)

"""
    Telemetry from the motion controller is routed to the MQTT 'astra/antenna/telmetry/<event_type>' channel.

    Expected <event_type> keys include 'imu-data', 'gps-data'. Other types are logging or exception messages which 
    should end up on the logging MQTT channels. This is an implict scheme driven by the rp2040 embedded software design. 
"""
async def telemetry_mqtt_handler(options, telemetryQ, logQ, telemetry_period):

    # create MQTT connection to the local nanomq server
    mqtt_client = aiomqtt.Client(hostname=options.mqtt, port=1883)

    while True:

        if options.verbose:
            print("telemetry mqtt handler")

        try:
            tdata = telemetryQ.get_nowait()
            #print("->", tdata)
            if tdata is not None:
                tdata_json = await serialize(tdata)
            else:
                tdata_json = None

            if options.verbose:
                print("telemetry object: ", tdata_json) 
            try:
                async with mqtt_client:
                    grp = tdata['group']
                    await mqtt_client.publish(f"astra/motion/telemetry/{grp}", payload=tdata_json)
                    if options.verbose:
                        print(f"telemetry object of group {grp} sent to mqtt")

            except aiomqtt.MqttError as err:
                if options.verbose:
                    print(f"Connection lost; Reconnect attempt every {telemetry_period} seconds ...")
                
                status = {'event':'exception', 'group':'astra-motion', 'source':'telemetry_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                await logQ.put(status)

                await asyncio.sleep(1)
            except Exception as e:
                print(f"telemetry exception {e}")

            status = {'event':'status', 'group':'astra-motion', 'source':'telemetry_mqtt_handler', 'value':f"dispatched {tdata['event']}"}
            await logQ.put(status)

            if options.verbose:
                print(status)

        except (asyncio.queues.QueueEmpty) as e:
                #if options.verbose:
                #    print("command queue empty in telemetry mqtt handler")
                # just pass through and let the other state machine stuff run
                pass
        
        except Exception as e:
            traceback.print_exc() 

        await asyncio.sleep(telemetry_period)

"""
    Log info from the serial handler is routed to the MQTT 'astra/antenna/log/<event type>' channel. 

    Expected types include 'exception', 'status', 'info'
"""
async def log_mqtt_handler(options, logQ, log_period):

    # create MQTT connection to the local nanomq server
    mqtt_client = aiomqtt.Client(hostname=options.mqtt, port=1883)


    while True:
        if options.verbose:
            print("update log handler")
        try:
            ldata = logQ.get_nowait()

            if ldata is not None:
                ldata_json = json.dumps(ldata)
            else:
                ldata_json = None

            if options.verbose:
                print("log object: ", ldata_json)

            try:
                async with mqtt_client:
                    grp = ldata['group']
                    await mqtt_client.publish(f"astra/log/{grp}", payload=ldata_json.encode('utf-8'))
                    if options.verbose:
                        print("log object sent to mqtt")

            except aiomqtt.MqttError as err:
                if options.verbose:
                    print(f"Connection lost {err}; Reconnect attempt every {log_period} seconds ...")
                status = {'event':'exception', 'group':'astra-motion', 'source':'log_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                await logQ.put(status)
               
                await asyncio.sleep(1)
                continue

            status = {'event':'status', 'group':'astra-motion', 'source':'log_mqtt_handler', 'value':f"dispatched {ldata['event']}"}
            await logQ.put(status)

            if options.verbose:
                print(status)

        except (asyncio.queues.QueueEmpty) as e:
            #if options.verbose:
            #    print("command queue empty in telemetry mqtt handler")
            # just pass through and let the other state machine stuff run
            pass

        except Exception as e:
            traceback.print_exc() 

        await asyncio.sleep(log_period)

def _load_config():

    config = None
    try:
        with open('/data/config/astra-config.json', 'rb') as f:
            config = f.read()
    except FileNotFoundError:
        print(f"Error: The configuration file '/data/config/astra-config.json' was not found.")
        return None
    
    return config

"""
    Primary Thread Startup 
"""
async def main():
    print("astra-motion startup")

    # Parse the Command Line for configuration
    options = parse_command_line()

    # create the antenna mount serial interface, parser, and lock
    ifx = azgti.AzGTi_Interface(options.dev,verbose=options.verbose)
    mount = azgti.AzGTi_Protocol(ifx,verbose=options.verbose)
    mlck = asyncio.Lock()
    antenna_state = AstraAntennaState()

    # load last state - configuration information on startup - if available
    try:
        config = _load_config()
        loc_data = deserialize(config)
        await antenna_state.update('astra-location', loc_data)
        print("config is:")
        print(config)
    except:
        traceback.print_exc() 

    
    print("create async control")
    eventQ = asyncio.Queue() # in bound telemetry events
    telemetryQ = asyncio.Queue() # out bound telemetry
    logQ = asyncio.Queue() # out bound logging

    print("set update periods")
    # set update periods in seconds, a bit fine grained
    
    motion_period = 0.05
    position_period = 0.1
    log_period = 0.1
    telemetry_period = 0.05
    cmd_period = 0.1
     
    print("activate interfaces")
    motion_handler = antenna_motion_handler(options, mount, mlck, antenna_state, eventQ, telemetryQ, logQ, motion_period)
    antenna_handler = antenna_telemetry_handler(options, mount, mlck, antenna_state, telemetryQ, logQ, position_period)
    command_handler = command_mqtt_handler(options,eventQ,logQ,cmd_period)
    input_handler = ai_mqtt_handler(options,antenna_state,logQ,telemetry_period)    
    output_handler = telemetry_mqtt_handler(options,telemetryQ,logQ,telemetry_period)    
    log_handler = log_mqtt_handler(options,logQ,log_period)    

    print("setup asyncio tasks")
    clients = [asyncio.create_task(motion_handler)]
    clients.append(asyncio.create_task(antenna_handler))
    clients.append(asyncio.create_task(command_handler))
    clients.append(asyncio.create_task(input_handler))
    clients.append(asyncio.create_task(output_handler))
    clients.append(asyncio.create_task(log_handler))
 
    print("run")

    await asyncio.gather(*clients)


asyncio.run(main())
