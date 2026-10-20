## Customizing ASTRA

We have intentionally limited the scope of ASTRA hardware to a few carefully selected 
components. A major reason for this is to avoid complexity in the system software and 
to enable consistency with use of the system for lessons and projects. 

Having said the above, it is possible to modify ASTRA or use different components. However,
we don't generally plan on directly supporting modifications or incorporating them into the build instructions, software code base, 3D printing models, or documentation. 

There are other software tools which can be used with ASTRA hardware successfully. They are sometimes
capable of specific activities or tasks where the ASTRA UI falls short. 

Hardware substitutions can be more problematic. In developing ASTRA we had a number of occassions
where components caused difficult to diagnose self interference. Additionally, not all components such
as batteries, mounts, and cameras are created equal. There are some areas we would have liked better performance are behaviors. 

Here are some notes on alternatives for various components. Some of them fairly extensive based on our
testing. 

## Alternative Hardware

### Bases

ASTRA doesn't really rely on the rolling base for more than moving the system easily and leveling. The mount used with the unit can also do the leveling function. Using ASTRA without the base may be easier if you aren't rolling it in an out of classrooms or if you have a fixed location. However, for a fixed mounting you need to manage weather proofing for an outdoor installation. The ASTRA hardware isn't well enough sealed to live in the wild without protection. A traditional telescope dome or RF transparent outdoor bubble dome or tent is a potential solution. 

### Antennas

It is possible to use other antennas in place of the Discovery dish. In particular, a larger dish will 
provide some additional sensitivity. You actually need to get quite a bit larger for better angular resolution. It is also possible to use a Hydrogen Line tuned Yagi antenna with
a customized bracket.

We have looked a bit at pairing a [solar cooker](https://www.amazon.com/dp/B0C2Z962SY?ref_=ppx_hzsearch_conn_dt_b_fed_asin_title_4) with the heavier [Wave 150i Pro](https://www.skywatcherusa.com/products/wave-150i-strainwave-mount) Strainwave mount. 

### Mounts

ASTRA and the associated software are really designed around an Az Alt capable mount. A few other 
potential models include:

- [Skywatcher Wave 100i Pro](https://www.skywatcherusa.com/products/wave-100i-with-carbon-fiber-tripod-extension-tube-kit?_pos=2&_sid=5540e9e61&_ss=r)
- [Skywatcher Wave 150i Pro](https://www.skywatcherusa.com/products/wave-150i-strainwave-mount)
- [MLAstro SAL-33](https://mlastro.com/product/mlastro-sal-33/)
- [MLAstro One](https://mlastro.com/product/mlastro-one/)

The above mounts are more expensive but will support larger antenna and telescope assemblies. The MLAstro unit will take a modification of the ASTRA antenna controller software. The Skywatcher units will likely work with the existing Synscope control layer. 

### Optical Telescopes

The specific finder scope used in the ASTRA bill of materials is a good balance of performance and cost. Alternative telescopes are possible up to the mount weight limits. With larger mounts it is possible to use larger radio telesccope antenna and optical assemblies. In many cases this make ASTRA
harder to user and you quickly will end up with both a wide field (finder scope) and narrow field optical imaging system. 

For slightly higher cost it may be valuable to consider a faster optical telescope that provides a wider field of view. Note that many optical telescopes are far too big for the mount in the ASTRA bill of materials. An example of an appropriate faster field telescope:

- [SVBony SV535](https://www.svbony.com/products/sv535-portable-f28-35mm-apo-telescope-with-ed-glass)

When using a different telescope it is likely you will need a different adapter and tube stack to attach to the associated CCD. This gets into a lot of details about the telescope and CCD imager that are specific to those selected. 

### CCD Cameras

Modifying the camera can be reasonable when paired with a different telescope or where there may be an
emphasis on either wider field or deeper imaging.

We have matched the optical telescope and CCD camera pixel size to be reasonable for a range of wide field astronmical targets. Other cameras from [QHYCCD](https://www.qhyccd.com/) will likely work, possibly without modification of the software. We have had bad luck with a number of cameras generating interference. This can be expensive to find out.

Note, there is a point where it makes more sense to split the optical telescope from the radio telescope and simply have separate units. The radio telescope dish surface can transfer wind and vibration to the optical assembly. That can negatively impact optical imaging. 

### Software Radio

It is possible to use different software radios although the ASTRA software is currently hardwired 
for the Analog Devices Pluto. Although the RTL-SDR radio is much lower cost and can receive the 1420 MHz hydrogen line. It has a very poor passband shape and is very sensitive to inteference. As such it is actually difficult to detect the H-line signal under many conditions. The Pluto has a much wider passband and a spectrally flater and more linear response. Ettus and RFSoC radios (e.g. Digilent RFSoC 4x2) can also be used but tend to be much more expensive. They can be more suitable to multiple channel systems. 


## Interferometry

We have been asked about this a bit so here is some advice on creating an interferometer using ASTRA.

You need two working antennas, feeds, and pointing systems to get interferometry to work. Antenna alignment must be reasonable bewteen the two systems. For example, both systems need to be able to accurately point at the Sun to use it as a source. 

In general an interferometer that is physically connected to a common radio is far more likely to work properly. Unfortunately, most inexpensive radios are not well suited to separate digitization and digital processing to combine the signals. This is possible but more costly and has its own complexities.  

### Analog Sum Interferometry
 
 Connected interferometry can be done using two antennas and feeds separated by a fixed baseline and pointing in the same direction. The RF signals from the two systems are combined in analog using a combiner or hybrid and power detection is done in the digital processing. This produces a summing interferometer and will generate fringes related to the source structure in the pointing direction and baseline spacing.  

### Digital Interferometry

For disconnected interferometry it is necessary to have highly coherent and externally clockable radios. Inexpensive radios can sometimes be hacked to share a common clock but this won't be useable over long baselines. A high performance GNSS stabilized ovenized crystal will provide reasonable performance for disconnected 1420 MHz interferometry over reasonable baselines.  
