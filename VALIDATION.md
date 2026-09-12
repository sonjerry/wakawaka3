# Validation

생성 시 수행한 정적/시뮬레이션 검증 결과:

- Python `compileall`: PASS
- Dashboard JavaScript `node --check`: PASS
- YAML parse: PASS
- 100 Hz virtual vehicle smoke test: PASS
- Full throttle automatic shift sequence: 1 -> 2 -> 3 -> 4 -> 5 -> 6
- Example shift RPM drops:
  - 1 -> 2: 5863 -> 3784 RPM
  - 2 -> 3: 5838 -> 4116 RPM
  - 3 -> 4: 5817 -> 4522 RPM
  - 4 -> 5: 5805 -> 4655 RPM
  - 5 -> 6: 5803 -> 4730 RPM
- Configured top virtual speed reached: 45.0 km/h
- Throttle release: speed remains and decays by inertia instead of instant stop
- D + full brake: speed cannot cross into reverse
- R + full brake: speed cannot cross into forward

Hardware-dependent items cannot be verified in this environment:
- Actual RCXAZ ESC pulse calibration
- Steering servo pulse endpoints
- Driving Force GT Windows axis indices
- Raspberry Pi CSI camera / MediaMTX runtime
- Raspberry Pi I2C/PCA9685 physical output
