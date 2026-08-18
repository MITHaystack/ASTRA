## ASTRA Architecture

The ASTRA architecture derives from many recent distributed instrument
platforms developed by MIT Haystack Observatory. 

- [Design Drawing](../drawings)
- [Environmental](./architecture.md)
- [System Notes](./system.md)

The overall design was selective in the choice of elements and limiting the
design to a small number of possible variations is intentionally. Ultimately 
ASTRA is intended to be constructed from largely off the shelf components combined 
with a small amount of rapid manufacturing using some key 3D printed elements. 

The system is divided into sensors, mechanical and motion elements, an antenna and software
radio, a control computer, and an "energy unit" that combines power regulation and a battery. 
These elements are integrated together onto a "cart" which provides a leveling platform and 
the ability to roll around on relatively smooth surfaces. Environmental tolerance is somewhat
limited in the design. Largely to keep costs affordable and due to the challenges of proper 
housing for optical systems outdoors.

The system software uses a distributed asynchronous messaging control system that is
event driven. This provides a stream of sensor data as MQTT messaging events, allows for 
command and control via an MQTT messaging API, and interface to a user interface via a shared
and asynchronously gathered interface state. An early version of this architecture was originally
developed for the Mahali project to control remote GPS systems in Alaska. 

### System Overview
![img](<img/astra-architecture.png>)
