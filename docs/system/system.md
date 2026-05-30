# ASTRA - System Software Installation

ASTRA uses a compact computer system to control the hardware, aquire data, and provide the user interface. After assembling
the hardware it is necessary to install and configure the operating system. 

## Needed Hardware

The assembled Intel / AMD NUC computer is needed for this step. A monitor, keyboard, mouse, and HDMI cable will be required for initial setup. An M.2 to USB drive dock is necessary for the operating system installation. 

## Power Supply Notes

It can be necessary to use a fully USB-PD compliant power supply for these steps. This is necessary due to the default behavior of the hardware where USB PD and an appropriate cable provide device power. Not all USB cables and power sources will be capable of the needed supply voltage range. 

## Drive Dock

If needed, install a M.2 NVME SSD card into the NUC computer. Be sure to carefully seat the M.2 edge connector and use the 
mounting screw or retainer clip to hold the drive down. Close the enclosure per manufacturer instructions.  

## Ubuntu Installation

Installation uses the [Ubuntu desktop](https://ubuntu.com/desktop). You will need an appropriate USB memory stick of sufficient size (e.g. 16 to 32GB). Follow the Ubuntu installation [instructions](https://ubuntu.com/tutorials/install-ubuntu-desktop#1-overview).

### Root account

Generally 'astra-admin' is used as the system account and on initial install a simple password can be used. For public deployment this should be updated to something suitable for the needed security environment. 

### WiFI

ASTRA uses WiFI in two ways using both the internal WiFi for internet connection and an external WiFI adapter to create a local user connection hotspot. For initial setup the internal WiFI is used with an appropriate internet connected WiFI gateway. This allows for software installation and update. The second adapter is used to provide a WiFI hotspot that allows connection to ASTRA directly. This is useful for operation of the system directly and in the field. Use of the internal WiFI may need to be limited to occassional software updates. 

Configure the internal WiFI for your local network and authentication. It may be possible to have the network adminstrator set
a MAC address specific IP address assignment. This would allow a consistent address for accessing the ASTRA system while connected
to the local network. 


## Boot the computer

Attach a mouse, keyboard, and monitor to the computer using an hdmi adapter. Use the USB memory stick Ubuntu installer. Power up and boot the computer. 

It will be necessary to set the WiFI for an appropriate network. 

Set the default account to astra-admin and select a simple password for the moment. 

## Create ASTRA user

It can be useful to have a user account separate from the admin account. To create an astra user do the following:

''' 

sudo adduser astra
sudo usermod -a -G adm,dialout,cdrom,audio,video,plugdev,games,users,input,netdev astra

'''

If needed add sudo to the ASTRA user. This is useful for remote access and development.

'''
sudo usermod -a -G sudo astra
'''

## Configure Remote Desktop

In the Settings tool, select "System" and enable both "Secure Shell" and "Remote Desktop".  

You may also need to install ssh using a terminal. 

''' 
sudo apt-get install ssh
sudo ufw allow ssh
    
'''

## Configure the WiFI Access Point

For field use it is very valuable to have ASTRA generate a local WiFI Access Point. This wireless interface allows for
devices to connect to ASTRA for web based remote control. The Access Point does not have to be externally connected to
the internet. An external USB WiFI dongle and antenna are used to provide this interface. 

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
mkdir /data/images
mkdir /data/config
mkdir /data/mnt

'''

## Install Radioconda

[Radioconda](https://github.com/radioconda/radioconda-installer) provides an encapsulated environment of software radio tools. This
software allows for use of GNU radio, DigitalRF, and the tools needed for the H-line software radio interface. 

Download the installer and run it:

'''
cd Downloads
wget https://glare-sable.vercel.app/radioconda/radioconda-installer/radioconda-.*-Linux-x86_64.sh
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

Current [link](https://www.qhyccd.com/html/prepub/log_en.html#!log_en.md) with the latest [driver](https://www.qhyccd.com/file/repository/publish/SDK/25.09.29/sdk_linux64_25.09.29.tgz)

Download this file, open the archive, and install the software. 
'''

wget https://www.qhyccd.com/file/repository/publish/SDK/25.09.29/sdk_linux64_25.09.29.tgz

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

sudo apt-get install cmake librtaudio-dev libfftw3-dev libglfw3-dev libzstd-dev libairspy-dev libairspyhf-dev libhackrf-dev libiio-dev libad9361-dev libsoapysdr-dev

mkdir build
cd build
cmake  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 ../
make -j 8 
sudo make install

'''

## Install Stellarium

'''
sudo apt install stellarium
'''

### Enable Stellarium goto mount plugin

This requires a direct display or RDP connection.

## Install ASTRA Software Distribution

## Activate ASTRA Services



