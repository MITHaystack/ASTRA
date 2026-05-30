# ASTRA - System Software Installation

'''
NOTE : The Raspberry Pi 5 has problems powering the USB ports and maintaining stability. This stems from very finicky voltage
regulation and the use of USB-PD to power the device. Most USB power sources are not capable of powering the Pi 5 and even
with firmware and eeprom modifications it was not possible to achieve a consistently stable system. 

After extensive work to try an make the Pi 5 function it was necessary to move over to an Intel / AMD x86 NUC platform
machine. This is unfortunate as it added about 7 to 10W to the overall ASTRA power consumption.

'''


ASTRA uses a compact computer system to control the hardware, aquire data, and provide the user interface. After assembling
the hardware it is necessary to install and configure the operating system. 

## Needed Hardware

The assembled Raspberry Pi 5 computer is needed for this step. A monitor, keyboard, mouse, and HDMI to micro-HDMI adapter will be required for initial setup. An M.2 to USB drive dock is necessary for the operating system installation. 

## Power Supply Notes

It can be necessary to use the official Raspberry Pi 5 / USB-PD compliant power supply for these steps. This is necessary due to the default behavior of the hardware where USB power is throttled when a compliant supply is not detected (i.e. most of them).

## Drive Dock

Install the M.2 NVME SSD card into the USB drive dock. Be sure to carefully seat the M.2 edge connector and use the 
mounting screw or retainer clip to hold the drive down. Close the dock complete per manufacturer instructions. Attach the USB
cable to the drive dock and to a computer capable of internet access that has the rpi-imager software installed. 

## Raspbian Installation

Installation uses the rpi-imager [software](https://www.raspberrypi.com/software/). Extensive instructions are available [online](https://www.raspberrypi.com/documentation/computers/getting-started.html#imager-install). 

Select the Raspberry Pi 5 as the 'device' and Rasberry Pi OS (64 bit). The target device should be the M.2 NVME SSD which
is connected via USB. You can preconfigure the system information. This can be useful for initial setup although often things
need an update / fixes anyway. Enable ssh to allow remote debug / login if needed. Only enable Raspberry Pi connect if you intend to use it. 

### Root account

Generally 'astra-admin' is used as the system account and on initial install a simple password can be used. For public deployment this
should be updated to something suitable for the needed security environment. 

### WiFI

ASTRA uses WiFI in two ways using both the internal Pi5 WiFi and an external WiFI adapter. For initial setup the internal WiFI
is used with an appropriate internet connected router. This allows for software installation and update. The second adapter is used
to provide a WiFI hotspot that allows connection to ASTRA directly. This is useful for operation of the system directly and in the
field. Use of the internal WiFI may need to be limited to occassional software updates. 

Configure the internal WiFI for your local network and authentication. It may be possible to have the network adminstrator set
a MAC address specific IP address assignment. This would allow a consistent address for accessing the ASTRA system while connected
to the local network. 

## Configure /boot/firmware/config.txt

After OS installation, mount the USB hosted M.2 NVME SSD on an appropraite computer that can interface with the EXT4 filesystem if possible. Then make the following modifications to the firmware configuration. This is generally located in /<drive mount>/firmware/config.txt and can be edited using a standard text editor (e.g. nano or vi). 

The first two device tree parameters enable NVME and PCIe and the last entry is later in the file and allows the USB ports
to supply full power to devices. The default current limiting of the Pi 5 can create may problematic and non-obvious failure
modes. 

'''
# Uncomment some or all of these to enable the optional hardware interfaces
#dtparam=i2c_arm=on
#dtparam=i2s=on
#dtparam=spi=on
dtparam=nvme
dtparam=pciex1_gen=3

...

[all]
usb_max_current_enable=1
'''

## Install the M.2 SSD into the Pi 5 

Follow the Enclosure instructions for the NVMe M.2 SSD installation with the Pi 5. Remove the device from the USB adapter and install into the Pi 5 computer. Again take care with the connector seating and drive retention screw. 

## Boot the Pi 5

Attach a mouse, keyboard, and monitor to the Pi 5 using a micro-hdmi adapter. Using the official Pi power supp=ly or an equivalent USB-PD compliant power adapter, power up and boot the computer. 

It may be necessary to set the WiFI for an appropriate network. 

## Configure Pi 5 EEPROM

On first boot it is necessary to configure the Pi 5 EEPROM.

Using the command ''' sudo -E rpi-eeprom-config --edit''' edit the eeprom parameters 
to include NVME early in the boot order, PCIe probe, and disable wake on GPIO. The final
command sets the power supply max current default to avoid the need for the official Pi power
supply. 

'''
[all]
BOOT_UART=1
WAKE_ON_GPIO=0
POWER_OFF_ON_HALT=1
BOOT_ORDER=0xf416
PCIE_PROBE=1
PSU_MAX_CURRENT=5000
'''

After successful application of the eeprom configuration it is necessary to reboot. Note if there
is a problem it can be necessary to install an updated eeprom. You can verify the configuration using

'''
rpi-eeprom-update 
rpi-eeprom-config
'''

The update command should show the 'BOOTLOADER: up to date' along with release information. Then the configuration set
should be reflected in the output of the config command. 

## Create ASTRA user

It can be useful to have a user account separate from the admin account. To create an astra user do the following:

''' 

sudo adduser astra
sudo usermod -a -G adm,dialout,cdrom,audio,video,plugdev,games,users,input,netdev,spi,i2c,gpio astra

'''

If needed add sudo to the ASTRA user. This is useful for remote access and development.

'''
sudo usermod -a -G sudo astra
'''

## Configure Remote Desktop

In the Raspberry pi configuration tool, select "Interfacing Options" and enable "VNC" or "Remote Desktop". Apply the changes and reboot. 

''' sudo raspi-config '''

## Configure raspi-config 

### Switch to X11 instead of Wayland

Under ''' sudo raspi-config ''' go to the Advanced Options -> A7 Wayland -> X11

### Disable WiFI power savings

Unser ''' sudo raspi-config ''' go to the Advance Options -> A13 WLAN Power Save -> Disable

### Disable Autologin on Boot

This is necessary to prevent RDP clients from exiting due to lack of multiple desktop support. 

Under ''' sudo raspi-config ''' go to the System Options -> Auto Login -> No 


## Install RDP

Remote Desktop Protocol installation allows for use of an RDP client (e.g. TheWindows App on Windows, Thincast on OSX, and Remmina on Linux, etc.) to interface directly with the ASTRA operating system desktop. This can be very useful for debug of hardware or the use of other software and applications. 

Install packages 

'''
sudo apt update
sudo apt install rpd-x-core rpd-theme rpd-preferences rpd-applications rpd-utilities rpd-developer rpd-graphics rpd-x-extras
sudo apt install xrdp xorgxrdp
'''

reboot

check for operation:

'''
systemctl show -p SubState --value xrdp
'''
which should return 'running'. Then add ssl:

'''
sudo adduser xrdp ssl-cert  
'''

### Configure your local RDP client

You will need to get the ip address of the Pi 5 in order to remotely connect. This may change on boot depending on the wireless
router behavior. Connection to the ASTRA Access Point will be more consistent and is based on the access point configuration default.

'''
astra-admin@astra2:~ $ ifconfig

wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.68.60  netmask 255.255.252.0  broadcast 192.168.71.255
        inet6 fe80::637:daf9:3acb:1ed8  prefixlen 64  scopeid 0x20<link>
        ether 88:a2:9e:a6:39:0e  txqueuelen 1000  (Ethernet)
        RX packets 6941  bytes 568283 (554.9 KiB)
        RX errors 0  dropped 27  overruns 0  frame 0
        TX packets 4702  bytes 1569883 (1.4 MiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0


'''

Set the client to the appropriate address (e.g. 192.168.68.60 in the above case) and select a suitable display resolution. The display
resolution is located in '/etc/X11/xrdp/xorg.conf' on the Pi and it is possible to modify to add resolutions if needed. The resolution
to use will depend on the computer platform available and the screen resolution of that platform.

A typical set of available modes is:

'''
Modes "640x480" "800x600" "1024x768" "1280x720" "1280x1024" "1600x900" "1920x1080"
'''

## Configure the WiFI Access Point

For field use it is very valuable to have ASTRA generate a local WiFI Access Point. This wireless interface allows for
devices to connect to ASTRA for web based remote control. The Access Point does not have to be externally connected to
the internet. An external USB WiFI dongle and antenna are used to provide this interface. 

### Install USB WiFI dongle device driver

Obtain the drivers for the RTL8812AU based product from

''' https://docs.alfa.com.tw/Support/Linux/RTL8812AU/ '''

and follow the Raspberry Pi OS installation instructions.


### Install HostAPD and DNSMasq

''' 
sudo apt install dnsmasq hostapd
'''

Edit '/etc/dhcpcd.conf' as sudo using an appropriate editor and at the end add:

'''
### Configure ASTRA access point address range
interface wlan1
   static ip_address=192.168.20.1/24
   nohook wpa_supplicant
'''

### Configure access point DNS DHCP range
Edit '/etc/dnsmasq.conf' as sudo and using an appropriate editor and at the end add:

'''
interface=wlan1
dhcp-range=192.168.20.2,192.168.20.128,255.255.255.0,24h
'''

### Configure the access point host software

Edit '/etc/hostapd/hostapd.conf' as sudo and using an appropriate editor, add:

'''
country_code=US
interface=wlan1
ssid=ASTRA
auth_algs=1
wpa=2
wpa_passphrase=ASTRA314
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP CCMP
rsn_pairwise=CCMP

'''

Edit '/etc/default/hostapd' as sudo using an editor and replace '#DAEMON_CONF' with:

'''
DAEMON_CONF="/etc/hostapd/hostapd.conf"
'''

You may need to reboot at this point. Also ensure the USB wireless adapter is installed.

### Activate the access point

Note this does not allow for routing and IP masquerading for the clients. It is purely to allow
direct access to ASTRA for web browser based use of the system. 

'''
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl start hostapd
'''

To enable internet:

'''
sudo iptables -A FORWARD -i wlan0 -o wlan1 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A FORWARD -i wlan1 -o wlan0 -j ACCEPT
'''

## Create /data directories

'''
sudo mkdir /data
sudo chown -R astra-admin:astra-admin /data
mkdir /data/logs
mkdir /data/rf
mkdir /data/img
mkdir /data/config
mkdir /data/mnt/rp2040

'''

## Install Radioconda

[Radioconda](https://github.com/radioconda/radioconda-installer) provides an encapsulated environment of software radio tools. This
software allows for use of GNU radio, DigitalRF, and the tools needed for the H-line software radio interface. 

Download the installer and run it:

'''
cd Downloads
wget https://glare-sable.vercel.app/radioconda/radioconda-installer/radioconda-.*-Linux-aarch64.sh
bash ./radioconda-.*-Linux-aarch64.sh
'''

Accept the license and use the defaults for the installation.

## Install LogGuru

'''
pip install loguru
'''

## Install pysynscan library -- DEPRECATE?

Both a serial interface library and the synscan controller library are needed for motion control using
the AzGTI mount. This assumes use of a USB to serial converter as the physical interface. 

'''
pip install pyserial
pip install synscan
'''

## Install QPHYCCD driver

Drivers move around a bit on the QPHYCCD web site. You want the ARM64 driver so it works with 
the Pi 5 CPU. 

Current [link](https://www.qhyccd.com/html/prepub/log_en.html#!log_en.md) with the latest [driver](https://www.qhyccd.com/file/repository/publish/SDK/25.09.29/sdk_Arm64_25.09.29.tgz)

Download this file, open the archive, and install the software. 
'''

wget https://www.qhyccd.com/file/repository/publish/SDK/25.09.29/sdk_Arm64_25.09.29.tgz

tar xvzf sdk_Arm64_25.09.29.tgz
cd sdk_Arm64_25.09.29
sudo bash ./install.sh

'''

The QHY camera should be recognized at the next reboot. This can be checked with the lsusb command.

'''
lsusb

which gives something similar to

Bus 003 Device 007: ID 1618:0716 QHYCCD QHY715U3G20-20230106

'''




## Install Indi Dependencies

'''
sudo apt install -y git cdbs dkms cmake fxload libev-dev libgps-dev libgsl-dev libraw-dev libusb-dev zlib1g-dev libftdi-dev libjpeg-dev libkrb5-dev libnova-dev libtiff-dev libfftw3-dev librtlsdr-dev libcfitsio-dev libgphoto2-dev build-essential libusb-1.0-0-dev libdc1394-dev libboost-regex-dev libcurl4-gnutls-dev libtheora-dev libdbus-1-dev pkg-config swig

'''

## Install Indi 

'''
git clone --depth 1 https://github.com/indilib/indi.git
cd indi
mkdir build
cmake -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=Release ..
make -j4
sudo make install

'''

## Install Indi drivers

We use the telescope control for the skywatcherAPI

## Install Indi 3rd party plugins

We primarily need the QHYCCD indi library and associated indi service. This requires prior installation of the QHYCCD SDK.

''' 
cd Programs
git clone https://github.com/indilib/indi-3rdparty.git
cd indi-3rdparty

cd libqhy
mkdir build
cd build
cmake ../
make -j 4
sudo make install

cd ../..

cd indi-qhy
mkdir build
cd build
cmake ../
make -j 4
sudo make install

'''

It is possible to test using the command '''qhy_ccd_test'''

## Install PyINDI Client library

''' 
pip install pyindi-client

'''

## Install the pyindi web client library

'''
pip install git+https://github.com/MMTObservatory/pyINDI.git
'''

## Configure and startup indi service

## Install PyINDI debug services

## Install Stellar Solver

## Install SDRPP

SDRPP is a useful software radio tool and valuable for debug of the software radio. To build SDRPP it is necessary to install several libraries, clone the github repository, and build and install the package. The 
distribution builds online generally do not work properly due to library relocation issues. 

'''



'''

## Install Stellarium

'''
sudo apt install stellarium
'''

### Enable Stellarium goto mount plugin

This requires a direct display or RDP connection.


## Install Open Live Stacker

### Install cppcms

'''
git clone https://github.com/artyom-beilis/cppcms
cd cppcms
mkdir build
cd build
cmake -DDISABLE_STATIC=ON -DCMAKE_INSTALL_PREFIX=/usr ..
make
make install
'''

### Install dependencies

'''
sudo apt-get install libgphoto2-dev libuvc-dev libtiff-dev libpcre2-dev libcurl4-openssl-dev zlib1g-dev libraw-dev libopencv-dev libopencv-imgcodecs-dev libopencv-imgproc-dev build-essential zlib1g-dev libcfitsio-dev
'''

### Install from github

'''
git clone https://github.com/artyom-beilis/OpenLiveStacker.git
'''

## Install ASTRA Software Distribution

## Activate ASTRA Services



