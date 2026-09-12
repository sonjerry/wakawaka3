# Validation

## Static
- Python syntax: PASS
- JavaScript syntax: PASS
- JS → HTML ID consistency: PASS

## Powertrain v3
- Full-throttle virtual 0–60 mph: 8.99 s
- WOT shifts: 1→2@54.1km/h / 2→3@76.6km/h / 3→4@84.6km/h / 4→5@103.4km/h / 5→6@131.4km/h / 6→7@174.7km/h
- WOT gear hunting: NONE
- One-tick ESC PWM drop during WOT shifts: 0.000000
- Steady 15/30/50/70% throttle hunting: NONE
- Pedal-stab multi-gear kickdown: PASS (7→3)
- Full braking to 0 + 1st-gear preselection: PASS
- Throttle release transient: <1 km/h additional rise before coast-down
- Coast inertia: PASS

## Gauge v3
- RPM: 0–6500 rpm
- Speed: 0–200 km/h
- Exact 270° SVG scale
- tick / label / needle use same mathematical angle mapping
- boot sweep uses complete gauge range

Hardware feel still depends on actual RCXAZ ESC calibration, DC motor/load, battery voltage and steering geometry.
