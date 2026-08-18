The ASTRA computer is an GMKtec G10 Mini PC Computer, Ryzen 5 3500U AMD machine with 12GB of ram and 512GB of SSD. 

The operating system is Ubuntu 26.04 LTS with the normal LTS kernel. I've applied all the latest updates. 

Linux astra-002 7.0.0-29-generic #29-Ubuntu SMP PREEMPT_DYNAMIC Fri Jul 17 20:52:35 UTC 2026 x86_64 GNU/Linux

The primary account is 'astra-admin' and it will generally not be needed by students. Teachers may need it for advanced use of the hardware or fixing problems. It is needed for software updates. 

1. Passwords 

a. astra-admin - This is a sudo capable admin account and the primary ; reset this one to something secure

b. astra - This is a non sudo capable account if some ssh access is needed to run software. ; reset if used

c. ASTRA hotspot SSID password - ASTRA314 , system access still requires one of the above accounts or the web user interface. Recommend to leave as set.

d. Marimo notebook interface - This is a notebook interface to allow students to do advanced lessons, data analysis, and eventually automation of measurements. There is a password key 'astra-002' which is set in the service startup : /etc/systemd/system/marimo.service and is set by the argument --token-password "astra002".

2. Networks

Note that network setup can require a monitor and keyboard and use of network manager via the desktop interface. 

ASTRA should be networked via the primary WiFI to the local external network. This uses the RTL8822CE interface. 

The ASTRA hotspot uses the Realtek 8812AU USB adapter for the hotspot. This is very useful to allow connection to the unit outdoors or where an external network address is not available. This is often used when taking the system out to do observations. It can be disabled if a WiFI network is consistently available in the outdoor location. 

There is an internal "Ethernet network" for the software radio. It is virtual to the USB connection. Don't disable or remove.

> enx00e022942f83: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
>         inet 192.168.2.10  netmask 255.255.255.0  broadcast 192.168.2.255
3. Firewall and Ports

The ASTRA computer exposes the following services and ports through the UFW firewall : SSH, HTTP, RDP (remote desktop). 

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere                  
443                        ALLOW       Anywhere                  
80/tcp                     ALLOW       Anywhere                  
Nginx HTTP                 ALLOW       Anywhere                  
3389/tcp                   ALLOW       Anywhere                  
3389/udp                   ALLOW       Anywhere                  
22/tcp (v6)                ALLOW       Anywhere (v6)             
443 (v6)                   ALLOW       Anywhere (v6)             
80/tcp (v6)                ALLOW       Anywhere (v6)             
Nginx HTTP (v6)            ALLOW       Anywhere (v6)             
3389/tcp (v6)              ALLOW       Anywhere (v6)             
3389/udp (v6)              ALLOW       Anywhere (v6)            

Discussion of services : 

a. SSH is useful for the IT team and possibly the teachers to allow for some reset commands / restarts of services if there are problems. This can also be done using RDP. There are some advanced features of the system which we will document that would need RDP access. Again, primarily useful for debugging. This isn't going to be common for typical student usage. 

b. Interaction is primarily using the web based user interface. 

It is located at the networked IP address (e.g. on my network http://192.168.68.57/) or if connected to the ASTRA hotspot on an address of 10.42.0.1 which shouldn't change. The actual web service interface itself is running on port 8080 and is proxied to port 80 via the nginx web server.

If DNS is available it is possible to assign an address or static mapping to ASTRA which will make it easier to use.  

4. Use of local storage / cleanup

Most data gets downloaded from the unit to the user's laptop. Multiple users and laptops can connect simultaneously. However, they can issue conflicting commands if on the same page. The radio snapshot feature does store data into /data/rf and there is a cleanup button on the user interfaces. There shouldn't be too much need to clean things up. The UI also shows the remaining storage. Future updates may increase the use of local storage. The Marimo notebook interface also makes notebooks and uses storage in /data/notebooks. This is not currently cleaned directly by the UI but using the Marimo interface. 

5. Updates

a. It should be possible to apply operating system updates when the system is networked. Use ssh to get into the unit and do:

'sudo apt-get update'

'sudo apt-get upgrade'

b. Updating the software used by the system may be possible. We hope to have a better update mechanism in a future release. Login as astra-admin using ssh and perform:

'conda update --all'

'cd Programs/ASTRA ; git pull'

'shutdown -r now'

The system will reboot and the latest software should run. 

c. There is some chance things get messed up by an update.

In that case you likely will need MIT Haystack support. I do have a duplicate system which it may be possible to "swap" for a working software upgrade. If this needs to happen we will open an IT ticket via Mr. Kleeman and coordinate configuring things / swapping systems. 

6. Documentation / If things don't work right

https://mithaystack.github.io/ASTRA/

https://github.com/MITHaystack/ASTRA

Problems are often due to power being off or out, a cable connected incorrectly, or pulled / hot plugged while the system is running that causes a software problem. Our logging and debug are limited on the unit at the moment. Generally, check for power, check and reseat the connectors, match the ports versus the documentation, and then reach out for help if needed. 