import math
import time


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def approach(current, target, rate, dt):
    step = rate * dt
    if current < target:
        return min(target, current + step)
    return max(target, current - step)


class VehicleModel:
    def __init__(self, cfg):
        self.cfg = cfg
        self.v = cfg["vehicle"]
        self.s = cfg["speed"]
        self.e = cfg["engine"]
        self.t = cfg["transmission"]
        self.m = cfg["esc_model"]

        self.selector = "P"
        self.gear = 1
        self.speed_mps = 0.0
        self.rpm = 0.0
        self.motor = 0.0
        self.shifting = False
        self.pending_gear = 1
        self.shift_end = 0.0
        self.last_shift = -999.0

    @property
    def speed_kph(self):
        return self.speed_mps * 3.6

    def shutdown(self):
        self.selector = "P"
        self.gear = 1
        self.speed_mps = 0.0
        self.rpm = 0.0
        self.motor = 0.0
        self.shifting = False
        self.pending_gear = 1
        self.shift_end = 0.0
        self.last_shift = -999.0

    def power_on(self):
        self.selector = "P"
        self.gear = 1
        self.speed_mps = 0.0
        self.rpm = float(self.e["idle_rpm"])
        self.motor = 0.0
        self.shifting = False
        self.pending_gear = 1
        self.shift_end = 0.0
        self.last_shift = -999.0

    def set_selector(self, selector):
        selector = selector.upper()
        if selector not in {"P", "R", "N", "D"}:
            return False

        # D <-> R is only allowed when effectively stopped.
        if (
            selector in {"D", "R"}
            and self.selector in {"D", "R"}
            and selector != self.selector
            and abs(self.speed_kph) > 1.0
        ):
            return False

        if selector == "P" and abs(self.speed_kph) > 0.5:
            return False

        self.selector = selector
        if selector == "D":
            self.gear = max(1, min(len(self.t["ratios"]), self.gear))
        return True

    def wheel_rpm(self):
        radius = float(self.v["wheel_radius_m"])
        return abs(self.speed_mps) / (2.0 * math.pi * radius) * 60.0

    def rpm_for_gear(self, gear):
        return max(
            float(self.e["idle_rpm"]),
            self.wheel_rpm()
            * float(self.t["ratios"][gear - 1])
            * float(self.t["final_drive"]),
        )

    def torque_factor(self, rpm):
        points = self.e["torque_curve"]
        if rpm <= points[0][0]:
            return float(points[0][1])

        for (r0, t0), (r1, t1) in zip(points, points[1:]):
            if r0 <= rpm <= r1:
                return lerp(float(t0), float(t1), (rpm - r0) / (r1 - r0))
        return float(points[-1][1])

    def start_shift(self, gear, now):
        gear = int(clamp(gear, 1, len(self.t["ratios"])))
        if gear == self.gear or self.shifting:
            return
        if now - self.last_shift < float(self.t["min_shift_interval_s"]):
            return

        self.shifting = True
        self.pending_gear = gear
        self.shift_end = now + float(self.t["shift_duration_s"])
        self.last_shift = now

    def transmission(self, throttle, now):
        if self.selector != "D":
            return

        rpm = self.rpm_for_gear(self.gear)
        if self.shifting:
            if now >= self.shift_end:
                self.gear = self.pending_gear
                self.shifting = False
            return

        if throttle >= float(self.t["kickdown_throttle"]) and self.gear > 1:
            target = float(self.t["kickdown_target_rpm"])
            for gear in range(self.gear - 1, 0, -1):
                candidate = self.rpm_for_gear(gear)
                if target <= candidate <= float(self.e["redline_rpm"]):
                    self.start_shift(gear, now)
                    return

        if rpm >= float(self.t["upshift_rpm"]) and self.gear < len(self.t["ratios"]):
            self.start_shift(self.gear + 1, now)
        elif rpm <= float(self.t["downshift_rpm"]) and self.gear > 1:
            self.start_shift(self.gear - 1, now)

    def engine_target(self, throttle):
        idle = float(self.e["idle_rpm"])
        redline = float(self.e["redline_rpm"])

        if self.selector in {"P", "N"}:
            return idle + throttle * (redline - idle) * 0.72

        if self.selector == "R":
            gear_ratio = float(self.t["ratios"][0]) * 0.85
        else:
            gear_ratio = float(self.t["ratios"][self.gear - 1])

        rpm = self.wheel_rpm() * gear_ratio * float(self.t["final_drive"])
        if abs(self.speed_kph) < 4.0:
            # A small launch-slip term mimics torque-converter/clutch slip.
            rpm += throttle * 1400.0
        return clamp(rpm, idle, redline)

    def update(self, throttle, brake, steering, dt):
        now = time.monotonic()
        throttle = clamp(float(throttle), 0.0, 1.0)
        brake = clamp(float(brake), 0.0, 1.0)

        self.transmission(throttle, now)
        self.rpm = approach(
            self.rpm,
            self.engine_target(throttle),
            float(self.e["inertia_response_per_s"]) * 900.0,
            dt,
        )

        direction = 1 if self.selector == "D" else (-1 if self.selector == "R" else 0)
        if self.selector == "D":
            ratio = float(self.t["ratios"][self.gear - 1])
        elif self.selector == "R":
            ratio = float(self.t["ratios"][0]) * 0.80
        else:
            ratio = 0.0

        drive_force = 0.0
        if direction and throttle > 0.0:
            torque = (
                float(self.e["max_virtual_torque_nm"])
                * self.torque_factor(self.rpm)
                * throttle
            )
            drive_force = (
                torque
                * ratio
                * float(self.t["final_drive"])
                * float(self.v["drivetrain_efficiency"])
                / float(self.v["wheel_radius_m"])
                * direction
            )

        if self.shifting:
            drive_force *= 1.0 - float(self.t["torque_cut_fraction"])

        resistance = 0.0
        if abs(self.speed_mps) > 0.01:
            sign = 1 if self.speed_mps > 0 else -1
            resistance = -(
                float(self.v["rolling_force_n"])
                + float(self.v["aero_drag_coeff"]) * self.speed_mps**2
            ) * sign
            if throttle < 0.03 and self.selector in {"D", "R"}:
                resistance -= float(self.v["engine_brake_force_n"]) * sign

        brake_force = 0.0
        if abs(self.speed_mps) > 0.01:
            brake_force = -math.copysign(
                brake * float(self.v["max_brake_force_n"]),
                self.speed_mps,
            )

        old_speed = self.speed_mps
        new_speed = old_speed + (
            drive_force + resistance + brake_force
        ) / float(self.v["mass_kg"]) * dt

        if old_speed > 0 and new_speed < 0 and drive_force <= 0:
            new_speed = 0.0
        if old_speed < 0 and new_speed > 0 and drive_force >= 0:
            new_speed = 0.0
        if self.selector == "D" and new_speed < 0:
            new_speed = 0.0
        if self.selector == "R" and new_speed > 0:
            new_speed = 0.0

        max_forward = float(self.s["max_forward_kph"]) / 3.6
        max_reverse = float(self.s["max_reverse_kph"]) / 3.6
        self.speed_mps = clamp(new_speed, -max_reverse, max_forward)

        if self.selector == "P" and abs(self.speed_mps) < 0.25:
            self.speed_mps = 0.0

        normalised_speed = self.speed_mps / (
            max_forward if self.speed_mps >= 0 else max_reverse
        )
        if abs(normalised_speed) > 0.001:
            minimum = float(self.m["min_effective_drive"])
            target_motor = math.copysign(
                minimum + (1.0 - minimum) * min(1.0, abs(normalised_speed)),
                normalised_speed,
            )
        else:
            target_motor = 0.0

        if self.selector in {"P", "N"}:
            target_motor = 0.0
        if self.shifting:
            target_motor *= 1.0 - float(self.m["shift_output_drop"])

        rate = float(
            self.m["output_slew_up_per_s"]
            if abs(target_motor) > abs(self.motor)
            else self.m["output_slew_down_per_s"]
        )
        self.motor = approach(self.motor, target_motor, rate, dt)

        return self.snapshot(throttle, brake, steering)

    def snapshot(self, throttle, brake, steering):
        return {
            "selector": self.selector,
            "gear": self.gear if self.selector == "D" else self.selector,
            "speed_kph": round(abs(self.speed_kph), 2),
            "signed_speed_kph": round(self.speed_kph, 2),
            "rpm": round(self.rpm),
            "throttle": round(throttle, 4),
            "brake": round(brake, 4),
            "steering": round(steering, 4),
            "motor_output": round(self.motor, 4),
            "shifting": self.shifting,
        }
