# ASTRA Makers

Building ASTRA is challenging but possible!

## Overview

Construction of an ASTRA unit includes the following major steps:

1. Purchase the needed components using the [BoM](../hardware/bom/astra-bom.csv).
1. 3D print the base template, antenna bracket, and antenna interface unit and lid.
1. Cut and assemble the base from wood using the template.
1. Assemble the tripod and AzGti mount
1. Build the Discovery Dish and feed
1. Assemble and wire the Antenna Interface unit components
1. Attach the discovery dish to the mount using the mounting bracket
1. Attach the counter-weight and bar
1. Assemble and attach the optical system
1. Assemble the DAQ and Energy Unit
1. Cable the system. 
1. Install software on the computer system. 

## 3D Printed Components

ASTRA uses 3D printed components to enable RF bias, an RF calibrator, a user display, and more integrated cable management. 

- [3D Printing Files](../../models/)
- [3D Printing Instructions](../hardware/3d_prints.md)

### Antenna Mounting Bracket

A customized Antenna Mounting Bracket is used to provide a strong mechanical connection for the antenna and a metal mount dove tail rail. The bracket also provides sufficient spacing for combination
with the Antenna Interface Unit. 

- [Antenna Mounting Bracket STL](../../models/astra-ai-bracket.stl)

### Antenna Interface Unit (AI)

The ASTRA AI contains the electronics needed to interface 

- [Antenna Interface Lid](../../models/astra-ai-bracket-enclosure-lid.stl)
- [Antenna Interface Enclosure](../../models/astra-ai-bracket-enclosure.stl)

### Base Template



### Solar Filter

## ASTRA Base

The ASTRA Base is designed for easy movement of the system in and out of a typical classroom. It is possible to use "off road" capable wheels with the system to improve portability. Care must be taken with the base not to tip the system over and it can be easier to simply use the tripod and transport ASTRA in component sections. 

The Base is constructed using wood working tools and supplies. You can leave the materials relatively unfinished or coat them for asthetics and weather protection. 

- [Base Build Details](../hardware/base.md)

## ASTRA Mount

An AzAlt mount intended for optical astronomy is repurposed to provide a suitable mount for the Discover Dish. This is a less expensive and more accurate solution than other currently available mounts. The central support for the mount is left out when using with the ASTRA base. This is needed to allow for a sufficient spacing for the DAQ and Energy unit. A tension based solution is used to prevent the overall mount from falling off the base. 

- [Mount Assembly](../hardware/mount.md)

## ASTRA Antenna and Feed

ASTRA uses a Discover Dish and a custom mounting bracket. The Discovery H-line feed is also used with 
the design although it is possible to swap in other feeds for satellite observations (i.e. L-band or S-band). 

- [Antenna and Feed Assembly](../hardware/antenna.md)

## Antenna Interface

The Antenna Interface contains an RF bias T, RF noise diode calibrator, RP2040 controler, IMU, Magnetometer, OLED display, and USB hub. It provide clean cable connections and consolidates the
USB cable wiring into a data and RF connection to the DAQ and Energy unit. Placed at the back of the 
antenna it provides sensors for antenna orientation that can be useful for aligning the system. 

- [Antenna Interface Assembly Instructions](../hardware/ai_assembly.md)

## DAQ and Energy Unit

The Data Acquisition and Energy Unit combines the software radio, computer, and a power station into
a single enclosure with appropriate cable entries to allow it to operate closed. This helps simplify
the cabling of the unit, provides a source of power, and helps provide some weather protection. 

It is necessary to foil shield the software radio and computer to prevent self interference. The cables used have EMI filtering and it can be tricky to get the system to not jam itself. 

- [DAQ and Energy Unit Build Details](../hardware/energy_unit.md)

