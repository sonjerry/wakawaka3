# Validation

- Python syntax parse: PASS (9 files)
- Dashboard JS syntax: PASS
- JS -> HTML element ID consistency: PASS
- Ignition model smoke test: PASS
- Vehicle power_on idle RPM: PASS
- Vehicle shutdown -> P / 0 RPM / 0 motor: PASS
- Inertia after throttle release: PASS
- Brake-to-shift interlock implemented in laptop/main.py
- Start requires brake + P/N
- Engine stop requires stopped + P
- Ignition OFF sends Pi armed=false / motor=0 / selector=P
- Boot sequence duration: 2.35 s
- Gauge sweep + warning self-check: implemented in app.js/CSS

Hardware-dependent calibration remains to be verified on the actual RC car:
- DFGT axis mapping
- RCXAZ ESC neutral/forward/reverse pulse widths
- steering servo endpoints
- PCA9685 physical output
- CSI camera / MediaMTX runtime
