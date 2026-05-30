"""
    astra-position.py

    Command line routine to connect to antenna controller and print the position.

    Currently defaults to a direct serial connection.

"""
import argparse
import os
import sys
import time
import traceback
import synscan


def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "astra-position"
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
        "-c",
        "--count",
        dest="count",
        default=10,
        type=int,
        help="Number of times to print out the position.",
    )

    parser.add_argument(
        "-p",
        "--period",
        dest="period",
        default=1.0,
        type=float,
        help="Delay period between updates in floating point seconds. Default is 1.0 seconds.",
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
        mc = synscan.motors(serial_dev=options.dev)
    except Exception as e:
        print("Problem connecting to the motion controller via the USB to serial connection. ")
        print (f"No serial connection on {options.dev}")
        traceback.print_exc()
        sys.exit()

    n = 0

    while n < options.count:

        azp = mc.axis_get_pos(1)
        elp = mc.axis_get_pos(2)

        print(f"{azp:.2f} deg Az / {elp:.2f} El deg")

        time.sleep(options.period)

        n += 1
