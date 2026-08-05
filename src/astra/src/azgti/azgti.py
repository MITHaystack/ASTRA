"""
    azgti.py

    This module provides a serial control interface for the synscan 3.3 based
    Skywatcher AzGTi mount. The serial interface is managed with an async
    compatible framework. 

"""

import asyncio
import argparse
import os
import sys
import traceback
import serial
import json
import time
from datetime import datetime, UTC, timezone
from enum import Enum

#### temp debug


def _int2hex(data,ndigits=6):
    ''' Convert data prior to send to the motors following 
        Synscan Motor Protocol rules

    * 24 bits Data Sample: for HEX number 0x123456, in the data segment of
        a command or response, it is sent/received in this order: "5" "6" "3" "4" "1" "2".
    * 16 bits Data Sample: For HEX number 0x1234, in the data segment of a command or 
        response, it is sent/received in this order: "3" "4" "1" "2". 
    * 8 bits Data Sample: For HEX number 0x12, in the data segment of a command or
        response, it is sent/received in this order: "1" "2".
    '''

    assert (ndigits in [0,1,2,4,6]), "ndigits must be one of [0,2,4,6]"
    if ndigits==6:
        strData=f'{data:06X}'
    if ndigits==4:
        strData=f'{data:04X}'
    if ndigits==2:
        strData=f'{data:02X}'
    if ndigits==1:
        strData=f'{data:01X}'
    if ndigits==0:
        strData=f''
    length=len(strData)
    strHEX=''
    for i in range(length,0,-2):
        strHEX=strHEX+f'{strData[i-2:i]}'
    return strHEX
    
def _hex2int(data):
    ''' Convert data recived from motors following 
        Synscan Motor Protocol rules

    * 24 bits Data Sample: for HEX number 0x123456, in the data segment of
        a command or response, it is sent/received in this order: "5" "6" "3" "4" "1" "2".
    * 16 bits Data Sample: For HEX number 0x1234, in the data segment of a command or 
        response, it is sent/received in this order: "3" "4" "1" "2". 
    * 8 bits Data Sample: For HEX number 0x12, in the data segment of a command or
        response, it is sent/received in this order: "1" "2".
    '''
    strData=data
    length=len(strData)
    assert (length<=6), f"Max allow value is FFFFFF. Actual={strData}"
    #Special cases
    #Some commands dont return data
    if length==0:
        return ''
    #Status msg only return 12 bits (1.5bytes or 3 hex digits)
    if length==3:
        return strData
    #General case. Returned msd has 1,2,3 bytes (2,4 or 6 hex digits)
    strHEX=''
    for i in range(length,0,-2):
        strHEX=strHEX+f'{strData[i-2:i]}'
    v=int(strHEX,16)
    return v


def _decode_status(hexstring):
    ''' Decode Status msg.
    Status msg is 12bits long (3 HEX digits). 
    
    HEX digit1 bits:

    * B0: 1=Tracking,0=Goto
    * B1: 1=CCW,0=CW
    * B2: 1=Fast,0=Slow

    HEX digit2 bits:

    * B0: 1=Running,0=Stopped
    * B1: 1=Blocked,0=Normal

    HEX digit3 bits:

    * B0: 0 = Not Init,1 = Init done
    * B1: 1 = Level switch on

    The decode value is returned as a dictionary with the following keys:

    * Tracking
    * CCW
    * FastSpeed
    * Stopped
    * Blocked
    * InitDone
    * LevelSwitchOn

    '''
    A=int(hexstring[0],16)       
    B=int(hexstring[1],16)
    C=int(hexstring[2],16)
    status=dict()
    status['Tracking']=bool(A & 0x01)
    status['CCW']=bool((A & 0x02) >> 1)
    status['FastSpeed']=bool((A & 0x04) >> 2)
    status['Stopped']=not(B & 0x01)
    status['Blocked']=bool((B & 0x02) >> 1)
    status['InitDone']=not(C & 0x01)
    status['LevelSwitchOn']=bool((B & 0x02) >> 1)
    return status

def axis_set_motion_mode(axis,cpr,Tracking,CW=True,fastSpeed=False):
    '''Set Motion Mode.

    NOTE: Channel will always be set to Tracking Mode after stopped

    Motion mode msg is 1byte msg (2 HEX digits)

    HEX Digit 1 bits:

        * B0: 0=Goto, 1=Tracking
        * B1: 0=Slow, 1=Fast  (T)
                0=Fast, 1=Slow  (G)
        * B2: 0=S/F, 1=Medium
        * B3: 1x SlowGoto

    HEX Digit 2 bits:  

        * B0: 0=CW,1=CCW
        * B1: 0=Noth,1=South
        * B2: 0=Normal Goto,1=Coarse Goto

    '''
    if not Tracking:
        if fastSpeed:
            speedBit=0
        else:
            speedBit=1
    else:
        if fastSpeed:
            speedBit=1
        else:
            speedBit=0
    if Tracking:
        value=16
    else:
        value=0
    value=value+speedBit*32+CW

    return value


###

class Axis(Enum):
    AZ = 1
    ALT = 2
    BOTH = 3

class MotorDevice(Enum):
    AZ = 16
    RA = 16
    ALT = 17
    DEC = 17

class GotoMode(Enum):
    GOTO = 0
    TRACK = 1

class Speed(Enum):
    SLOW = 0
    FAST = 1

class Direction(Enum):
    CW = 0
    CCW = 1
    N = 0
    S = 1

class StatusMask(Enum):
    TG_MASK   = 0x0001
    CCW_MASK  = 0x0002
    SPD_MASK  = 0x0004
    RUN_MASK  = 0x0020
    BLK_MASK  = 0x0010
    INIT_MASK = 0x0100
    LVL_MASK  = 0x0200
 
class ModeMask(Enum):
    TG_MASK     = 0x20
    SPD_MASK    = 0x10
    COARSE_MASK = 0x04
    SOUTH_MASK  = 0x02
    CCW_MASK    = 0x01
    

class TrackingMode(Enum):
    OFF = 0
    ALTAZ = 1
    EQUATORIAL = 2
    PEC = 3

class CMDError(Enum):
    UNKNOWN = 0
    CMD_LEN = 1
    MOTOR_NOT_STOPPED = 2
    INVALID_CHARACTER = 3
    NOT_INITIALIZED = 4
    DRIVER_SLEEPING = 5
    PEC_TRAINING = 7
    NO_PEC_DATA = 8


"""
    Provides a serial interface to the AzGTi wired telescope mount via their 
    slightly customized synscan 3.3 protocol. Handles the associated
    serial port interface using a locked async framework. The protocol
    is handled by a separate object. 

    The network and wireless interface is not yet supported. 

"""
class AzGTi_Protocol:
    def __init__(self, interface, verbose=False, logging=None):

        self.ifx = interface
        self.verbose = verbose
        self.logging = logging

        self._motion_scaling_setup = False

        self.timer_interrupt_freq = 0
        self.az_counts_per_rev = 0 
        self.alt_counts_per_rev = 0
        self.step_period = 0
        self.high_speed_ratio = 0

        # first thing is to load version
        self.version = self.get_version()
        if self.verbose:
            print(f"mount version: {self.version}")
        # second thing is to load motion scaling
        self._setup_motion_scaling()

    def _error_name(self, val):
        match self._hstr_int(self._strip(val,True)):
            case CMDError.UNKNOWN:
                return 'known unknown'
            case CMDError.CMD_LEN:
                return 'bad length'
            case CMDError.MOTOR_NOT_STOPPED:
                return 'motor not stopped'
            case CMDError.INVALID_CHARACTER:
                return 'invalid character'
            case CMDError.NOT_INITIALIZED:
                return 'not initialized'
            case CMDError.DRIVER_SLEEPING:
                return 'driver sleeping'
            case CMDError.PEC_TRAINING:
                return 'PEC training'
            case CMDError.NO_PEC_DATA:
                return 'no PEC data'
            case _:
                return 'unknown unknown'


    """ compute a required hex string length for a given integer value, must be 0,1,2,4,6 """
    def _hex_len(self,v):
        hl = max(1,(v.bit_length() +7 ) // 8)
        match hl:
            case 0:
                return 0
            case 1:
                return 1
            case 2:
                return 2
            case 3 | 4:
                return 4
            case 5 | 6:
                return 6
            case _:
                raise ValueError(f"hex length for value {v} is {hl} but must be 0,1,2,4, or 6")

    """ convert an integer value to a 24 bit maximum hex string in little endian order"""
    def _int_hstr(self,d,digits=0):
        lval = int(max(self._hex_len(d),digits)/2)
        return d.to_bytes(lval,byteorder='little').hex().upper()

    """ convert string of hexadecimal in little endian to an integer value"""
    def _hstr_int(self,hstr):
        lodd = (len(hstr) % 2 == 1)
        if lodd:
            hb = bytes.fromhex(hstr.zfill(len(hstr)+1))
        else:
            hb = bytes.fromhex(hstr)
        return int.from_bytes(hb,byteorder='little')
    
    """ strip un-parsed characters from the command response. """
    def _strip(self,s,hval_only=False):
        s2 = s.replace("#","")
        s2 = s2.replace("\r","")
        s2 = s2.replace(":","")
        if hval_only:
            s2 = s2.replace("=","")
            s2 = s2.replace("!","")
        return s2
    
    def _match_axis(self,axis):
        match axis:
            case Axis.AZ | Axis.AZ.value | '1':
                rval = '1'
            case Axis.ALT | Axis.ALT.value | '2':
                rval = '2'
            case Axis.BOTH | Axis.BOTH.value | '3':
                rval = '3'
            case _:
                raise ValueError(f"AzGti_Protocol - unexpected axis {axis} in _match_axis private method.")

        return rval
    
    """ converts motor counts for a given axis into degrees of motion. """
    def _counts2deg(self,counts,axis):
        match axis:
            case Axis.AZ | Axis.AZ.value:
                degval = counts * 360.0 / self.az_counts_per_rev
            case Axis.ALT | Axis.ALT.value:
                degval = counts * 360.0 / self.alt_counts_per_rev
            case _:
                raise ValueError(f"AzGti_Protocol - unexpected axis {axis} in _counts2deg private method.")

        return degval
    
    """ converts motor counts for a given axis into degrees of motion. """
    def _deg2counts(self,deg,axis):
        match axis:
            case Axis.AZ | Axis.AZ.value:
                cval = int((deg * self.az_counts_per_rev)/360.0)
            case Axis.ALT | Axis.ALT.value:
                cval = int((deg * self.alt_counts_per_rev)/360.0)
            case _:
                raise ValueError(f"AzGti_Protocol - unexpected axis {axis} in _deg2counts private method.")

        return cval

    """ Setup the variables for motion scaling by reading them from the mount on the first call. """
    def _setup_motion_scaling(self):
        if not self._motion_scaling_setup:
            self.timer_interrupt_freq = self.get_timer_interrupt_freq()
            self.az_counts_per_rev = self.get_counts_per_revolution(Axis.AZ.value)
            self.alt_counts_per_rev = self.get_counts_per_revolution(Axis.ALT.value)
            self.step_period = self.get_step_period(Axis.AZ.value)
            self.high_speed_ratio = self.get_high_speed_ratio(Axis.AZ.value)
            self._motion_scaling_setup = True
        
        if self.verbose:
            print("motion scaling:")
            print(f"tif: {self.timer_interrupt_freq}")
            print(f"az_cpr: {self.az_counts_per_rev}")
            print(f"alt_cpr: {self.alt_counts_per_rev}")
            print(f"step_p: {self.step_period}")
            print(f"hsr: {self.high_speed_ratio}")

    def get_motion_scaling(self):
        encoder_info = {
            'timer_interrupt_freq'  : self.timer_interrupt_freq,
            'az_counts_per_rev'     : self.az_counts_per_rev,
            'alt_counts_per_rev'    : self.alt_counts_per_rev,
            'step_period'           : self.step_period,
            'high_speed_ratio'      : self.high_speed_ratio,
            'deg_to_counts'         : self.az_counts_per_rev/360.0
        }
        
        return encoder_info

    """ command F : Initialization Done"""
    def check_init(self,axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":F{ax}\r")
        match val:
            case '=\r':
                return (True, 0)
            case _:
                ec = int(val[1])
                return (False,ec)
   
    """ Decode following synscan C# example, likely not right... """
    def decode_version(self,val):
        tmpver = self._hstr_int(self._strip(val,True))
        mcv = ((tmpver & 0xFF) << 16) | ((tmpver & 0xFF00)) | ((tmpver & 0xFF0000) >> 16)
        return mcv

    def get_version(self):
        val = self.ifx.cmd(f":e1\r")
        ver = self.decode_version(val)
        return ver
    
    """ Return the position of a given axis in counts with the mount offset removed. """
    def get_axis_position_counts(self,axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":j{ax}\r") 
        cpos = self._hstr_int(self._strip(val,True)) - 0x800000
        return cpos
    
    def get_axis_position_deg(self,axis):
        return self._counts2deg(self.get_axis_position_counts(axis),axis)
    
    def get_position(self):
        az = self.get_axis_position_deg(Axis.AZ)
        alt = self.get_axis_position_deg(Axis.ALT)
        return {'timestamp':datetime.now(UTC).isoformat().replace("+00:00", "Z"),'position_az':az,'position_alt':alt}
    
    """ sets the motor controller period between steps for the given axis """    
    def set_step_period(self, axis, period):
        ax = self._match_axis(axis)
        hper = self._int_hstr(period,6)
        val = self.ifx.cmd(f":I{ax}{hper}\r")
        rval = self._strip(val)

        if rval[0] == '=':
            return True
        elif rval[0] == '!':
            if self.verbose:
                print(f"AzGti_Protocol - set_step_period - error is {rval[1:]}")
            return False
        else:
            raise ValueError(f"AzGti_Protocol - unexpected set_step_period return {val}")
        
    def set_speed(self, axis, deg_per_sec):
        cval = self._deg2counts(abs(deg_per_sec),axis)
        print(f"cval:{cval}")
        if abs(cval) < 0:
            crate = int(self.timer_interrupt_freq)
        elif abs(cval) == 0:
            crate = 0
        else:
            crate = int(self.timer_interrupt_freq / cval)

        return self.set_step_period(axis,crate)
        

    """ This sets the mount position to a specific axis count position / degrees.
            NOTE : It appears this command is invalid for Skywatcher AzGTi Az El mount
    """
    def set_axis_position_counts(self, axis, cnt):
        ax = self._match_axis(axis)
        hcnt = self._int_hstr(cnt + 0x800000,6)
        val = self.ifx.cmd(f":E{ax}{hcnt}\r")
        rval = self._strip(val)
        if rval[0] == '=':
            return True
        elif rval[0] == '!':
            if self.verbose:
                print(f"AzGti_Protocol - set_position_sync_counts - error is {rval[1:]}")
            return False
        else:
            raise ValueError(f"AzGti_Protocol - unexpected set_position_sync_counts return {val}")

    """ degree based set position helper function """
    def set_axis_position_deg(self, axis, deg):
        return self.set_axis_position_counts(axis,self._deg2counts(deg,axis)) 
    
    """ set the azimuth and altitude position in degrees - helper"""
    def sync_position(self, az_pos, alt_pos):
        az_r = self.set_axis_position_deg(Axis.AZ.value,az_pos)
        alt_r = self.set_axis_position_deg(Axis.ALT.value,alt_pos)

        if az_r and alt_r:
            return True
        else:
            return False
    
    def _decode_mode(self, mode):
        #print(hex(mode))
        tracking = ((mode & StatusMask.TG_MASK.value) != 0)
        ccw = ((mode & StatusMask.CCW_MASK.value) != 0)
        speed = ((mode & StatusMask.SPD_MASK.value) != 0)
        running = ((mode & StatusMask.RUN_MASK.value) != 0)
        blocked = ((mode & StatusMask.BLK_MASK.value) != 0)
        init = ((mode & StatusMask.INIT_MASK.value) != 0)
        level_sw = ((mode & StatusMask.LVL_MASK.value) != 0)

        return (tracking, ccw, speed, running, blocked, init, level_sw)
    
    """" Set the mode bit mask as bit fields of an integer """
    def _encode_mode(self, track, speed, ccw):
        val = 0x00
        print("tracking ", track, "speed", speed, "ccw", ccw)
        if track:
            val = (val | ModeMask.TG_MASK.value)
            sbit = speed
            if sbit:
                val = (val | ModeMask.SPD_MASK.value)
        else:
            sbit = not speed
            if sbit:
                val = (val | ModeMask.SPD_MASK.value)

        if ccw:
            val = (val | ModeMask.CCW_MASK.value)

        #if coarse:
        #    val = (val | ModeMask.COARSE_MASK.value)

        return val

    def get_motion_mode(self, axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":f{ax}\r")
        hval = self._hstr_int(self._strip(val,True))
        mv = self._decode_mode(hval)
        return {'timestamp':datetime.now(UTC).isoformat().replace("+00:00", "Z"), 'axis':axis,'tracking':mv[0],'ccw':mv[1],'high_speed':mv[2],'moving':mv[3],'blocked':mv[4],'init':mv[5],'level_sw':mv[6]}

    def set_motion_mode(self, axis, tracking, speed, ccw):
        ax = self._match_axis(axis)
        mode = self._encode_mode(tracking, speed, ccw)
        hmode = self._int_hstr(mode,2)
        val = self.ifx.cmd(f":G{ax}{hmode}\r")

        rval = self._strip(val)
        if rval[0] == '=':
            return True
        elif rval[0] == '!':
            if self.verbose:
                print(f"AzGti_Protocol - set_motion_mode - error is {rval[1:]}")
            return False
        else:
            raise ValueError(f"AzGti_Protocol - unexpected set_motion_mode return {val}")


    """ Set a goto target for the mount with azimuth and elevation targets in degrees"""
    def set_goto_target_counts(self, axis, counts):
        ax = self._match_axis(axis)
        # first stop the mount
        self.stop_motion(axis)

        # now set the target axis position in counts with needed offset
        hcnt = self._int_hstr(counts + 0x800000,6)

        val = self.ifx.cmd(f":S{ax}{hcnt}\r")

        rval = self._strip(val)
        if rval[0] == '=':
            return True
        elif rval[0] == '!':
            if self.verbose:
                print(f"AzGti_Protocol - set_goto_target_counts - error is {rval[1:]}")
            return False
        else:
            raise ValueError(f"AzGti_Protocol - unexpected set_goto_target_counts return {val}")


    """ Set a goto target for the mount for an axis in degrees"""
    def set_goto_target_deg(self, axis, deg_target):
        return self.set_goto_target_counts(axis, self._deg2counts(deg_target,axis))
    
    def start_motion(self, axis):
        match axis:
            case Axis.AZ | Axis.AZ.value | '1':
                val = self.ifx.cmd(f":J1\r")
            case Axis.ALT | Axis.ALT.value | '2':
                val = self.ifx.cmd(f":J2\r")
            case Axis.BOTH | Axis.BOTH.value | '3':
                val = self.ifx.cmd(f":J1\r")
                val = self.ifx.cmd(f":J2\r")
            case _:
                raise ValueError(f"AzGti_Protocol - unexpected start_motion axis {axis}")
        
        if self._strip(val) == '=':
            return True
        else:
            raise ValueError(f"AzGti_Protocol - unexpected start_motion return {val}")
        
    """ Move the selected axis at a given rate with positive CW and negative CCW. Take care to monitor position and stop! """
    def track_rate(self, axis, rate):
        state = self.get_motion_mode(axis)

        CW = not state['CCW']

        if state['running']:
            if not state['tracking'] or (CW and (rate < 0)) or (not CW and (rate > 0)):
                self.stop_motion(axis)
                self.set_motion_mode(axis,True,True,(rate < 0))
                self.set_speed(axis,rate)
            else:
                self.set_speed(axis,rate)
        else:
            self.set_motion_mode(axis,True,True,(rate < 0))
            self.set_speed(axis,rate)

        return self.start_motion(axis)

        
    def goto_position_az(self, az_tgt, az_rate = 1.0):
        # get position
        az_cur = self.get_axis_position_deg(Axis.AZ)

        # compute directions
        CCW1 = (az_tgt < az_cur)

        # set the goto target
        az_r = self.set_goto_target_deg(Axis.AZ, az_tgt)

        # setup the motion mode to goto, CW, speed
        #   axis, tracking, speed, down, ccw
        azm_r = self.set_motion_mode(Axis.AZ, False, True, CCW1)

        # setup the speed, defaults
        azr_r = self.set_speed(Axis.AZ,az_rate)

        # start motion
        azs_r = self.start_motion(Axis.AZ)

        if az_r and azm_r and azs_r:
            return True
        else:
            return False               

    def goto_position_alt(self, alt_tgt, alt_rate = 1.0):
        # get position
        alt_cur = self.get_axis_position_deg(Axis.ALT)

        # compute directions
        CCW2 = (alt_tgt < alt_cur)

        # set the goto target
        alt_r = self.set_goto_target_deg(Axis.ALT, alt_tgt)

        # setup the motion mode to goto, CW, speed
        #   axis, tracking, speed, down, ccw
        altm_r = self.set_motion_mode(Axis.ALT, False, True, CCW2)

        # setup the speed, defaults
        altr_r = self.set_speed(Axis.ALT,alt_rate)

        # start motion
        alts_r = self.start_motion(Axis.ALT)

        if alt_r and altm_r and alts_r:
            return True
        else:
            return False               


    """ goto azimuth and altitude position in degrees, rates in dps - helper"""      
    def goto_position(self, az_tgt, alt_tgt, az_rate = 1.0, alt_rate = 1.0):

        # get position
        az_cur = self.get_axis_position_deg(Axis.AZ)
        alt_cur = self.get_axis_position_deg(Axis.ALT)

        # compute directions
        CCW1 = (az_tgt < az_cur)
        CCW2 = (alt_tgt < alt_cur)

        # set the goto target
        az_r = self.set_goto_target_deg(Axis.AZ, az_tgt)
        alt_r = self.set_goto_target_deg(Axis.ALT, alt_tgt)

        # setup the motion mode to goto, CW, speed
        #   axis, tracking, speed, down, ccw
        azm_r = self.set_motion_mode(Axis.AZ, False, True, CCW1)
        altm_r = self.set_motion_mode(Axis.ALT, False, True, CCW2)

        # setup the speed, defaults
        azr_r = self.set_speed(Axis.AZ,az_rate)
        altr_r = self.set_speed(Axis.ALT,alt_rate)

        # start motion
        azs_r = self.start_motion(Axis.AZ)
        alts_r = self.start_motion(Axis.ALT)

        if az_r and alt_r and azm_r and altm_r and azs_r and alts_r:
            return True
        else:
            return False       

    def stop_motion(self, axis):
        match axis:
            case Axis.AZ | Axis.AZ.value | '1':
                val = self.ifx.cmd(f":K1\r")
            case Axis.ALT | Axis.ALT.value | '2':
                val = self.ifx.cmd(f":K2\r")
            case Axis.BOTH | Axis.BOTH.value | '3':
                val = self.ifx.cmd(f":K1\r")
                val = self.ifx.cmd(f":K2\r")
            case _:
                raise ValueError(f"AzGti_Protocol - unexpected stop_motion axis {axis}")
        
        if self._strip(val) == '=':
            return True
        else:
            raise ValueError(f"AzGti_Protocol - unexpected stop_motion return {val}")
            
    def force_stop_motion(self):
        val1 = self.ifx.cmd(f":L1\r")
        val2 = self.ifx.cmd(f":L2\r")

        if self._strip(val1) == '=' and self._strip(val2) == '=':
            return True
        else:
            raise ValueError(f"AzGti_Protocol - unexpected force_stop_motion return {val1},{val2}")

    """ Set the state of the auxillary switch"""
    # def set_aux_switch(self, state):
    #     val = self.ifx.cmd(f":O{state}\r")
    #     if self._strip(val) == '=':
    #         return True
    #     else:
    #         raise ValueError(f"AzGti_Protocol - unable to set aux switch state to {state}")

    """ Return the counts per revolution for the provided axis, only 1 / Az or 2 / Alt allowed. """
    def get_counts_per_revolution(self,axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":a{ax}\r")
        hval = self._hstr_int(self._strip(val,True))
        return hval

    """ Return the underlying motor controller timer interrupt frequency. This drives the motor update loop. """
    def get_timer_interrupt_freq(self):
        val = self.ifx.cmd(f":b1\r")
        hval = self._hstr_int(self._strip(val,True))
        return hval

    " return the target counts for the axis, removing the offset"
    def get_goto_target_counts(self, axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":h{ax}\r")
        hval = self._hstr_int(self._strip(val,True))
        return (hval - 0x800000)

    """ return the target goto point for the axis in degrees """
    def get_goto_target_deg(self, axis):
        return self._counts2deg(self.get_goto_target_counts(axis),axis)

    """ return the period between motor steps """
    def get_step_period(self,axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":i{ax}\r")
        sp = self._hstr_int(self._strip(val,True))
        return sp

    """ return the high speed gear ratio """
    def get_high_speed_ratio(self,axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":g{ax}\r")
        hsr = self._hstr_int(self._strip(val,True))
        return hsr

    """ return the period the mount has been tracking? """
    def get_tracking_period(self):
        val = self.ifx.cmd(f":D1\r")
        tp = self._hstr_int(self._strip(val,True))
        return tp

    """ telescope axis position value in counts"""
    def get_tele_axis_position_counts(self, axis):
        ax = self._match_axis(axis)
        val = self.ifx.cmd(f":d{ax}\r")
        if val[0] == '=':
            taxp = self._hstr_int(self._strip(val,True))
            return (taxp - 0x800000)
        else:
            ename = self._error_name(val)
            raise ValueError(f"AzGti_Protocol - get_tele_axis_position_counts error {ename}")


    """ telescope axis position value in counts"""
    def get_tele_axis_position_deg(self, axis):
        return self._counts2deg(self.get_tele_axis_position_counts(axis),axis)




"""
    Provides a serial interface to the AzGTi wired telescope mount via their 
    slightly customized synscan 3.3 protocol. Handles the associated
    serial port interface using a locked async framework. The protocol
    is handled by a separate object. 

    The network and wireless interface is not yet supported. 

"""
class AzGTi_Interface:
    def __init__(self, device, baud=9600, timeout=0.05, verbose=False, logging=None):

        # create lock    
        self._state = 'startup'
        self.verbose = verbose
        self.logging = logging

        self.serial = None
        self.device = device
        self.baud = baud
        self.timeout = timeout

        # create serial interface
        try:
            self.serial = serial.Serial(device, baudrate=baud, timeout = timeout)
            # if self._check_baud(baud):
            #     # try for 115200, might be redundant if already at that rate externally
            #     if self._check_baud(115200):
            #         self._baud = 115200
            #     else:
            #         # fallback
            #         self._check_baud(baud)
            # else:
            #     # problem at the provided default, try 9600 baud
            #     if not self._check_baud(9600):
            #         raise serial.SerialException
            #     else:
            #         self._baud = 9600

            self._state = 'connected'

            if self.logging is not None:
                self.logging.info(f"AzGTi Interface - connected to {self.device} at {self.baud}")

        except (serial.SerialException, EOFError) as e:
                self._state = 'disconnected'
                if self.logging is not None:
                    self.logging.error(f"AzGTi Interface - problem connecting to {self.device} at {self.baud}")

        if self.verbose:
            print(f"serial device {self.device} interface {self._state} at {self.baud}")

    def _check_baud(self, baud):
        # select baud to test, use native mount hex values and word order
        match baud:
            case 9600:
                self.serial.baudrate = 9600
                baud_cmd = b":W10DC003\r"
            
            case 115200:
                self.serial.baudrate = 115200
                baud_cmd = b":W10D8004\r"

        # set the baud rate
        r = self.cmd(baud_cmd)
        if not (r == '=\r'):
            if self.logging is not None:
                self.logging.error(f"Problem setting baud to {self.serial.baudrate} for {self.device}")
            if self.verbose:
                print(f"Problem setting baud to {self.serial.baudrate} for device {self.device}")

            self.serial.baudrate = self.baud

            return False

        # double check for initialization response at the set baud rate
        r = self.cmd(b":F1\r")
        if r == '=\r':
            if self.logging is not None:
                self.logging.info(f"Baud set to {self.serial.baudrate} for {self.device}")
            if self.verbose:
                print(f"Baud set to {self.serial.baudrate} for device {self.device}")

            return True
        else:
            return False    

    def close(self):
        if self.verbose:
            print("serial close attempt")
        
        if self.serial is not None:
            self.serial.close()
            self.serial = None
            self._state = 'disconnected'


    def reconnect(self):
        if self.verbose:
            print("serial reconnect attempt")

        self.close()

        if self.verbose:
            print("reconnected")
        
        try:
            self.serial = serial.Serial(self.device, baudrate=self.baud, timeout = 0.05)
            self._state = 'connected'
        except (serial.SerialException, EOFError) as e:
            self._state = 'disconnected'
                
    def send(self, data):
        if not self._state == 'connected':
            self.reconnect()
            if self._state == 'disconnected':
                raise serial.SerialException
            
        self.serial.write(data)

        if self.verbose:
            print(f"sw: {data}")
              
    def recv(self):
        if not self._state == 'connected':
            self._reconnect()
            if self._state == 'disconnected':
                raise serial.SerialException

        data = self.serial.readline()

        if self.verbose:
            print(f"sr: {data}")

        return data.decode("utf-8")
            
    def cmd(self, cmd_str):
        # may not need the flush
        self.serial.reset_input_buffer()
        self.send(cmd_str.encode())
        response = self.recv()

        if self.verbose:
            # most commands only have \r which overwrites without a linefeed...
            print(cmd_str)
            print("->", response)

        return response

        
        
