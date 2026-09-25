# Control revision 3

Update and restart both laptop and Pi. Mismatched control revisions disable
drive. Startup readiness is a software neutral timer, not an ESC acknowledgement.

- Neutral remains 1500 us. D is bounded to 1500..2000 us; R to 1000..1500 us.
- D 7% maps to 1864 us, the rounded pulse previously sent at displayed 50%:
  `1540 + (0.45 + (0.50 - 0.07) * 0.55 / 0.93) * 460`.
- Above 7%, acceleration interpolates to 2000 us at 100%. Below creep,
  interpolation to neutral supports gradual pulse reduction. Reverse creep
  remains 1253 us; the new forward observation does not calibrate reverse.
- This is a no-brake ESC. Brake never requests reverse torque. While the pedal
  exceeds 4%, Pi ignores drive demand and approaches neutral in pulse space.
  Rate is `40 + 860 * ((brake - 0.04) / 0.96)^1.3` us/s. Full pedal reduces
  1864 us to neutral in about 0.405 s. Holding brake cannot increase output.
- Releasing brake restores the virtual-speed target with a 700 us/s pulse slew
  limit. RPM/transmission/speed remain simulated; braking also suppresses
  simulated propulsion, and deeper pedal produces faster virtual deceleration.
- MOTOR displays signed Pi output, not the virtual target. Its tooltip shows
  requested pulse/mode/selector. These values are not electrical measurements.
- Steering center remains 1786 us; endpoints are 1672 and 1900 us, equal
  +/-114 us within the previously used limits. This reduces left travel rather
  than extending the unverified right limit. Greater symmetric travel requires
  mechanical alignment or separately verified safe endpoints.

Without wheel-speed feedback, decreasing motor drive cannot guarantee a physical
stopping distance or active braking torque. Validate on a supported chassis
before ground driving. If 1500 us itself causes reverse, the neutral calibration,
actual PWM waveform, or another writer must be investigated; software boundary
tests alone cannot establish real motor direction.
