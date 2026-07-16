"""
    astra-indi-stop.py

    Command line routine to connect to antenna controller via INDI and stops the mount motion.

"""
import argparse
import os
import sys
import traceback

import time
import datetime
import PyIndi
import json

import pywmm

def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "astra-indi-stop"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Stop the motion of the ASTRA telescope mount."
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
        default="Skywatcher Alt-Az",
        help=(
            "The INDI device associated with the antenna control."
        ),
    )
    
    parser.add_argument(
        "-p",
        "--park",
        action="store_true",
        dest="park",
        default=False,
        help="Stop and then set the park position.",
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

    #connect_prop = mount.getSwitch("CONNECTION")
    #if connect_prop:
    #    # Set the CONNECTION_CONNECT switch to ON
    #    connect_prop[0].s = PyIndi.ISS_ON 
    #    connect_prop[1].s = PyIndi.ISS_OFF
    
    # Send the new state to the INDI server
    #pic.sendNewSwitch(connect_prop)

    # send stop
    abort_prop = get_switch_with_retry(mount,"TELESCOPE_ABORT_MOTION")

    if not abort_prop.isValid():
        print("Property TELESCOPE_ABORT_MOTION not valid")
        sys.exit(1)

    print(abort_prop[0].name)
    abort_prop[0].s = PyIndi.ISS_ON

    pic.sendNewSwitch(abort_prop)
    time.sleep(0.1)

    # clear stop
    abort_prop[0].s = PyIndi.ISS_OFF
    pic.sendNewSwitch(abort_prop)

    if options.park:
        print(f"set mount park position. ")
        park_prop = get_switch_with_retry(mount,"TELESCOPE_PARK")

        if not park_prop.isValid():
            print("Property TELESCOPE_PARK not valid")
            sys.exit(1)
        
        park_prop[0].s = PyIndi.ISS_ON
        park_prop[1].s = PyIndi.ISS_OFF
    else:
        # quietly clear park state
        park_prop = get_switch_with_retry(mount,"TELESCOPE_PARK")

        if not park_prop.isValid():
            print("Property TELESCOPE_PARK not valid")
            sys.exit(1)
        
        park_prop[0].s = PyIndi.ISS_OFF
        park_prop[1].s = PyIndi.ISS_ON

    pic.sendNewSwitch(park_prop)







    # read back INDI configuration and print
