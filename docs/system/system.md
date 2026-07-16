# ASTRA - System Software Installation

ASTRA uses a compact computer system to control the hardware, aquire data, and provide the user interface. After assembling
the hardware it is necessary to install and configure the operating system. 

## Needed Hardware

The assembled Intel / AMD NUC computer is needed for this step. A monitor, keyboard, mouse, and HDMI cable will be required for initial setup. An M.2 to USB drive dock is necessary for the operating system installation. 

## Power Supply Notes

It can be necessary to use a fully USB-PD compliant power supply for these steps. This is necessary due to the default behavior of the hardware where USB PD and an appropriate cable provide device power. Not all USB cables and power sources will be capable of the needed supply voltage range. NEEDS MORE INFO HERE Add link to acceptable cable examples or image

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

``` 

sudo adduser astra
sudo usermod -a -G adm,dialout,cdrom,audio,video,plugdev,games,users,input,netdev astra

```

If needed add sudo to the ASTRA user. This is useful for remote access and development.

```
sudo usermod -a -G sudo astra
```

## Configure Remote Desktop

In the Settings tool, select "System" and enable both "Secure Shell" and "Remote Desktop".  

You may also need to install ssh using a terminal. 

``` 
sudo apt-get install ssh
sudo ufw allow ssh
sudo ufw allow https
sudo ufw allow http
    
```

## Configure the WiFI Access Point

For field use it is very valuable to have ASTRA generate a local WiFI Access Point. This wireless interface allows for
devices to connect to ASTRA for web based remote control. The Access Point does not have to be externally connected to
the internet. An external USB WiFI dongle and antenna are used to provide this interface. 

### Install HostAPD and DNSMasq

``` 
sudo apt install dnsmasq hostapd
```

Edit '/etc/dhcpcd.conf' as sudo using an appropriate editor and at the end add:

```
### Configure ASTRA access point address range
interface wlan1
   static ip_address=192.168.20.1/24
   nohook wpa_supplicant
```

### Configure access point DNS DHCP range
Edit '/etc/dnsmasq.conf' as sudo and using an appropriate editor and at the end add:

```
interface=wlan1
dhcp-range=192.168.20.2,192.168.20.128,255.255.255.0,24h
```

### Configure the access point host software

Edit '/etc/hostapd/hostapd.conf' as sudo and using an appropriate editor, add:

```
country_code=US
interface=wlan1
ssid=ASTRA
auth_algs=1
wpa=2
wpa_passphrase=ASTRA314
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP CCMP
rsn_pairwise=CCMP

```

Edit '/etc/default/hostapd' as sudo using an editor and replace '#DAEMON_CONF' with:

```
DAEMON_CONF="/etc/hostapd/hostapd.conf"
```

You may need to reboot at this point. Also ensure the USB wireless adapter is installed.

### Activate the access point

Note this does not allow for routing and IP masquerading for the clients. It is purely to allow
direct access to ASTRA for web browser based use of the system. 

```
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl start hostapd

Substitute the name from nmcli device for the wifi interface below for wlan0 and wlan1.
For example:

sudo nmcli d wifi hotspot ifname wlx00c0cabb50b8 ssid ASTRA password ASTRA314

For persistent usage:

nmcli connection add type wifi ifname wlan0 con-name access_point autoconnect yes ssid my_ssid
nmcli connection modify access_point 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
nmcli connection modify access_point wifi-sec.key-mgmt wpa-psk
nmcli connection modify access_point wifi-sec.psk "my_password"
nmcli connection up access_point


```

To enable internet:

```
sudo iptables -A FORWARD -i wlan0 -o wlan1 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A FORWARD -i wlan1 -o wlan0 -j ACCEPT
```

## Create /data directories

```
sudo mkdir /data
sudo chown -R astra-admin:astra-admin /data
mkdir /data/logs
mkdir /data/rf
mkdir /data/images
mkdir /data/config
mkdir /data/mnt
mkdir /data/notebooks

## The /data/examples data are for persistent "backup" data and configurations

mkdir /data/examples
mkdir /data/examples/rf
mkdir /data/examples/images
mkdir /data/examples/config
mkdir /data/examples/notebooks

```

## Install Radioconda

[Radioconda](https://github.com/radioconda/radioconda-installer) provides an encapsulated environment of software radio tools. This
software allows for use of GNU radio, DigitalRF, and the tools needed for the H-line software radio interface. 

Download the installer and run it:

```
cd Downloads
wget https://glare-sable.vercel.app/radioconda/radioconda-installer/radioconda-.*-Linux-x86_64.sh
bash ./radioconda-.*-Linux-aarch64.sh
```

Accept the license and use the defaults for the installation.

## Pluto Radio Setup
It is necessary to install and update some udev rules to enable the non-root
accounts to access the PlutoSDR.

```
https://github.com/analogdevicesinc/plutosdr-fw/blob/master/scripts/53-adi-plutosdr-usb.rules

sudo udevadm control --reload-rules
sudo udevadm trigger

```


## Install LogGuru

```
pip install loguru
```

## Install pyserial

A serial interface library is needed for interface to the antenna interface unit
RP2040 computer. 

```
pip install pyserial
```

## Install python-statemachine

We need an asyncio compatible means of handling state machine behavior for
implementing services and control patterns.

```
pip install python-statemachine
```

## install nanomq

Nanomq is used for the local on ASTRA messaging bus. This allows realtime 
interconnection of different software components in a pub-sub framework. 
Nanomq provides a means to bridge ZMQ usage in legacy srt-py software to 
allow for easier migration to MQTT messaging. We build from source to enable
this feature. 

```

```
git clone --recurse-submodules https://github.com/nanomq/nanomq.git
cd nanomq
mkdir build
cd build
cmake ../ -DBUILD_ZMQ_GATEWAY=ON 


```

Instructions for this may be found [here](https://nanomq.io/docs/en/latest/config-description/introduction.html)

```
cd ../etc
sudo cp nanomq.conf /etc
sudo cp nanomq_pwd.conf /etc/
sudo cp nanomq_acl.conf /etc/
sudo cp nanomq_zmq_gateway.conf /etc/

Edit the configuration file to setup correct network and permission configurations. Put logging into /data/logs ...

Create nanomq system user

sudo useradd -r -s /sbin/nologin nanomq

sudo systemctl daemon-reload
sudo systemctl start nanomq

```

## Setup NanoMQ as a serivce

```
sudo nano /etc/systemd/system/nanomq.service

[Unit]
Description=NanoMQ MQTT Broker
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/nanomq start --conf /etc/nanomq.conf
Restart=always
RestartSec=3
User=root
Group=root

[Install]
WantedBy=multi-user.target

```

## install mqtt client libraries

```
pip install paho-mqtt
pip install mqtt5
pip install aiomqtt
or if aiomqtt is older than version 3.0
pip install aiomqtt==3.0.0-alpha.1
```

## Install zmq

```
sudo apt install -y libzmq3-dev
pip install pyzmq
```

## Install redis server
```
sudo apt install redis-server -y
sudo systemctl start redis-server
```


## Install Mongodb

```
sudo apt-get install gnupg curl

curl -fsSL https://pgp.mongodb.com/server-8.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg \
   --dearmor

echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.3 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.3.list

sudo apt-get update

sudo chown astra-admin:astra-admin /var/run/mongodb/
sudo mkdir /var/run/mongodb

```

Note there is a bug which requires a configuration change to enable use with newer Linux kernels. 

```
[Unit]
Description=MongoDB Database Server
Documentation=https://docs.mongodb.org/manual
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=astra-admin
Group=astra-admin
EnvironmentFile=-/etc/default/mongod
#Environment="MONGODB_CONFIG_OVERRIDE_NOFORK=1"
Environment="GLIBC_TUNABLES=glibc.pthread.rseq=1"
ExecStart=/usr/bin/mongod --config /etc/mongod.conf
ExecReload=/bin/kill -HUP $MAINPID
RuntimeDirectory=/data/db/
PIDFile=/data/tmp/mongod.pid
# file size
LimitFSIZE=infinity
# cpu time
LimitCPU=infinity
# virtual memory size
LimitAS=infinity
# open files
LimitNOFILE=32768
# processes/threads
LimitNPROC=32768
# locked memory
LimitMEMLOCK=infinity
# total threads (user+kernel)
TasksMax=infinity
TasksAccounting=false

# Recommended limits for mongod as specified in
# https://docs.mongodb.com/manual/reference/ulimit/#recommended-ulimit-settings

[Install]
WantedBy=multi-user.target

```

## Install Marimo


```
sudo nano /etc/systemd/system/marimo-app.service

sudo systemctl daemon-reload
sudo systemctl enable marimo-app.service
sudo systemctl start marimo-app.service

This is a configuration to allow for editable notebooks. There is a security risk associated with this if
the people doing the coding are not well supervised. However, it does allow for interactive development of
lessons and projects. 

[Unit]
Description=marimo Application
After=network.target

[Service]
Type=simple
User=astra-admin
WorkingDirectory=/data/notebooks
Environment="PATH=/home/astra-admin/radioconda/bin:/home/astra-admin/radioconda/condabin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr>
ExecStart=/home/astra-admin/radioconda/bin/marimo edit --headless --port 8085 --host 0.0.0.0 --token-password "astra"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target



```

## Install QPHYCCD driver

Drivers move around a bit on the QPHYCCD web site. You want the ARM64 driver so it works with Intel / AMD64 machines. 

Current [link](https://www.qhyccd.com/html/prepub/log_en.html#!log_en.md) with the latest [driver](https://www.qhyccd.com/file/repository/publish/SDK/25.09.29/sdk_linux64_25.09.29.tgz)

Download this file, open the archive, and install the software. 
```

wget https://www.qhyccd.com/file/repository/publish/SDK/25.09.29/sdk_linux64_25.09.29.tgz

tar xvzf sdk_linux64_25.09.29.tgz
cd sdk_linux64_25.09.29
sudo bash ./install.sh

```

The QHY camera should be recognized at the next reboot. This can be checked with the lsusb command.

```
lsusb

which gives something similar to

Bus 003 Device 007: ID 1618:0716 QHYCCD QHY715U3G20-20230106

```




## Install Indi Dependencies

```
sudo apt install -y git cdbs dkms cmake fxload libev-dev libgps-dev libgsl-dev libraw-dev libusb-dev zlib1g-dev libftdi-dev libjpeg-dev libkrb5-dev libnova-dev libtiff-dev libfftw3-dev librtlsdr-dev libcfitsio-dev libgphoto2-dev build-essential libusb-1.0-0-dev libdc1394-dev libboost-regex-dev libcurl4-gnutls-dev libtheora-dev libdbus-1-dev pkg-config swig

```

## Install Indi 

```
git clone --depth 1 https://github.com/indilib/indi.git
cd indi
mkdir build
cd build
cmake -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=Release ..
make -j4
sudo make install

```

## Install Indi drivers

We use the telescope control for the skywatcherAPI

## Install Indi 3rd party plugins

We primarily need the QHYCCD indi library and associated indi service. This requires prior installation of the QHYCCD SDK.

``` 
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

```

It is possible to test using the command ```qhy_ccd_test```

## Install PyINDI Client library

``` 
pip install pyindi-client

```

## Install the pyindi web client library

```
pip install git+https://github.com/MMTObservatory/pyINDI.git
```

## Indi Web Manager
```
sudo apt-add-repository ppa:mutlaqja/ppa -y
sudo apt update
sudo apt -y install python3-pip
pip3 install indiweb					(NOTE: Not as root!)
sudo apt -y install indiwebmanagerapp
```

## Astropy
```
pip install astropy
```

## Skyfield
```
   pip install skyfield
```

## Astroquery
```
   pip install astroquery
```

## Magnetic model
```
pip install pywmm
```

## Configure and startup indi service

## Install PyINDI debug services

## Install Stellar Solver

## Install SDRPP

SDRPP is a useful software radio tool and valuable for debug of the software radio. To build SDRPP it is necessary to install several libraries, clone the github repository, and build and install the package. The 
distribution builds online generally do not work properly due to library relocation issues. 

```

sudo apt-get install cmake libvolk-dev librtaudio-dev libfftw3-dev libglfw3-dev libzstd-dev libairspy-dev libairspyhf-dev libhackrf-dev libiio-dev libad9361-dev libsoapysdr-dev

cd Programs
git clone https://github.com/AlexandreRouma/SDRPlusPlus.git
mkdir build
cd build
cmake  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 ../
make -j 8 
sudo make install

```

## Build Kstars / Ekos

```
sudo apt install build-essential cmake git extra-cmake-modules gettext
sudo apt install qt6-base-dev qt6-declarative-dev qt6-multimedia-dev qt6-svg-dev libkf6config-dev libkf6kio-dev libkf6i18n-dev libkf6xmlgui-dev libkf6plotting-dev libkf6notifications-dev libkf6notifyconfig-dev libkf6newstuff-dev libcfitsio-dev libnova-dev libraw-dev libgsl-dev zlib1g-dev libeigen3-dev

```


## Install Stellarium

```
sudo apt install stellarium
pip install stellariumrc

Enable remote control interface if you want.

Enable the Remote Control PluginOpen Stellarium and press F2 to open the Configuration window.Select the Plugins tab in the left-hand menu.Scroll down and click on Remote Control.Check the "Load at startup" box.Close the Configuration window and restart Stellarium.

Start the Web ServerAfter restarting, press F2 and go back to the Plugins tab -> Remote Control.Check both the "Server enabled" and "Enable automatically on startup" boxes.Note the port number (default is 8090).Restart Stellarium one final time to finalize the server activation.

Access the ServerOpen any modern web browser and navigate to http://localhost:8090 to access the standard web GUI, or use http://localhost:8090/tablet7in.html if you are on a smaller 7-inch touch device

```

### Enable Stellarium goto mount plugin

This requires a direct display or RDP connection.

## Install ASTRA Software Distribution

## Activate ASTRA Services



