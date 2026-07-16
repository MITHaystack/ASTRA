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
import socket
import traceback
import serial
import json
import time
from datetime import datetime, UTC, timezone

from loguru import logger
import aiomqtt

import azgti

"""
    Antenna pointing model. For the moment this is a direct implementation
    class computing a single synchronization point model. This initial model
    has no time estimation history or assimilation. 
"""
class AstraAntennaPointing:
    def __init__(self):
        self.last_update_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        self._state_lock = asyncio.Lock()

        # last sync point for the mount
        self.sync = {
            'group'         : 'mount-sync',
            'timestamp'     : datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            'sync_az'       : 0.0,
            'sync_alt'      : 0.0,
            'sync_imu'      : False,
            'imu_offset_az' : 0.0,
            'imu_offset_alt': 0.0
        }

        self.pointing = {
            'group'          : 'mount-pointing',
            'timestamp'      : datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            'pointing_az'    : 0.0,
            'pointing_alt'   : 0.0,
            'pointing_model' : None
        }

    async def clear(self):
        async with self._state_lock:
            self.sync['sync_az'] = 0.0
            self.sync['sync_alt'] = 0.0
            self.sync['sync_imu'] = False
            self.sync['sync_delta_az'] = 0.0 # difference between last pointing and sync
            self.sync['sync_delta_alt'] = 0.0

            self.pointing['pointing_az'] = 0.0
            self.pointing['pointing_alt'] = 0.0
            self.pointing['pointing_model'] = None

    """ Treat the provided position as if it is the 0.0 AZ and 0.0 ALT reference point. """
    async def sync_direct(self, current_az, current_alt, sync_az, sync_alt):
        async with self._state_lock:

            self.sync['timestamp'] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.sync['sync_imu'] = False
            self.sync['sync_az'] = sync_az
            self.sync['sync_alt'] = sync_alt
            self.sync['sync_delta_az'] = self.pointing_data['pointing_az'] - sync_az
            self.sync['sync_delta_alt'] = self.pointing_data['pointing_alt'] - sync_alt
            self.pointing['pointing_az'] = current_az - sync_az
            self.pointing['pointing_alt'] = current_alt - sync_alt
    
    """ Treat the provided IMU position as if it is the AZ ALT reference point. Set IMU sync to true. """
    def sync_imu(self, current_az, current_alt, imu_data):
        async with self._state_lock:

            self.sync['timestamp'] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.sync['sync_imu'] = True
            sync_az, sync_alt = imu_data['pointing']
            self.sync['sync_az'] = sync_az
            self.sync['sync_alt'] = sync_alt
            self.pointing['pointing_az'] = current_az - sync_az
            self.pointing['pointing_alt'] = current_alt - sync_alt

        
    """
        The AzGTI antenna mount frame is a north pointing AltAZ configuration which is 
        centered at 0.0 AZ, 0.0 ALT for level and northward pointing. The manual alignment
        is planned for magnetic north alignment via the IMU. As such it is necessary to 
        offset the declination prior to zeroing the mount. The mount itself only zeros to the
        single 0.0,0.0 coordinate at power on and cannot be updated. Coordinates for the mount
        cover +/- 180 degrees on each axis. This allows for over-rotation of each axis and
        over the top tracking subject to cable wrap limitations.
    """
    async def update(self, timestamp, current_az, current_alt):
        async with self._state_lock:
            self.pointing['timestamp'] = timestamp # carry through from interface layer
            # rotate to sync coordinates
            self.pointing['pointing_az'] = current_az - self.sync['sync_az']
            self.pointing['pointing_alt'] = current_alt - self.sync['sync_alt']

    async def sync(self):
        async with self._state_lock:
            return self.sync
    
    async def pointing(self):
        async with self._state_lock:
            return self.pointing




""" Represent the current state of the ASTRA antenna and associated data. State are stored as
    dictionaries with variables that encode related information and any needed model objects.
    Locking is provided for async usage and object update time is tracked to allow for basic
    stale data detection. The essential categories of antenna data include:

        calibration : Information about estimated latencies and the associated calibration model.
        
        location : Geographic position of the mount, assumes a fixed terrestrial location. 
        
        pointing : Best combined pointing estimate and the associated pointing model. Implements synchronization.
        
        target : Motion target mode, goto location, and rates. Allows for tracking / scanning. 

        offsets : Motion offsets primarily used for offset pointing and tracking, useful for gridding objects while tracking

    Dictionaries are used to allow for generic update logic and easy addition of parameters.  


"""
class AstraAntennaState:
    def __init__(self):
        
        # state change lock
        self._state_lock = asyncio.Lock()

        # UTC datetime of last update
        self.update_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.update_period = 0.0 # seconds
        self.update_count = 0

        # calibration, ignore for the moment
        self.calibration = {
            'group'          : 'mount-calibration',
            'imu_delay'     : 0.0,
            'mount_delay'   : 0.0,
            'calibration_model' : None
        }

        # location
        self.location = {
            'group'      : 'mount-location',
            'latitude'  : 0.0,
            'longitude' : 0.0,
            'altitude'  : 0.0
        }

        # mount encoder info
        self.encoder = {
            'group'         : 'mount-encoder',
            'timer_interrupt_freq'  : 0,
            'az_counts_per_rev'     : 0,
            'alt_counts_per_rev'    : 0,
            'step_period'           : 0,
            'high_speed_ratio'      : 1.0,
            'deg_to_counts'         : 0.0
         }

        # last position for the mount
        self.position = {
            'group'         : 'mount-position',
            'timestamp'     : datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            'position_az'   : 0.0,
            'position_alt'  : 0.0,
        }

        # motion target and rate target
        """
            target_info contains the information specific to a type of target / motion control

                standby - take no action without a command, assume on target
                goto - {'target_az':degrees,'target_alt':degrees,'az_rate':deg/sec,'alt_rate':deg/sec}
                radec - {'target_ra':degrees,'target_dec':degrees,'track':True/False}
                object - {'object_name':'sun','moon',}
                slew - {'az_ccw':True/False, 'alt_ccw':True/False, 'az_rate':deg/sec,'alt_rate':deg/sec, time_limit:seconds}
                    Note : Slew commands will stop on a direction change in motion, time_limit expiration, or motion limits
                solar - {}

        """
        self.target = {
            'group'          : 'mount-target',
            'target_type'   : 'standby', # standby, goto, slew, object, radec, SGP4, Horizons
            'target_info'   : {'type':'target-info'},
        }

        # motion offset and rate offsets
        # helps with offset tracking of objects
        self.offsets = {
            'group'          : 'mount-offsets',
            'offset_az'     : 0.0,
            'offset_alt'    : 0.0,
            'offset_azr'    : 0.0,
            'offset_altr'   : 0.0
        }

        # motion limits
        self.limits = {
            'group'          : 'mount-limits',
            'az_cw_limit'   : False,
            'az_ccw_limit'  : False,
            'azr_limit'     : False,
            'alt_cw_limit'  : False,
            'alt_ccw_limit' : False,
            'altr_limit'    : False,
            'limit_model'   : None
        }

        self.mode_az = {
            'group'         : 'mount-az-mode',
            'timestamp'     : datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            'axis'          : '1',
            'init'          : False,
            'moving'        : False,
            'tracking'      : False,
            'blocked'       : False,
            'ccw'           : False,
            'high_speed'    : False,
            'level_sw'      : False,
            'overwrap_cw'   : False,
            'overwrap_ccw'  : False,
            'over_turn'     : False
        }


        self.mode_alt = {
            'group'         : 'mount-alt-mode',
            'timestamp'     : datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            'axis'          : '2',
            'init'          : False,
            'moving'        : False,
            'tracking'      : False,
            'blocked'       : False,
            'ccw'           : False,
            'high_speed'    : False,
            'level_sw'      : False,
            'overwrap_cw'   : False,
            'overwrap_ccw'  : False,
            'over_turn'     : False
        }


        # raw AI imu data - last update event only
        self.imu_data = {}
        # raw AI gps data - last update only
        self.gps_data = {}

    def _match_obj(self,group):
        # match for the group provides weak category validation
        # dictionary composition used for field change tolerant and generic update
        match group:
            case 'mount-calibration':
                gobj = self.calibration
            case 'mount-location':
                gobj = self.location
            case 'mount-encoder':
                gobj = self.encoder
            case 'mount-position':
                gobj = self.position
            case 'mount-pointing':
                gobj = self.pointing
            case 'mount-target':
                gobj = self.target
            case 'mount-offsets':
                gobj = self.offsets
            case 'mount-limits':
                gobj = self.limits
            case 'mount-mode-az':
                gobj = self.mode_az
            case 'mount-mode-alt':
                gobj = self.mode_alt
            case 'imu':
                gobj = self.imu_data
            case 'gps':
                gobj = self.gps_data
            case _:
                raise ValueError(f"AstraAntennaState - unexpected group {group} in serialize")

        return gobj
 
    async def update(self, group, data):
        # grab the object
        gobj = self._match_obj(group)

        # update the object
        async with self._state_lock:
            gobj |= data






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


"""
    Handle motion control of the mount. 
"""
async def antenna_motion_handler(options, mount, mount_lock, antenna_state, antenna_pointing, eventQ, telemetryQ, logQ, motion_period):
    # no initial connection
    event_cnt = 0
    target_state = 'standby' # standby, on_target, goto_target, scan, track_target, track_object, track_radec, stop, quick_stop
    on_target = True 
    update_mount = False

    while True:
        if options.verbose:
            print("update antenna motion handler")

         # grab a command from the queue, if available
        try:
            cmd = eventQ.get_nowait()
            if cmd is not None:
                match cmd['event']:
                    case 'antenna-set-location':
                        loc_data = {    # explicit attempt to access object
                            'latitude'  : cmd['latitude'],
                            'longitude' : cmd['longitude'],
                            'altitude'  : cmd['altitude']
                        }
                        antenna_state.update('mount_location', loc_data)
                    case 'antenna-set-offset':
                        off_data = {
                            'offset_az'     : cmd['offset_az'],
                            'offset_alt'    : cmd['offset_alt'],
                            'offset_azr'    : cmd['offset_azr'],
                            'offset_altr'   : cmd['offset_altr']
                        }
                        antenna_state.update('mount_offsets', loc_data)
                    case 'antenna-goto':
                        tgt_data = {
                            'target_type'   : cmd['target_type'], # goto, slew, solar, lunar, radec, SGP4, Horizons
                            'target_info'   : cmd['target_info'],
                        }

                    case 'antenna-slew':
                        pass
                    case 'antenna-stop':
                        if cmd['force_stop']:
                            target_state = 'force-stop'
                        else:
                            target_state = 'stop'
                        
                        

                    case _:
                        if options.verbose:
                            print(f"unknown antenna motion command {cmd['event]}")
      
        except (serial.SerialException, EOFError) as e:
                if options.verbose:
                    print("serial exception EOF error, attempt reconnect")
                asyncio.sleep(0.1)
                mount.ifx.reconnect()
                continue
        except Exception as e:
            if options.verbose:
                print(e)
            else:
                pass

        
        # check for limits

        # on limit stop axis motion and flag direction, back out?

        match target_state:
            case 'none':
                pass
            case 'on_target':
                pass
            case 'goto_target':
                pass
            case 'scan':
                pass
            case 'track_target':
                pass
            case 'track_object':
                pass
            case 'track_radec':
                pass
            case 'force-stop':
                async with mount_lock:
                    mount.force_stop_motion()
                target_state = 'standby'
            case 'stop':
                async with mount_lock:
                    mount.stop_motion(azgti.Axis.AZ)
                    mount.stop_motion(azgti.Axis.ALT)       
                target_state = 'standby'     
            
        # issue updated position and speed command if not on target
        try:
            if update_mount:
                pass   # issue command if not on target

        except (serial.SerialException, EOFError) as e:
                if options.verbose:
                    print("serial exception EOF error, attempt reconnect")
                asyncio.sleep(0.1)
                mount.ifx.reconnect()
                continue
        except Exception as e:
            if options.verbose:
                print(e)
            else:
                pass


        if options.verbose and event is not None:
            print(f"event {event_cnt} : {event}")
        elif options.verbose and event is None:
            print("event is None")


        await asyncio.sleep(motion_period)

"""
    Handle mount telemetry readout and state object update.
"""
async def antenna_telemetry_handler(options, mount, mount_lock, antenna_state, antenna_pointing, telemetryQ, logQ, position_period):
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
                motion_mode_az = mount.get_motion_mode(azgti.Axis.AZ)
                motion_mode_alt = mount.get_motion_mode(azgti.Axis.ALT)
                pos = mount.get_position()

            # update pointing model with latest measurements
            # broken out because it is manipulated by the pointing model 
            antenna_pointing.update(pos['timestamp'],pos['position_az'],pos['position_alt'])

            # update antenna state
            antenna_state.update('mount-encoder', encoder)
            antenna_state.update('mount-mode-az', motion_mode_az)
            antenna_state.update('mount-mode-alt', motion_mode_alt)
            antenna_state.update('mount-position', pos)

            # slow rate telemetry for things that are very slow to change
            if event_cnt % 10 == 0:
                telemetryQ.put(antenna_state.calibration)
                telemetryQ.put(antenna_state.location)
                telemetryQ.put(antenna_state.encoder)
                telemetryQ.put(antenna_state.sync)
                telemetryQ.put(antenna_state.target)
                telemetryQ.put(antenna_state.offsets)
                telemetryQ.put(antenna_state.limits)

            # fast rate telemetry for mode, position, and pointing
            # do not duplicate the imu telemetry
            telemetryQ.put(antenna_state.position)
            telemetryQ.put(antenna_state.mode_az)
            telemetryQ.put(antenna_state.mode_alt)

            # send latest pointing estimate at full rate
            telemetryQ.put(antenna_pointing.pointing())


        except (serial.SerialException, EOFError) as e:
                if options.verbose:
                    print("serial exception EOF error, attempt reconnect")
                asyncio.sleep(0.1)
                mount.ifx.reconnect()
                continue
        except Exception as e:
            if options.verbose:
                print(e)
            else:
                pass
       
        if options.verbose and event is not None:
            print(f"event {event_cnt} : {event}")
        elif options.verbose and event is None:
            print("event is None")

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
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/motion/command")

                cmd = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            cmd = json.loads(message.payload.decode('utf-8'))
                            await eventQ.put(cmd)
                        if options.verbose:
                            print("sent command: ", message)
                except aiomqtt.ConnectError as err:
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

        except Exception as err:
            print(f"command loop global exception {err}")
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
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/telemetry/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            tdata = json.loads(message.payload.decode('utf-8'))
                            try:
                                match tdata['event']:
                                    case 'ai-imu-data':
                                        antenna_state.update('imu',tdata)
                                    case 'ai-gps-data':
                                        antenna_state.update('gps',tdata)
                                    case _:
                                        if options.verbose:
                                            print("unknown telemetry event {tdata}")
                            except Exception as err:
                                if options.verbose:
                                    print(f"Unknown telemetry input object from antenna interface {tdata}")

                        if options.verbose:
                            print("got telemetry: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {telemetry_period} seconds ...")
                    status = {'event':'exception', 'source':'ai_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'source':'ai_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'ai_mqtt_handler', 'value':f"dispatched {tdata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"AI telemetry loop global exception {err}")
            pass

        await asyncio.sleep(telemetry_period)

"""
    Telemetry from the motion controller is routed to the MQTT 'astra/antenna/telmetry/<event_type>' channel.

    Expected <event_type> keys include 'imu-data', 'gps-data'. Other types are logging or exception messages which 
    should end up on the logging MQTT channels. This is an implict scheme driven by the rp2040 embedded software design. 
"""
async def telemetry_mqtt_handler(options, telemetryQ, logQ, telemetry_period):

    # create MQTT connection to the local nanomq server
    mqtt_client = aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True)

    while True:

        if options.verbose:
            print("telemetry mqtt handler")

        try:
            tdata = telemetryQ.get_nowait()
            
            if tdata is not None:
                tdata_json = json.dumps(tdata)
            else:
                tdata_json = None

            if options.verbose:
                print("telemetry object: ", tdata_json) 
            try:
                async with mqtt_client:
                    grp = tdata['group']
                    await mqtt_client.publish(f"astra/antenna/telemetry/{grp}", payload=tdata_json.encode('utf-8'))
                    if options.verbose:
                        print(f"telemetry object of group {grp} sent to mqtt")

            except aiomqtt.ConnectError as err:
                if options.verbose:
                    print(f"Connection lost; Reconnect attempt every {telemetry_period} seconds ...")
                
                status = {'event':'error', 'source':'telemetry_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                await logQ.put(status)

                await asyncio.sleep(1)
            except Exception as e:
                print(f"telemetry exception {e}")

            status = {'event':'status', 'source':'telemetry_mqtt_handler', 'value':f"dispatched {tdata['event']}"}
            await logQ.put(status)

            if options.verbose:
                print(status)

        except Exception as e:
            pass

        await asyncio.sleep(telemetry_period)

"""
    Log info from the serial handler is routed to the MQTT 'astra/antenna/log/<event type>' channel. 

    Expected types include 'exception', 'status', 'info'
"""
async def log_mqtt_handler(options, logQ, log_period):

    # create MQTT connection to the local nanomq server
    mqtt_client = aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True)


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
                    evt = ldata['event']
                    await mqtt_client.publish(f"astra/antenna/log/{evt}", payload=ldata_json.encode('utf-8'))
                    if options.verbose:
                        print("log object sent to mqtt")

            except aiomqtt.ConnectError as err:
                if options.verbose:
                    print(f"Connection lost {err}; Reconnect attempt every {log_period} seconds ...")
                status = {'event':'exception', 'source':'log_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                await logQ.put(status)
               
                await asyncio.sleep(1)
                continue


            status = {'event':'status', 'source':'log_mqtt_handler', 'value':f"dispatched {ldata['event']}"}
            await logQ.put(status)

            if options.verbose:
                print(status)

        except Exception as e:
            pass

        await asyncio.sleep(log_period)

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
    antenna_pointing = AstraAntennaPointing()

    print("create async control")
    eventQ = asyncio.Queue() # in bound telemetry events
    telemetryQ = asyncio.Queue() # out bound telemetry
    logQ = asyncio.Queue() # out bound logging

    print("set update periods")
    # set update periods in seconds, a bit fine grained
    
    motion_period = 0.025
    position_period = 0.1
    log_period = 0.1
    telemetry_period = 0.1
    cmd_period = 0.1
     
    print("activate interfaces")
    motion_handler = antenna_motion_handler(options, mount, mlck, antenna_state, antenna_pointing, eventQ, telemetryQ, logQ, motion_period)
    antenna_handler = antenna_telemetry_handler(options, mount, mlck, antenna_state, antenna_pointing, telemetryQ, logQ, position_period)
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
