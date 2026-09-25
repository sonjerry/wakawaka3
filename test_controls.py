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
    def test_brake_never_sends_reverse_pulse_in_drive(self):
        pca = FakePCA()
        esc = ESCController(pca, config("pi.yaml"))
        esc.ready = True
        esc.set_drive_enabled(True)
        esc.update(0.6, 0.0, 0.1)
        self.assertGreater(pca.outputs[-1][1], 1500)
        for brake in (0.04, 0.2, 0.5, 1.0):
            esc.update(0.6, brake, 0.1)
            self.assertEqual(pca.outputs[-1], (1, 1500))
            self.assertEqual(esc.last_mode, "BRAKE_NEUTRAL")
            esc.update(-0.6, brake, 0.1)
            self.assertEqual(pca.outputs[-1], (1, 1500))

    def test_creep_displays_seven_percent_and_brake_cuts_it(self):
        car = VehicleModel(config("vehicle.yaml"))
        car.power_on()
        self.assertTrue(car.set_selector("D"))
        for _ in range(30):
            state = car.update(0.0, 0.0, 0.0, 0.05)
        self.assertGreater(state["speed_kph"], 0)
        self.assertGreaterEqual(state["motor_output"], 0.07)
        self.assertLess(state["motor_output"], 0.10)
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

    def test_seven_percent_creep_reproduces_old_45_percent_pulse(self):
        esc = ESCController(FakePCA(), config("pi.yaml"))
        self.assertEqual(esc._pulse_for_drive(0.07), 1747.0)
        self.assertEqual(esc._pulse_for_drive(-0.07), 1253.0)
        self.assertEqual(esc._pulse_for_drive(0.0), 1500.0)
        self.assertEqual(esc._pulse_for_drive(1.0), 2000.0)

    def test_observed_25_degree_alignment_is_new_neutral(self):
        pca = FakePCA()
        steering = SteeringController(pca, config("pi.yaml"))
        steering.center()
        self.assertEqual(pca.outputs[-1], (0, 1786.0))
        steering.update(0.0, 0.1)
        self.assertEqual(pca.outputs[-1], (0, 1786.0))


if __name__ == "__main__":
    unittest.main()
