"""
    astra-goto.py

    Command line routine to connect to antenna controller and goto the provided pointing position.

    Currently defaults to a direct serial connection and (0,0) Azimuth / Elevation. Command line
    for other positions.

"""
import argparse
import os
import sys
import traceback
import azgti



def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "astra-goto"
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
        default="/dev/ttyUSB0",
        help=(
            "The serial device associated with the antenna control interface."
        ),
    )

    parser.add_argument(
        "-az",
        "--azimuth",
        dest="az",
        default=0.0,
        type=float,
        help="The antenna azimuth for goto.",
    )

    parser.add_argument(
        "-el",
        "--elevation",
        dest="el",
        default=0.0,
        type=float,
        help="The antenna elevation for goto.",
    )

    parser.add_argument(
        "-azr",
        "--azimuth-rate",
        dest="azr",
        default=1.0,
        type=float,
        help="Set the azimuth rate in degrees per second. Maximum of 5 deg / sec",
    )

    parser.add_argument(
        "-erl",
        "--elevation-rate",
        dest="elr",
        default=1.0,
        type=float,
        help="Set the elevation rate in degrees per second. Maximum of 5 deg / sec",
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


    # connect
    try:
        # This is an initial test. We will ultimately do this via the 
        # motion control service which will also provide an API to isolate
        # different antenna controllers. 
        ifx = azgti.AzGTi_Interface(options.dev,verbose=options.verbose)
        mount = azgti.AzGTi_Protocol(ifx,verbose=options.verbose)
        mount._setup_motion_scaling()
    except Exception as e:
        print("Problem connecting to the motion controller via the USB to serial connection. ")
        traceback.print_exc()
        sys.exit()

    # pull az and el
    az = options.az
    el = options.el

    # check for target position for basic sanity
    if az < -359.9 or az > 359.9:
        print("Azimuth outside valid range, default to 0.0")
        az = 0.0
    
    if el < -5.0:
        print("Elevation is below -5.0 deg, level unit and resync.")
        print("default to elevation 0.0")
        el = 0.0

    if el > 180.0:
        print("Antenna cannot point greater than 180.0 elevation (over top), default to elevation 0.0")
        el = 0.0

    # check motion rate for basic sanity

    azr = options.azr
    elr = options.elr

    if azr < 0.0 or azr > 5.0:
        print("Azimuth rate must be between 0.0 and 5.0 deg / sec.")
        print("Defaulting to 1.0 deg / sec")
        azr = 1.0

    if elr < 0.0 or elr > 5.0:
        print("Altitude rate must be between 0.0 and 5.0 deg / sec.")
        print("Defaulting to 1.0 deg / sec")
        elr = 1.0

    # set axis rates
    mount.set_speed(azgti.Axis.AZ, azr)
    mount.set_speed(azgti.Axis.ALT, elr)

    # goto position
    mount.goto_position(az,el)

    if options.verbose:
        (az,el) = mount.get_position()
        print(f"move to {az:05.2f}AZ {el:05.2f}ALT")