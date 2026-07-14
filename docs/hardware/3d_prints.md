# ASTRA - 3D Printing Overview

ASTRA uses 3D printed components to enable a highly integrated 
design. This allows for easy transport of a working system and 
ensures that the components remain assembled except at key 
boundaries. 

Printed Components include : 

- Antenna Bracket (ASTRA-AB)
- Antenna Interface Unit Box (ASTRA-AIU-BOX)
- Antenna Interface Unit Lid (ASTRA-AIU-LID)
- AIU Buttons (ASTRA-AIU-BTN)
- Base Template and Bracket (ASTRA-BASE-BRKT)
- SDR Carrier (ASTRA-SDR-CARRIER)
- CPU Carrier (ASTRA-CPU-CARRIER)

For development a Centauri Carbon printer was used with a 
0.6mm hardened steel nozzle and an enclosure. Specific filament
materials were selected based on the needed performance and
testing. 

## Antenna Bracket (ASTRA-AB)

The antenna bracket is used to attach the Discovery Dish and Antenna Interface Unit (AIU)
to the metal Vixen rail. This component will be used outdoors and needs to be strong and relatively UV resistant. 

The material suggested is PETG-CF although others such as ASA or PA6-CF might also work well. PLA or PLA Pro
will work for a short while but are likely to break down with extended usage. Our early PLA 
prototype did not survive very long without distortion. 

Printing settings:

- Material : Filament vendor specific PETG-CF
- Wall Loops : 6
- Top Shell : 6
- Bottom Shell : 6
- Infill : 25%
- Infill pattern : hexagonal
- Infill / Wall Overlap: 25%

The screw holes allow for M6 hardware to be used. If using 1/4 inch hardware it can be
necessary to increase the hole size slightly. This is somewhat filament dependent.
Additionally, it is useful to check your Discovery Dish bracket hole patterns to ensure 
they match the model. This has been an issue for some of the holes.

## Antenna Interface Unit (ASTRA-AIU)

The Antenna Interface Unit contains the electronics associated with the RF bias T, RF noise
diode, RP2040 computer, IMU, GPS, and GPIO interfaces, and a USB hub. The enclosure accomodates
the wiring between the devices and allows for these elements to be mounted onto the ASTRA Antenna
Bracket. The unit consists of a box and an associated lid. Buttons may be printed and inserted into
the appropriate holes relative to the RP2040 mounting. 

We have generally found that a white filament is beneficial for this portion of ASTRA to help 
control heat absorption when the system is used in sunlight. 

### Box (ASTRA-AIU-BOX)

Printing settings:

- Material : Filament vendor specific PLA-PRO (white)
- Wall Loops : 4
- Top Shell : 4
- Bottom Shell : 4
- Infill : 15%
- Infill pattern : hexagonal
- Infill / Wall Overlap: 20%

### Lid (ASTRA-AIU-LID)

Printing settings:

- Material : Filament vendor specific PLA-PRO (black or white)
- Wall Loops : 4
- Top Shell : 4
- Bottom Shell : 4
- Infill : 15%
- Infill pattern : hexagonal
- Infill / Wall Overlap: 20%

### Buttons (ASTRA-AIU-BTN)

Printing settings:

- Material : Filament vendor specific TPU
- Wall Loops : 2
- Top Shell : 2
- Bottom Shell : 2
- Infill : 10%
- Infill pattern : linear
- Infill / Wall Overlap: 10%


## Base Template and Bracket (ASTRA-BASE-BRKT)

The Base Template and Bracket is used for cutting the ASTRA base and as part 
of the construction to hold the tripod feet and attach the tie down cords. These
components experience a fair amount of stress and need to be made of a strong
material. Thermal tolerance can be necessary for ASTRA units when used outdoors
in sunlight. 

Printing settings:

- Material : Filament vendor specific PETG-GF or PETG-CF
- Wall Loops : 6
- Top Shell : 6
- Bottom Shell : 6
- Infill : 25%
- Infill pattern : hexagonal
- Infill / Wall Overlap: 25%

## SDR Carrier (ASTRA-SDR-CARRIER)

The SDR carrier is used to allow for the radio to be constrained from moving
using only a piece of kapton tape. It is also necessary to cover the radio carrier in 
copper foil tape for control of interference. The carrier is sized to accomodate the Analog Devices
ADLAM Pluto Software Defined Radio. It is possible to modify this carrier to accomodate other 
radios if necessary. The radio is roughly centered in this carrier with openings at each end for
input and output connections. 

Printing settings:

- Material : Filament vendor specific PLA-PRO (black)
- Wall Loops : 4
- Top Shell : 4
- Bottom Shell : 4
- Infill : 15%
- Infill pattern : hexagonal
- Infill / Wall Overlap: 20%

## CPU Carrier (ASTRA-CPU-CARRIER)

The CPU used in ASTRA can vary and for some types of systems it can be 
valuable to have a CPU carrier. This allows the CPU to be held down via kapton and covered
with EMI copper foil as necessary. Care must be taken when modifying the carrier for
different computers to allow for proper airflow and exposure of any heat sinks for good
thermal transfer and cooling. 

Printing settings:

- Material : Filament vendor specific PLA-PRO (black)
- Wall Loops : 4
- Top Shell : 4
- Bottom Shell : 4
- Infill : 15%
- Infill pattern : hexagonal
- Infill / Wall Overlap: 20%

## Acknowledgements

An Education version of Autodesk Fusion was used for the development
of ASTRA 3D printed hardware. We thank Autodesk corporation for
providing access to this software. Please add an absolute coordinate readout 
and snap to grid option for the mouse cursor position in 2d / 3d views. 
