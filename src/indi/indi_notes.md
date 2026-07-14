Notes for the ASTRA Indi Interface



- Mount property dump

List of devices
   > AZ-GTi Alt-Az Wired
List of Device Properties
-- AZ-GTi Alt-Az Wired
   > CONNECTION INDI_SWITCH
       CONNECT(Connect) = On
       DISCONNECT(Disconnect) = Off
   > DRIVER_INFO INDI_TEXT
       DRIVER_NAME(Name) = Skywatcher Alt-Az
       DRIVER_EXEC(Exec) = indi_skywatcherAltAzMount
       DRIVER_VERSION(Version) = 1.8
       DRIVER_INTERFACE(Interface) = 5
   > POLLING_PERIOD INDI_NUMBER
       PERIOD_MS(Period (ms)) = 1000.0
   > DEBUG INDI_SWITCH
       ENABLE(Enable) = Off
       DISABLE(Disable) = On
   > CONFIG_PROCESS INDI_SWITCH
       CONFIG_LOAD(Load) = Off
       CONFIG_SAVE(Save) = Off
       CONFIG_DEFAULT(Default) = Off
       CONFIG_PURGE(Purge) = Off
   > ALIGNMENT_POINT_MANDATORY_NUMBERS INDI_NUMBER
       ALIGNMENT_POINT_ENTRY_OBSERVATION_JULIAN_DATE(Observation Julian date) = 0.0
       ALIGNMENT_POINT_ENTRY_RA(Right Ascension (hh:mm:ss)) = 0.0
       ALIGNMENT_POINT_ENTRY_DEC(Declination (dd:mm:ss)) = 0.0
       ALIGNMENT_POINT_ENTRY_VECTOR_X(Telescope direction vector x) = 0.0
       ALIGNMENT_POINT_ENTRY_VECTOR_Y(Telescope direction vector y) = 0.0
       ALIGNMENT_POINT_ENTRY_VECTOR_Z(Telescope direction vector z) = 0.0
   > ALIGNMENT_POINT_OPTIONAL_BINARY_BLOB INDI_BLOB
       ALIGNMENT_POINT_ENTRY_PRIVATE(Private binary data) = <blob 0 bytes>
   > ALIGNMENT_POINTSET_SIZE INDI_NUMBER
       ALIGNMENT_POINTSET_SIZE(Size) = 0.0
   > ALIGNMENT_POINTSET_CURRENT_ENTRY INDI_NUMBER
       ALIGNMENT_POINTSET_CURRENT_ENTRY(Pointer) = 0.0
   > ALIGNMENT_POINTSET_ACTION INDI_SWITCH
       APPEND(Add entries at end of set) = On
       INSERT(Insert entries at current index) = Off
       EDIT(Overwrite entry at current index) = Off
       DELETE(Delete entry at current index) = Off
       CLEAR(Delete all the entries in the set) = Off
       READ(Read the entry at the current pointer) = Off
       READ INCREMENT(Increment the pointer before reading the entry) = Off
       LOAD DATABASE(Load the alignment database from local storage) = Off
       SAVE DATABASE(Save the alignment database to local storage) = Off
   > ALIGNMENT_POINTSET_COMMIT INDI_SWITCH
       ALIGNMENT_POINTSET_COMMIT(OK) = Off
   > ALIGNMENT_SUBSYSTEM_MATH_PLUGINS INDI_SWITCH
       INBUILT_MATH_PLUGIN(Inbuilt Math Plugin) = Off
       Nearest Math Plugin(Nearest Math Plugin) = On
       SVD Math Plugin(SVD Math Plugin) = Off
   > ALIGNMENT_SUBSYSTEM_MATH_PLUGIN_INITIALISE INDI_SWITCH
       ALIGNMENT_SUBSYSTEM_MATH_PLUGIN_INITIALISE(OK) = Off
   > ALIGNMENT_SUBSYSTEM_ACTIVE INDI_SWITCH
       ALIGNMENT SUBSYSTEM ACTIVE(Alignment Subsystem Active) = On
   > CONNECTION_MODE INDI_SWITCH
       CONNECTION_SERIAL(Serial) = On
       CONNECTION_TCP(Network) = Off
   > SYSTEM_PORTS INDI_SWITCH
       Prolific_Technology_Inc._USB(Prolific_Technology_Inc._USB) = Off
       Analog_Devices_Inc._PlutoSDR__ADALM(Analog_Devices_Inc._PlutoSDR__ADALM) = Off
       Adafruit_Feather_RP2040_DF6548405F490B28(Adafruit_Feather_RP2040_DF6548405F490B28) = Off
       Adafruit_Feather_RP2040_DF6548405F490B28(Adafruit_Feather_RP2040_DF6548405F490B28) = Off
   > DEVICE_PORT INDI_TEXT
       PORT(Port) = /dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller_AZBMb135B02-if00-port0
   > DEVICE_BAUD_RATE INDI_SWITCH
       9600(9600) = On
       19200(19200) = Off
       38400(38400) = Off
       57600(57600) = Off
       115200(115200) = Off
       230400(230400) = Off
   > DEVICE_AUTO_SEARCH INDI_SWITCH
       INDI_ENABLED(Enabled) = Off
       INDI_DISABLED(Disabled) = On
   > DEVICE_PORT_SCAN INDI_SWITCH
       Scan Ports(Scan Ports) = Off
   > ACTIVE_DEVICES INDI_TEXT
       ACTIVE_GPS(GPS) = GPS Simulator
       ACTIVE_DOME(DOME) = Dome Simulator
   > DOME_POLICY INDI_SWITCH
       DOME_IGNORED(Dome ignored) = On
       DOME_LOCKS(Dome locks) = Off
   > ON_COORD_SET INDI_SWITCH
       TRACK(Track) = On
       SLEW(Slew) = Off
       SYNC(Sync) = Off
   > EQUATORIAL_EOD_COORD INDI_NUMBER
       RA(RA (hh:mm:ss)) = 20.313068291815117
       DEC(DEC (dd:mm:ss)) = 47.660694444444445
   > TELESCOPE_ABORT_MOTION INDI_SWITCH
       ABORT(Abort) = Off
   > TELESCOPE_TRACK_MODE INDI_SWITCH
       TRACK_SIDEREAL(Sidereal) = On
       TRACK_SOLAR(Solar) = Off
       TRACK_LUNAR(Lunar) = Off
   > TELESCOPE_TRACK_STATE INDI_SWITCH
       TRACK_ON(On) = Off
       TRACK_OFF(Off) = On
   > TELESCOPE_MOTION_NS INDI_SWITCH
       MOTION_NORTH(North) = Off
       MOTION_SOUTH(South) = Off
   > TELESCOPE_MOTION_WE INDI_SWITCH
       MOTION_WEST(West) = Off
       MOTION_EAST(East) = Off
   > TELESCOPE_REVERSE_MOTION INDI_SWITCH
       REVERSE_NS(North/South) = Off
       REVERSE_WE(West/East) = Off
   > TELESCOPE_SLEW_RATE INDI_SWITCH
       1x(1.000000x) = Off
       2x(2.000000x) = Off
       3x(4.000000x) = Off
       4x(8.000000x) = Off
       5x(16.000000x) = On
       6x(32.000000x) = Off
       7x(64.000000x) = Off
       8x(128.000000x) = Off
       SLEW_MAX(600.000000x) = Off
   > TARGET_EOD_COORD INDI_NUMBER
       RA(RA (hh:mm:ss)) = 0.0
       DEC(DEC (dd:mm:ss)) = 0.0
   > TELESCOPE_MOUNT_TYPE INDI_SWITCH
       ALTAZ(ALTAZ) = On
       EQ_FORK(Fork (Eq)) = Off
       EQ_GEM(GEM) = Off
   > TIME_UTC INDI_TEXT
       UTC(UTC Time) = 2026-06-21T19:01:12
       OFFSET(UTC Offset) = -4
   > GEOGRAPHIC_COORD INDI_NUMBER
       LAT(Lat (dd:mm:ss.s)) = 42.35666666666667
       LONG(Lon (dd:mm:ss.s)) = 288.9433333333333
       ELEV(Elevation (m)) = 5.53000021
   > TELESCOPE_PARK INDI_SWITCH
       PARK(Park(ed)) = Off
       UNPARK(UnPark(ed)) = On
   > TELESCOPE_PARK_POSITION INDI_NUMBER
       PARK_AZ(AZ Encoder) = 7933181.0
       PARK_ALT(ALT Encoder) = 8562748.0
   > TELESCOPE_PARK_OPTION INDI_SWITCH
       PARK_CURRENT(Current) = Off
       PARK_DEFAULT(Default) = Off
       PARK_WRITE_DATA(Write Data) = Off
       PARK_PURGE_DATA(Purge Data) = Off
   > USEJOYSTICK INDI_SWITCH
       ENABLE(Enable) = Off
       DISABLE(Disable) = On
   > SNOOP_JOYSTICK INDI_TEXT
       SNOOP_JOYSTICK_DEVICE(Device) = Joystick
   > BASIC_MOUNT_INFO INDI_TEXT
       MOTOR_CONTROL_FIRMWARE_VERSION(Motor control firmware version) = 210117
       MOUNT_CODE(Mount code) = 197
       MOUNT_NAME(Mount name) = Unknown
       IS_DC_MOTOR(Is DC motor) = 0
   > AXIS_ONE_INFO INDI_NUMBER
       MICROSTEPS_PER_REVOLUTION(Microsteps per revolution) = 2073600.0
       STEPPER_CLOCK_FREQUENCY(Stepper clock frequency) = 16000000.0
       HIGH_SPEED_RATIO(High speed ratio) = 1.0
       MICROSTEPS_PER_WORM_REVOLUTION(Microsteps per worm revolution) = 14400.0
   > AXIS_ONE_STATE INDI_SWITCH
       FULL_STOP(FULL_STOP) = On
       SLEWING(SLEWING) = Off
       SLEWING_TO(SLEWING_TO) = Off
       SLEWING_FORWARD(SLEWING_FORWARD) = On
       HIGH_SPEED(HIGH_SPEED) = Off
       NOT_INITIALISED(NOT_INITIALISED) = Off
   > AXIS_TWO_INFO INDI_NUMBER
       MICROSTEPS_PER_REVOLUTION(Microsteps per revolution) = 2073600.0
       STEPPER_CLOCK_FREQUENCY(Step timer frequency) = 16000000.0
       HIGH_SPEED_RATIO(High speed ratio) = 1.0
       MICROSTEPS_PER_WORM_REVOLUTION(Microsteps per worm revolution) = 14400.0
   > AXIS_TWO_STATE INDI_SWITCH
       FULL_STOP(FULL_STOP) = On
       SLEWING(SLEWING) = Off
       SLEWING_TO(SLEWING_TO) = Off
       SLEWING_FORWARD(SLEWING_FORWARD) = On
       HIGH_SPEED(HIGH_SPEED) = Off
       NOT_INITIALISED(NOT_INITIALISED) = Off
   > AXIS1_ENCODER_VALUES INDI_NUMBER
       RAW_MICROSTEPS(Raw Microsteps) = 8388608.0
       MICROSTEPS_PER_ARCSEC(Microsteps/arcsecond) = 1.6
       OFFSET_FROM_INITIAL(Offset from initial) = 0.0
       DEGREES_FROM_INITIAL(Degrees from initial) = 0.0
   > AXIS2_ENCODER_VALUES INDI_NUMBER
       RAW_MICROSTEPS(Raw Microsteps) = 8388608.0
       MICROSTEPS_PER_ARCSEC(Microsteps/arcsecond) = 1.6
       OFFSET_FROM_INITIAL(Offset from initial) = 0.0
       DEGREES_FROM_INITIAL(Degrees from initial) = 0.0
   > TELESCOPE_MOTION_SLEWMODE INDI_SWITCH
       SLEW_SILENT(Silent) = Off
       SLEW_NORMAL(Normal) = On
   > TELESCOPE_MOTION_SOFTPECMODE INDI_SWITCH
       SOFTPEC_ENABLED(Enable for tracking) = Off
       SOFTPEC_DISABLED(Disabled) = On
   > SOFTPEC INDI_NUMBER
       SOFTPEC_VALUE(degree/minute (Alt)) = 0.009
   > GUIDE_RATES INDI_NUMBER
       GUIDERA_RATE(arcsec/seconds (RA)) = 120.0
       GUIDEDEC_RATE(arcsec/seconds (Dec)) = 120.0
   > AXIS1_PID INDI_NUMBER
       Propotional(Propotional) = 0.1
       Derivative(Derivative) = 0.05
       Integral(Integral) = 0.05
   > AXIS2_PID INDI_NUMBER
       Propotional(Propotional) = 0.2
       Derivative(Derivative) = 0.1
       Integral(Integral) = 0.1
   > DEAD_ZONE INDI_NUMBER
       AXIS1(AZ (steps)) = 10.0
       AXIS2(AL (steps)) = 10.0
   > AXIS_CLOCK INDI_NUMBER
       AXIS1(AZ %) = 100.0
       AXIS2(AL %) = 100.0
   > AXIS_OFFSET INDI_NUMBER
       RAOffset(RA (deg)) = 0.0
       DEOffset(DE (deg)) = 0.0
       AZEncoder(AZ (steps)) = 0.0
       ALEncoder(AL (steps)) = -100.0
       JulianOffset(JD (s)) = 0.0
   > AXIS1TrackRate INDI_NUMBER
       TrackDirection(West/East) = 0.0
       TrackClockRate(Freq/Step (Hz/s)) = 0.0
   > AXIS2TrackRate INDI_NUMBER
       TrackDirection(North/South) = 0.0
       TrackClockRate(Freq/Stel (Hz/s)) = 0.0
   > AUX_ENCODERS INDI_SWITCH
       INDI_ENABLED(Enabled) = On
       INDI_DISABLED(Disabled) = Off
   > TELESCOPE_TIMED_GUIDE_NS INDI_NUMBER
       TIMED_GUIDE_N(North (ms)) = 0.0
       TIMED_GUIDE_S(South (ms)) = 0.0
   > TELESCOPE_TIMED_GUIDE_WE INDI_NUMBER
       TIMED_GUIDE_W(West (ms)) = 0.0
       TIMED_GUIDE_E(East (ms)) = 0.0

- CCD Property Dump

List of devices
   > QHY CCD QHY5III715C
List of Device Properties
-- QHY CCD QHY5III715C
   > CONNECTION INDI_SWITCH
       CONNECT(Connect) = Off
       DISCONNECT(Disconnect) = On
   > DRIVER_INFO INDI_TEXT
       DRIVER_NAME(Name) = QHY CCD
       DRIVER_EXEC(Exec) = indi_qhy_ccd
       DRIVER_VERSION(Version) = 2.9
       DRIVER_INTERFACE(Interface) = 2
   > POLLING_PERIOD INDI_NUMBER
       PERIOD_MS(Period (ms)) = 1000.0
   > DEBUG INDI_SWITCH
       ENABLE(Enable) = Off
       DISABLE(Disable) = On
   > SIMULATION INDI_SWITCH
       ENABLE(Enable) = Off
       DISABLE(Disable) = On
   > CONFIG_PROCESS INDI_SWITCH
       CONFIG_LOAD(Load) = Off
       CONFIG_SAVE(Save) = Off
       CONFIG_DEFAULT(Default) = Off
       CONFIG_PURGE(Purge) = Off
   > NICKNAME INDI_TEXT
       nickname(nickname) = 
   > ACTIVE_DEVICES INDI_TEXT
       ACTIVE_TELESCOPE(Telescope) = AZ-GTi Alt-Az Wired
       ACTIVE_ROTATOR(Rotator) = Rotator Simulator
       ACTIVE_FOCUSER(Focuser) = Focuser Simulator
       ACTIVE_FILTER(Filter) = 
       ACTIVE_SKYQUALITY(Sky Quality) = SQM
Disconnecting
