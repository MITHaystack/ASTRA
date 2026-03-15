# ASTRA
The Automated Small Telescope for Radio Astronomy (ASTRA) is a low cost platform for astronomy education.

## Description

ASTRA integrates a small radio telescope, an optical wide-field imaging system, a position and orientation sensor, and a GoTo mount. 
An onboard computer enables automation and control of the system. Combined with a browser based interface to student laptops the 
platform can be used for collection and visualization of radio and optical astronomy data. This enables active learning for science
and radio education through real world measurement.  

The system is relatively inexpensive and suitable for use by a science program or astronomy club. ASTRA can be used as an 
adjunct for lesson plans related to the electromagnetic spectrum, chemistry and physics, and radio and optical astronomy. More advanced
'mini projects' are also possible for small groups of enthusiastic students who are willing to put in more work observing. 

## Key Features

- 70 cm diameter [Discovery Dish](https://www.crowdsupply.com/krakenrf/discovery-dish) radio antenna
- Hydrogen Line (1420 MHz) feed and software radio
- 100mm optical F/2.8 wide field of view optical telescope 
- 8 Mega Pixel CCD (uncooled) for optical imaging
- Goto Telescope Mount 
- Integrated Navigation (GNSS?/GPS), Inertial Measurement (IMU), and Orientation (Magnetometer)
- Battery Operation (24hr+)
- Rolling Base / Cart

### Example Observations

ASTRA can be used to make [radio](docs/observations/radio-obs.md) and [optical](docs/observations/optical-obs.md) observations. This includes
radio measurement of the hydrogen line, galactic structure and rotation. Optical imaging of the Sun, Moon, star clusters, and major Nebula also 
enables a direct comparison of radio signatures with wide field of view imaging. 

### System Details

ASTRA can be constructed by a small group using off the shelf components, 3D printed brackets and enclosures, and open source software. 

- [Components](hardware/components-overview.md)
- [Assembly](hardware/assembly-overview.md)
- [Software Configuration](software/software-overview.md)
- [Integration and Testing](testing/testing-overview.md)
- [Focusing and Calibration](testing/focusing-cal-overview.md)
- [Environmental](testing/environmental-overview.md)
- [Prior Versions](docs/astra-prior-version-archive.md)

Although many alternative components exist the overall selections for ASTRA are a good balance of cost, performance, and integration complexity. 

## Getting Started

## Lessons

Our lessons are currently under development and will be released after we complete testing them. 

### Introduction
- [What is ASTRA?](lessons/astra-intro-overview)
- [Observing with ASTRA](lessons/astra-intro-observing)

### Setup and Calibration
- [How to Align ASTRA](lessons/astra-intro-align)
- [How to Focus ASTRA](lessons/astra-intro-focus)
- [Safe Observing with ASTRA](lessons/astra-safety)

### Basic Data Taking
- [Pointing and Tracking](lessons/astra-intro-pointing)
- [Radio Measurement](lessons/astra-radio-measurements)
- [Optical Measurement](lessons/astra-optical-measurements)

### Lesson Plans
- [The Electromagnetic Spectrum](lessons/astra-em-spectrum)
- [The Hydrogen Line at 1420 MHz](lessons/astra-hline-intro)
- [Radio Waves and Propagation](lessons/astra-radio-propagation)
- [Astrochemistry](lessons/astra-astro-chemistry)
- [Outer Space is Not Empty](lessons/astra-space-not-empty)

### Mini Projects
- [Radio and Optical Imaging of the Sun](projects/astra-project-solar)
- [Radio and Optical Imaging of the Moon](projects/astra-project-lunar)
- [Galactic Rotation Curve](projects/astra-project-rotation-curve)
- [Detection of Jupiter](projects/astra-project-jovian)
- [Imaging Andromeda](projects/astra-project-andromeda)
- [The Crab Nebula](projects/astra-project-crab-nebula)
- [Star Cluster Survey](projects/astra-project-star-clusters)
- [Imaging Sagitarius A*](projects/astra-project-sagitariusA)

## License

BSD 3-clause "New" or "Revised" license, see the associated license file. 

## Acknowledgments

ASTRA leverages both the Discovery Dish, GNU Radio, RTL-SDR, Stellarium web, JupyterLab, the Raspberry Pi, Python, and a range of open source libraries
to implement the needed control, user interface, data processing, and hardware systems. These tools are generally installed directly from online repositories. 
