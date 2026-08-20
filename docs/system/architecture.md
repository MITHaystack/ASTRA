## ASTRA Architecture

The ASTRA architecture derives from many recent distributed instrument
platforms developed by MIT Haystack Observatory. Ultimately many of these sensors have 
fairly common features when compared to ASTRA. Here they simply take on a smaller scale,
use less expensive components, and provide a bit lower level of capability. 

The overall design was selective in the choice of elements. Both cost, performance,
availability, RFI / EMI, and ease of software interface were considered. We tried a fair
number of hardware components which ultimately were abandoned. This was combined with 
limiting the ASTRA hardware elements to a very small number of possible variations. This is a
very intentional choice to allow for simpler software and more reliable operations. We tried
several existing frameworks to allow for more low level flexibility but ultimately the available
open source projects were not well suited to our needs and development timeline. 

Ultimately ASTRA is intended to be constructed from largely off the shelf components combined 
with a small amount of rapid manufacturing using some key 3D printed elements. It is possible
for a small team to produce the system from the design drawings, bill of materials, and instructions. 
However, don't underestimate the effort and expect integration and testing to take some time. One
particularly important factor is having appropriate test sources and devices available. The availability of inexpensive signal generation, spectral analysis, and network analysis makes this
more viable than in prior years. 

The system is divided into sensors, mechanical and motion elements, an antenna and software
radio, a control computer, and an "energy unit" that combines power regulation and a battery. 
These elements are integrated together onto a "cart" which provides a leveling platform and 
the ability to roll around on relatively smooth surfaces. It is possible to make a cart which can handle off road applications but this takes fairly big wheels and a modification of the template bracket used for base construction and tripod support. Environmental tolerance is somewhat
limited in the design. In particular the unit is not well suited to outdoor use rain, high wind, snow or condensing humid environments. This is necessary to keep costs affordable and due to the challenges of proper housing for optical systems outdoors.

The system software uses a distributed asynchronous messaging control system that is
event driven. This provides a stream of sensor data as MQTT messaging events, allows for 
command and control via an MQTT messaging API, and interface to a user interface via a shared
and asynchronously gathered interface state. An early version of this architecture was originally
developed for the Mahali project to control remote GPS systems in Alaska. 

### System Overview
![img](<img/astra-architecture.png>)
