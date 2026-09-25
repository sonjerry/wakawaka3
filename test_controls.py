import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "laptop"))
sys.path.insert(0, str(ROOT / "raspberry_pi"))
sys.modules.setdefault("smbus2", SimpleNamespace(SMBus=object))

from hardware import ESCController, SteeringController
from input_manager import InputManager
from vehicle import VehicleModel


def config(name):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


class FakePCA:
    def __init__(self):
        self.outputs = []

    def pulse_us(self, channel, pulse):
        self.outputs.append((channel, pulse))


class ControlTests(unittest.TestCase):
    def drive(self, selector="D"):
        esc = ESCController(FakePCA(), config("pi.yaml"))
        esc.ready = True
        esc.set_drive_enabled(True)
        esc.selector = selector
        return esc

    def test_brake_never_sends_reverse_pulse_in_drive(self):
        for brake in (0.05, 0.2, 0.5, 1.0):
            esc = self.drive()
            esc._write_pulse(1864, "DRIVE")
            previous = 1864
            for _ in range(300):
                esc.update(-0.6, brake, 0.05, "D")
                self.assertGreaterEqual(esc.last_pulse_us, 1500)
                self.assertLessEqual(esc.last_pulse_us, previous)
                previous = esc.last_pulse_us
            self.assertEqual(esc.last_pulse_us, 1500)

    def test_brake_depth_sets_pulse_decay_rate(self):
        pulses = []
        for brake in (0.2, 0.5, 1.0):
            esc = self.drive()
            esc._write_pulse(1900, "DRIVE")
            esc.update(1.0, brake, 0.05, "D")
            pulses.append(esc.last_pulse_us)
        self.assertGreater(pulses[0], pulses[1])
        self.assertGreater(pulses[1], pulses[2])
        self.assertEqual(pulses[2], 1855)

    def test_selector_change_clears_reverse_residual(self):
        esc = self.drive("R")
        esc._write_pulse(1200, "DRIVE")
        esc.value = -0.3
        esc.update(0.7, 0, 0.05, "D")
        self.assertEqual(esc.last_pulse_us, 1500)
        for selector in ("P", "N", "invalid"):
            esc.update(1, 0, 0.05, selector)
            self.assertEqual(esc.last_pulse_us, 1500)

    def test_nonfinite_input_goes_neutral(self):
        for bad in (float("nan"), float("inf"), None):
            esc = self.drive()
            esc._write_pulse(1900, "DRIVE")
            esc.update(bad, 0, .05, "D")
            self.assertEqual(esc.last_pulse_us, 1500)

    def test_brake_release_is_slew_limited_and_reverse_requires_r(self):
        esc = self.drive()
        esc.update(1, 0, .05, "D")
        self.assertEqual(esc.last_pulse_us, 1535)
        esc.update(-1, 0, .05, "D")
        self.assertEqual(esc.last_pulse_us, 1500)
        reverse = self.drive("R")
        reverse.update(-1, 0, .05, "R")
        self.assertEqual(reverse.last_pulse_us, 1465)
        reverse.update(-1, 1, .05, "R")
        self.assertEqual(reverse.last_pulse_us, 1500)

    def test_virtual_coast_and_progressive_brake(self):
        speeds = []
        for brake in (0, .2, .7, 1):
            car = VehicleModel(config("vehicle.yaml"))
            car.power_on()
            car.set_selector("D")
            car.speed_mps = 15
            car.motor = .3
            for _ in range(20):
                state = car.update(0, brake, 0, .05)
                self.assertGreaterEqual(state["motor_output"], 0)
            speeds.append(car.speed_mps)
        self.assertGreater(speeds[0], speeds[1])
        self.assertGreater(speeds[1], speeds[2])
        self.assertGreater(speeds[2], speeds[3])
        self.assertGreater(speeds[0], 10)

    def test_creep_displays_seven_percent_and_brake_cuts_it(self):
        car = VehicleModel(config("vehicle.yaml"))
        car.power_on()
        self.assertTrue(car.set_selector("D"))
        for _ in range(30):
            state = car.update(0.0, 0.0, 0.0, 0.05)
        self.assertGreater(state["speed_kph"], 0)
        self.assertGreaterEqual(state["motor_output"], 0.07)
        self.assertLess(state["motor_output"], 0.10)
        for _ in range(60):
            state = car.update(0.0, 1.0, 0.0, 0.05)
        self.assertEqual(state["motor_output"], 0.0)
        self.assertGreaterEqual(state["signed_speed_kph"], 0)

    def test_keyboard_steering_holds_at_rest_and_recenters_forward_only(self):
        controls = InputManager(config("input.yaml"))
        controls.keys["a"] = True
        controls._keyboard(0.2, 0.0)
        left = controls.k_steer
        controls.keys["a"] = False
        controls._keyboard(1.0, 0.0)
        self.assertEqual(controls.k_steer, left)
        controls._keyboard(1.0, -10.0)
        self.assertEqual(controls.k_steer, left)
        controls._keyboard(0.2, 6.5)
        self.assertGreater(controls.k_steer, left)
        self.assertLess(controls.k_steer, 0.0)

    def test_seven_percent_creep_reproduces_previous_50_percent_pulse(self):
        esc = ESCController(FakePCA(), config("pi.yaml"))
        old_fifty = 1540 + (0.45 + (0.50-0.07)*0.55/0.93)*460
        self.assertEqual(esc._pulse_for_drive(0.07), round(old_fifty))
        self.assertEqual(esc._pulse_for_drive(-0.07), 1253.0)
        self.assertEqual(esc._pulse_for_drive(0.0), 1500.0)
        self.assertEqual(esc._pulse_for_drive(1.0), 2000.0)
        for percent in range(1, 101):
            value = percent / 100
            self.assertAlmostEqual(esc._drive_for_pulse(esc._pulse_for_drive(value)), value)

    def test_left_right_travel_and_rate_are_equal(self):
        outputs = []
        for sign in (-1, 1):
            pca = FakePCA()
            steering = SteeringController(pca, config("pi.yaml"))
            steering.update(sign, .05)
            outputs.append(abs(pca.outputs[-1][1]-1786))
            steering.update(sign, 1)
            self.assertEqual(abs(pca.outputs[-1][1]-1786), 114)
        self.assertAlmostEqual(*outputs)

    def test_observed_25_degree_alignment_is_new_neutral(self):
        pca = FakePCA()
        steering = SteeringController(pca, config("pi.yaml"))
        steering.center()
        self.assertEqual(pca.outputs[-1], (0, 1786.0))
        steering.update(0.0, 0.1)
        self.assertEqual(pca.outputs[-1], (0, 1786.0))


if __name__ == "__main__":
    unittest.main()
