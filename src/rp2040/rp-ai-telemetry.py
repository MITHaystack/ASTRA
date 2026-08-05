"""
    rp-ai-telemetry.py

    Server side tool for telemetry capture via USB CDC serial interface. Expects JSON line messages from serial interface
    which correspond to the RP2040 telemetry format using dictionary objects. Informal schema for the moment...
    
    The specific device name will vary based on the platform. 

"""

import argparse
import os
import sys
import traceback
import serial
import json
import ast


def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "rp-ai-telemetry.py"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Handle telemetry from the ASTRA antenna interface unit connected via USB."
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
        default="/dev/ttyACM3",
        help=(
            "The serial device associated with the antenna interface unit."
        ),
    )

    parser.add_argument(
        "-n",
        "--number",
        dest="number",
        default=0,
        type=int,
        help="Number of times to print out the position prior to halt. Zero goes forever.",
    )

    parser.add_argument(
       "-c",
        "--cmd",
        dest="cmd",
        default=None,
        help=(
            "Send a command to the AIU over the serial port. (e.g. {'event':'command',group:'noise-diode-cmd','mode':'PULSE'})"
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


    # connect
    try:
        ai_usb = serial.Serial(options.dev, timeout = 1.0)
    except Exception as e:
        print("Problem connecting to the USB serial connection. ")
        print (f"No serial connection on {options.dev}")
        traceback.print_exc()
        sys.exit()

    n = 0
    event_cnt = 0

    # handle one shot commands

    if options.cmd is not None:
        cmd = ast.literal_eval(options.cmd)
        cmd['source']='rp-ai-telemetry'
        cmdj = json.dumps(cmd)
        ai_usb.write(cmdj.encode('utf-8'))
        ai_usb.write("\n".encode('utf-8'))

    while True:
        line = None

        if options.number > 0:
            if n > options.number:
                break
            else:
                pass

        # grab line from the serial port
        try:
            line = ai_usb.readline()
        except Exception as e:
            print(e)

        event = None
        try:
            event = json.dumps(line.decode("utf-8").rstrip())
            event_cnt += 1
        except:
            print(f"problem parsing json from line : {line}")

        if options.verbose and event is not None:
            print(f"event {event_cnt} : {event}")
        else:
            print(event)
        n += 1
