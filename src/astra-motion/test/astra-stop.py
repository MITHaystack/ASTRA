"""
    astra-stop.py

    Command line routine to connect to antenna controller and stop the mount from moving.

    Currently defaults to a direct serial connection. 

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

    title = "astra-stop"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Stop motion of the ASTRA telescope mount."
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
        "-f",
        "--force",
        action="store_true",
        dest="force",
        default=False,
        help="Use force stop instead of axis stop command.",
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


    # connect to serial, add mqtt later
    try:
        # This is an initial test. We will ultimately do this via the 
        # motion control service which will also provide an API to isolate
        # different antenna controllers. 
        ifx = azgti.AzGTi_Interface(options.dev,verbose=options.verbose)
        mount = azgti.AzGTi_Protocol(ifx,verbose=options.verbose)
        mount._setup_motion_scaling()
    except Exception as e:
        print("Problem connecting to the motion controller via the USB to serial connection. ")
        print (f"No serial connection on {options.dev}")
        traceback.print_exc()
        sys.exit()

    # pull az and el
    az = options.az 
    el = options.el

    if az < -359.9 or az > 359.9:
        print("Azimuth outside valid range, default to 0.0")
        az = 0.0
    
    if el < -5.0:
        print("Elevation is below zero, level unit and resync.")
        print("default to elevation 0.0")
        el = 0.0

    if el > 180.0:
        print("Antenna cannot point greater than 180.0 elevation (over top), default to elevation 0.0")
        el = 0.0

    # synchronize position
    if options.force:
        mount.force_stop_motion()
    else:
        mount.stop_motion(azgti.Axis.BOTH)

    if options.verbose:
        (az,el) = mount.get_position()
        print(f"stop position {az:05.2f}AZ {el:05.2f}ALT")
