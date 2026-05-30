"""
    boot.py

    Adafruit Feather RP2040 boot.py 

    This is used to load specific configurations on boot. In particular the USB CDC interface.

"""
import storage
import usb_cdc

def connect_usb_cdc():
    usb_cdc.enable(console=True, data=True) # turn on a CDC data path
    # limit any potential blocking with timeouts

storage.remount("/", True) # False makes it writable by the board, read-only to the PC
connect_usb_cdc()

