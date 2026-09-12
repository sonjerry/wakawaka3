# Validation v4

## ESC / hardware
- ESC startup neutral handshake: 1500us for 3.0s
- Full forward command: 2000us
- Full electronic-brake command while moving forward: 1000us
- Failsafe: drive disabled + neutral
- `/health` exposes `esc_ready`, `drive_enabled`, `esc_pulse_us`, `esc_mode`
- Steering effective center: 1545us (1500 + 45 trim)

## Braking
- Virtual full braking from 100 km/h: ~2.51 s to stop in simulation
- Physical ESC brake path is now active; brake input is no longer ignored by Pi
- Brake signal returns to neutral below 0.8 km/h to prevent accidental reverse at stop

## UI
Removed requested visible blocks:
- RC / TRAILBLAZER RC / DRIVER INFORMATION CENTER header
- WASD / CONTROL / VIDEO / ENGINE ON / RTT top status row
- BRAKE TO SHIFT / LOCKED row
- CONTROL RTT row
- DRIVE READY / HOLD BRAKE TO SHIFT text
- auxiliary footer text strip

Retained:
- camera
- RPM / speed gauges
- steering graphic
- throttle / brake / motor meters
- compact warning lamps
- PRND
- START/STOP and emergency stop

## Static checks
- Python compile: PASS
- JavaScript syntax (`node --check`): PASS
- JS -> HTML element references: PASS
