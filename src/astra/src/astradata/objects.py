"""
    astradata.py

    This software implements data objects for ASTRA so that they operate like dictionaries but with
    asyncio based locking of modifications and reads. 

"""

import asyncio
import traceback
import copy
import json
import msgpack
import numpy as np
from inspect import iscoroutinefunction

from datetime import datetime, UTC, timezone

from dataclasses import dataclass, asdict, field, fields
from typing import Optional

##
## ASTRA System Data
##

""" Base object class to enable dictionary like | and |= updates and [] lookups. 
    ASTRA data all looks like dictionaries. The base class provides asyncio state locking
    for updates performed by dictionary access or dictionary set operations.
"""
class AstraObject:
    def __init__(self):
        """ Base object has some uniform local info for each derived object. """
        self.group = 'unknown' # group is used for namespace elaboration 
        self.event = 'none' # event is used for object category sorting: status, exception, command, telemetry
        self.last_update_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.update_count = 0
        self._lock = asyncio.Lock()

    def __ror__(self, other: dict) -> "AstraObject":
        """Enables dictionary | object syntax in async context: await obj | dict """
        if not isinstance(other, dict):
            return NotImplemented
        return self.__class__(**({**other, **self.__dict__}))

    def __ior__(self, other: dict) -> "AstraObject":
        """Enables object |= dictionary syntax in async context: await obj |= dict """
        if not isinstance(other, dict):
            return NotImplemented
        for key, value in other.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self

    def __setitem__(self, key: str, value):
        """Allows dictionary-style updates, e.g., instance["status"] = "running\""""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise KeyError(f"Invalid key: {key}")  
    
    def __getitem__(self, key: str):
        """Allows dictionary-style access, e.g., instance["status"]"""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"Invalid key: {key}")
    
    def keys(self):
        return [f.name for f in fields(self)]
    
    async def locked_update(self, other: dict):
        """ locked update method for async contexts must use await"""
        async with self._lock:
            if not isinstance(other, dict):
                return NotImplemented
            for key, value in other.items():
                if hasattr(self, key):
                    setattr(self, key, value)

            self.last_update_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.update_count += 1

            return self            


def _remove_callables(data):
    # Filter out items where the value is a method, function, or callable
    return {
        k: v for k, v in data 
        if not callable(v) and not iscoroutinefunction(v)
    }

##
## Object serialization and deserialization with lock awareness
## 
# serialize Astra Object as dict to json or msgpack bytes
async def serialize(obj, fmt='json'):
    async with obj._lock:
        sdict = asdict(obj,dict_factory=_remove_callables)
        #print("-->", sdict)
        sdict['group'] = obj.group
        sdict['event'] = obj.event
        #print(sdict)
        match fmt:
            case 'json':
                sd = json.dumps(sdict).encode('utf-8')
            case 'msgpack':
                sd = msgpack.packb(sdict,use_bin_type=True)
            case _:
                raise ValueError(f"unknown serialization format {fmt}")
    return sd
    
# deserialize object from json or msgpack bytes to dictionary, update is separate
def deserialize(payload, fmt='json'):
        match fmt:
            case 'json':
                obj = json.loads(payload.decode('utf-8'))
            case 'msgpack':
                obj = msgpack.unpackb(payload, raw=False)
            case _:
                raise ValueError(f"unknown serialization format {fmt}")
        
        return obj
    

""" Synchronization Object """
@dataclass
class AstraSyncData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    sync_az         : float = 0.0
    sync_alt        : float = 0.0
    sync_imu        : bool  = False
    imu_offset_az   : float = 0.0
    imu_offset_alt  : float = 0.0

    def __post_init__(self):
        super().__init__()
        self.group = 'astra-sync-data'

    async def clear(self):
        async with self._lock:
            self.sync['sync_az'] = 0.0
            self.sync['sync_alt'] = 0.0
            self.sync['sync_imu'] = False
            self.sync['sync_delta_az'] = 0.0 # difference between last pointing and sync
            self.sync['sync_delta_alt'] = 0.0

    """ Treat the provided position as if it is the 0.0 AZ and 0.0 ALT reference point. """
    async def sync_direct(self, current_az, current_alt, sync_az, sync_alt):
        async with self._lock:
            self.sync['timestamp'] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.sync['sync_imu'] = False
            self.sync['sync_az'] = sync_az
            self.sync['sync_alt'] = sync_alt
            self.sync['sync_delta_az'] = current_az - sync_az
            self.sync['sync_delta_alt'] = current_alt - sync_alt
            
    
    """ Treat the provided IMU position as if it is the AZ ALT reference point. Set IMU sync to true. """
    async def sync_imu(self, current_az, current_alt, imu_data, decl, imu_offset_az, imu_offset_alt):
        async with self._state_lock:
            self.sync['timestamp'] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.sync['sync_imu'] = True
            sync_az, sync_alt = imu_data['pointing']
            # magnetic azimuth pointing
            self.sync['sync_az'] = sync_az + decl
            self.sync['sync_alt'] = sync_alt
            self.sync['sync_delta_az'] = current_az - sync_az + decl
            self.sync['sync_delta_alt'] = current_alt - sync_alt

""" Pointing Object """
@dataclass
class AstraPointingData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    pointing_az     : float = 0.0
    pointing_alt    : float = 0.0
 
    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'astra-pointing-data'

    """
        The AzGTI antenna mount frame is a north pointing AltAZ configuration which is 
        centered at 0.0 AZ, 0.0 ALT for level and northward pointing. The manual alignment
        is planned for magnetic north alignment via the IMU. As such it is necessary to 
        offset the declination prior to zeroing the mount. The mount itself only zeros to the
        single 0.0,0.0 coordinate at power on and cannot be updated. Coordinates for the mount
        cover +/- 180 degrees on each axis. This allows for over-rotation of each axis and
        over the top tracking subject to cable wrap limitations.
    """
    async def update(self, syncdata, timestamp, current_az, current_alt):
        async with self._lock:
            self.timestamp = timestamp # carry through from interface layer
            # rotate to sync coordinates
            self.pointing_az = current_az - syncdata['sync_az']
            self.pointing_alt = current_alt - syncdata['sync_alt']


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
        async with self._lock:
            self.pointing['timestamp'] = timestamp # carry through from interface layer
            # rotate to sync coordinates
            self.pointing['pointing_az'] = current_az - self.sync['sync_az']
            self.pointing['pointing_alt'] = current_alt - self.sync['sync_alt']

    async def sync(self):
        async with self._lock:
            return self.sync
    
    async def pointing(self):
        async with self._lock:
            return self.pointing


""" Mount Calibration Object """
@dataclass
class AstraCalibrationData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    imu_delay       : float = 0.0
    mount_delay     : float = 0.0

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'astra-calibration-data'

""" Mount Location Object """
@dataclass
class AstraLocationData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    site_name       : str = field(default_factory=lambda:"unknown")
    gps_location    : bool = False
    latitude        : float = 0.0
    longitude       : float = 0.0
    altitude        : float = 0.0
    declination     : float = 0.0

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'astra-location-data'

""" Mount encoder Object """
@dataclass
class AstraEncoderData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    timer_interrupt_freq  : int = 0
    az_counts_per_rev     : int = 0
    alt_counts_per_rev    : int = 0
    step_period           : int = 0
    high_speed_ratio      : float = 1.0
    deg_to_counts         : float = 0.0

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'mount-encoder-data'

""" Mount current position Object """
@dataclass
class AstraPositionData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    position_az     : float = 0.0
    position_alt    : float = 0.0

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'mount-position-data'

""" Mount current rate Object """
@dataclass
class AstraRateData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    az_rate         : float = 0.0
    alt_rate        : float = 0.0

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'mount-rate-data'

"""
            target_info contains the information specific to a type of target / motion control

                standby - take no action without a command, assume on target, no needed info, stop moving if moving
                stow - goto the stow position
                calibration - perform calibration pattern for IMU and magnetometer around current default pointing
                altaz - {'target_az':degrees,'target_alt':degrees,'az_rate':deg/sec,'alt_rate':deg/sec}
                radec - {'target_ra_h':hours,'target_ra_m':minutes,'target_ra_s':seconds,'target_dec':degrees,'track':True/False}
                object - {'object_type':'planet' | , 'object_name':'planet name' | 'moon' | 'sun', 'track':True/False} - uses de440s.bsp from JPL}
                object - {'object_type':'catalog','object_name':'name from catalog','track':True/False - needs online access for download}
                sgp4 - {'ephemeris_type':'tle'|'omm','object_name':'name','track':True/False, 'tle1':'line1','tle2':'line2' or 'omm_json':json string of omm data}
                slew - {'axis':0 (az)| 1 (alt) | 2 (both),'az_ccw':True/False, 'alt_ccw', 'timeout':seconds}
                    Note : Slew commands will stop on a direction change in motion, time_limit expiration, or motion limits
                        Slew rate is set by the separate rate setting command and can be updated. 
                horizons - {} ; API call using astroquery that requires internet access, use JPL Horizons data

"""
@dataclass
class AstraTargetData(AstraObject):
    timestamp      : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    target_type    : str = 'standby' # standby, goto, radec, slew, object, sgp4, horizons
    target_info    : dict = field(default_factory=lambda: {"type": "target-info-data"})

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'astra-target-data'

""" Mount offsets Object """
@dataclass
class AstraOffsetsData(AstraObject):
    offset_az     : float = 0.0
    offset_alt    : float = 0.0
    offset_azr    : float = 0.0
    offset_altr   : float = 0.0

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'astra-offsets-data'

""" Mount limits Object """
@dataclass
class AstraLimitsData(AstraObject):
    az_cw_limit     : float = 185.0     # hard starting limit, some overwrap
    az_ccw_limit    : float = -185.0    # hard starting limits, some overwrap
    alt_down_limit  : float = -5.0      # hard starting limits, a bit down
    alt_up_limit    : float = 90.0      # hard starting limits, all the way to zenith, over takes cmd driven change
    azr_limit       : float = 5.0
    altr_limit      : float = 5.0

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'mount-limits-data'

""" Mount azimuth mode Object """
@dataclass
class AstraAzimuthModeData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    axis            : str = '1'
    init            : bool = False
    moving          : bool = False
    tracking        : bool = False
    blocked         : bool = False
    ccw             : bool = False
    high_speed      : bool = False
    level_sw        : bool = False
    overwrap_cw     : bool = False
    overwrap_ccw    : bool = False
    over_turn       : bool = False
   
    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'mount-az-mode-data'

""" Mount azimuth mode Object """
@dataclass
class AstraAltitudeModeData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    axis            : str = '2'
    init            : bool = False
    moving          : bool = False
    tracking        : bool = False
    blocked         : bool = False
    ccw             : bool = False
    high_speed      : bool = False
    level_sw        : bool = False
    overwrap_up     : bool = False
    overwrap_down   : bool = False
    over_turn       : bool = False
   
    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'mount-alt-mode-data'
        
@dataclass
class AstraIMUData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    temperature     : float = 0.0
    calibrated      : bool = False
    cal_status      : list[int] = field(default_factory=lambda: [0,0,0,0])
    euler           : np.ndarray = field(default_factory=lambda: np.zeros(3))
    pointing        : np.ndarray = field(default_factory=lambda: np.zeros(3))
    gravity         : np.ndarray = field(default_factory=lambda: np.zeros(3))
    gyro            : np.ndarray = field(default_factory=lambda: np.zeros(3))
    acceleration    : np.ndarray = field(default_factory=lambda: np.zeros(3))
    linear_acceleration : np.ndarray = field(default_factory=lambda: np.zeros(3))
    magnetic        : np.ndarray = field(default_factory=lambda: np.zeros(3))
    quaternion      : np.ndarray = field(default_factory=lambda: np.zeros(4))

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'astra-imu-data'

@dataclass
class AstraGPSData(AstraObject):
    timestamp       : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    utc             : str = "",
    adata           : bool = False
    fix             : bool = False
    fixQ            : str = ""
    fixQ3d          : str = ""
    sats            : int = 0
    track_angle_deg : float = 0.0
    speed           : float = 0.0
    hdil            : float = 0.0
    hgeoid          : float = 0.0
    pdop            : float = 0.0
    vdop            : float = 0.0
    latitude        : float = 0.0
    longitude       : float = 0.0
    altitude        : float = 0.0 
    nmea            : str = ""

    def __post_init__(self):
        super().__init__()
        self.event = 'telemetry'
        self.group = 'astra-gps-data'

""" Motion control program status for UI usage Object """
@dataclass
class AstraMostionControllerStatusData(AstraObject):
    timestamp         : str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    status            : str = 'Startup'

    def __post_init__(self):
        super().__init__()
        self.group = 'astra-motion-status-data'

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
@dataclass
class AstraAntennaState(AstraObject):

    calibration = AstraCalibrationData()
    location = AstraLocationData()
    encoder = AstraEncoderData()
    sync = AstraSyncData()
    position = AstraPositionData() # direction where the mount says it is oriented
    pointing = AstraPointingData() # directino where the adjusted controller data thinks it is oriented
    rate = AstraRateData()
    target = AstraTargetData()

    offsets = AstraOffsetsData()
    limits = AstraLimitsData()
    mode_az = AstraAzimuthModeData()
    mode_alt =AstraAltitudeModeData()

    imu_data = AstraIMUData()
    gps_data = AstraGPSData()

    motion_controller_status = AstraMostionControllerStatusData()

    def __post_init__(self):
        super().__init__()
        self.update_count = 0

    def _match_obj(self,group):
        # match for the group provides weak category validation
        # dictionary composition used for field change tolerant and generic update
        match group:
            case 'astra-calibration':
                gobj = self.calibration
            case 'astra-location':
                gobj = self.location
            case 'astra-sync':
                gobj = self.sync
            case 'astra-pointing':
                gobj = self.pointing
            case 'astra-target':
                gobj = self.target
            case 'astra-offsets':
                gobj = self.offsets
            case 'astra-imu':
                gobj = self.imu_data
            case 'astra-gps':
                gobj = self.gps_data
            case 'mount-encoder':
                gobj = self.encoder
            case 'mount-position':
                gobj = self.position
            case 'mount-rate':
                gobj = self.rate
            case 'mount-limits':
                gobj = self.limits
            case 'mount-mode-az':
                gobj = self.mode_az
            case 'mount-mode-alt':
                gobj = self.mode_alt
            case 'astra-motion-status':
                gobj = self.motion_controller_status
            case _:
                raise ValueError(f"AstraState - unexpected group {group} in _match_obj")

        return gobj
 
    async def update(self, group, data, update_ts = False):
        # grab the object after locking
        gobj = self._match_obj(group)

        # lock and update the object, lock implicit in parent class
        await gobj.locked_update(data)

        # update the timestamp if it has one
        if update_ts:
            gobj.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        # track last update for catching stale data later...
        gobj.last_update_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.update_count += 1

    async def get(self,group):
        # grab the object while locked
        gobj = self._match_obj(group)

        # lock and copy, lock implicit in parent class
        async with gobj._lock:
            robj = copy.copy(gobj)

        return robj


##
## Commands
## 

""" Helper method for validating commands"""
def validate_command(cmd,dclass):
    valid_keys = {f.name for f in fields(dclass)}
    ekey = set(cmd.keys()) - set(valid_keys)
    if ekey:
        raise ValueError(f"Invalid command keys found: {ekey}")
    
    return True

""" Mount stop axis command - soft stop selected motion axes """
@dataclass
class AstraStopCommand(AstraObject):
    timestamp       : datetime = None
    azimuth         : bool = False
    altitude        : bool = False   

    def __init__(self):
        super().__init__()
        self.group = 'mount-stop-cmd'
        self.event = 'command'

""" Mount estop command - hard stop both motion axes """
@dataclass
class AstraEStopCommand(AstraObject):
    timestamp       : datetime = None
    estop           : bool = False

    def __init__(self):
        super().__init__()
        self.group = 'mount-estop-cmd'
        self.event = 'command'


""" Mount Set Location command Object """
@dataclass
class AstraSetLocationCommand(AstraObject):
    timestamp       : datetime = None
    site_name       : str = "unknown"
    use_gps         : bool = False
    latitude        : float = 0.0
    longitude       : float = 0.0
    altitude        : float = 0.0   

    def __init__(self):
        super().__init__()
        self.group = 'astra-set-location-cmd'
        self.event = 'command'


""" Set Synchronization command Object """
@dataclass
class AstraSyncCommand(AstraObject):
    timestamp       : datetime = None
    sync_az         : float = 0.0
    sync_alt        : float = 0.0
    sync_values     : bool = True
    sync_telemetry  : bool = False
    sync_imu        : bool  = False
    imu_offset_az   : float = 0.0
    imu_offset_alt  : float = 0.0

    def __init__(self):
        super().__init__()
        self.group = 'mount-sync-cmd'
        self.event = 'command'

""" Mount set offsets command Object """
@dataclass
class AstraSetOffsetsCommand(AstraObject):
    timestamp       : datetime = None
    offset_az     : float = 0.0
    offset_alt    : float = 0.0
    offset_azr    : float = 0.0
    offset_altr   : float = 0.0

    def __init__(self):
        super().__init__()
        self.group = 'astra-set-offsets-cmd'
        self.event = 'command'

""" Mount set rates command Object """
@dataclass
class AstraSetRateCommand(AstraObject):
    timestamp       : datetime = None
    az_rate         : float = 0.0
    alt_rate        : float = 0.0

    def __init__(self):
        super().__init__()
        self.group = 'astra-set-rate-cmd'
        self.event = 'command'


""" Mount set limits command Object """
@dataclass
class AstraSetLimitsCommand(AstraObject):
    timestamp       : datetime = None
    az_cw_limit_val     : float = 185.0     # hard starting limit, some overwrap
    az_ccw_limit_val    : float = -185.0    # hard starting limits, some overwrap
    alt_down_limit_val  : float = -5.0      # hard starting limits, a bit down
    alt_up_limit_val    : float = 90.0      # hard starting limits, all the way to zenith, over takes cmd driven change
    azr_limit_val       : float = 5.0
    altr_limit_val      : float = 5.0

    allow_az_overwrap   : bool = False
    allow_alt_overwrap : bool = False

    def __init__(self):
        super().__init__()
        self.group = 'mount-set-limits-cmd'

""" 
    This is the primary command to point the ASTRA antenna and imager. The
    implemented behavior depends on the target type as do the secondary fields
    associated with the target_info dictionary. See the data object comments for
    a discussion of the needed fields. 
"""
@dataclass
class AstraSetTargetCommand(AstraObject):
    timestamp       : datetime = None
    target_type    : str = 'standby' # standby, stow, calibration, altaz, radec, slew, object, sgp4, horizons
    target_info    : dict = field(default_factory=lambda: {"group": "target-info-data"})

    def __init__(self):
        super().__init__()
        self.group = 'astra-set-target-cmd'
        self.event = 'command'


""" Noise Diode command Object """
@dataclass
class AstraSetNoiseDiodeCommand(AstraObject):
    timestamp       : datetime = None
    mode : str = 'DISABLE'

    def __init__(self):
        super().__init__()
        self.group = 'astra-ai-diode-cmd'
        self.event = 'command'