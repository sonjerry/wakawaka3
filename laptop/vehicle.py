import math
import time


G = 9.80665


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def approach(current, target, rate_per_s, dt):
    step = max(0.0, rate_per_s) * dt
    if current < target:
        return min(target, current + step)
    return max(target, current - step)


def first_order(current, target, tau_s, dt):
    if tau_s <= 1e-6:
        return target
    alpha = 1.0 - math.exp(-dt / tau_s)
    return current + (target - current) * alpha


def interp_map(points, x):
    if x <= points[0][0]:
        return float(points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / max(1e-9, x1 - x0)
            return lerp(float(y0), float(y1), t)
    return float(points[-1][1])


class VehicleModel:
    """Virtual 1.3T + 9-speed automatic road-vehicle model.

    The model intentionally separates:
      1) virtual road dynamics / engine / transmission
      2) physical RC motor PWM target

    Gear shifts only change virtual tractive torque. They do NOT directly
    punch a hole into ESC PWM, so road speed / motor command remains smooth
    through a shift like a normal passenger car.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.v = cfg["vehicle"]
        self.s = cfg["speed"]
        self.e = cfg["engine"]
        self.tc = cfg["torque_converter"]
        self.t = cfg["transmission"]
        self.eb = cfg["engine_braking"]
        self.m = cfg["esc_model"]

        self.selector = "P"
        self.gear = 1
        self.speed_mps = 0.0
        self.rpm = 0.0
        self.motor = 0.0
        self.effective_throttle = 0.0

        self.shifting = False
        self.shift_from = 1
        self.shift_to = 1
        self.shift_started = 0.0
        self.shift_end = 0.0
        self.last_shift_end = -999.0

        self.last_pedal = 0.0
        self.last_raw_pedal = 0.0
        self.sim_time = 0.0

    @property
    def speed_kph(self):
        return self.speed_mps * 3.6

    def shutdown(self):
        self.selector = "P"
        self.gear = 1
        self.speed_mps = 0.0
        self.rpm = 0.0
        self.motor = 0.0
        self.effective_throttle = 0.0
        self.shifting = False
        self.shift_from = 1
        self.shift_to = 1
        self.shift_started = 0.0
        self.shift_end = 0.0
        self.last_shift_end = -999.0
        self.last_pedal = 0.0
        self.last_raw_pedal = 0.0
        self.sim_time = 0.0

    def power_on(self):
        self.selector = "P"
        self.gear = 1
        self.speed_mps = 0.0
        self.rpm = float(self.e["idle_rpm"])
        self.motor = 0.0
        self.effective_throttle = 0.0
        self.shifting = False
        self.shift_from = 1
        self.shift_to = 1
        self.shift_started = 0.0
        self.shift_end = 0.0
        self.last_shift_end = -999.0
        self.last_pedal = 0.0
        self.last_raw_pedal = 0.0
        self.sim_time = 0.0

    def set_selector(self, selector):
        selector = str(selector).upper()
        if selector not in {"P", "R", "N", "D"}:
            return False

        speed = abs(self.speed_kph)

        # Mechanical-style interlocks. Brake-to-shift is enforced one layer
        # above this class in laptop/main.py.
        if selector == "P" and speed > 0.5:
            return False

        if selector in {"D", "R"} and self.selector in {"D", "R"}:
            if selector != self.selector and speed > 1.0:
                return False

        self.selector = selector
        if selector == "D":
            self.gear = max(1, min(9, self.gear))
        elif selector == "R":
            self.shifting = False
        return True

    def wheel_rpm(self):
        radius = float(self.v["wheel_radius_m"])
        return abs(self.speed_mps) / (2.0 * math.pi * radius) * 60.0

    def coupled_rpm(self, gear):
        gear = int(clamp(gear, 1, len(self.t["ratios"])))
        return (
            self.wheel_rpm()
            * float(self.t["ratios"][gear - 1])
            * float(self.t["final_drive"])
        )

    def reverse_coupled_rpm(self):
        return (
            self.wheel_rpm()
            * float(self.t["reverse_ratio"])
            * float(self.t["final_drive"])
        )

    def torque_nm(self, rpm):
        return interp_map(self.e["torque_curve_nm"], rpm)

    def _converter_lock_fraction(self, pedal):
        speed = abs(self.speed_kph)
        begin = float(self.tc["lock_begin_kph"])
        full = float(self.tc["lock_full_kph"])

        base = clamp((speed - begin) / max(1e-6, full - begin), 0.0, 1.0)

        # Heavy throttle unlocks the converter more readily.
        unlock = float(self.tc["unlock_throttle"])
        if pedal > unlock:
            base *= clamp(1.0 - (pedal - unlock) / max(1e-6, 1.0 - unlock), 0.12, 1.0)

        if self.gear <= 2 and speed < 25.0:
            base *= 0.55

        return smoothstep(base)

    def _drive_rpm_for_gear(self, gear, pedal):
        idle = float(self.e["idle_rpm"])
        coupled = self.coupled_rpm(gear)
        lock = self._converter_lock_fraction(pedal)

        stall = lerp(
            float(self.tc["stall_rpm_low"]),
            float(self.tc["stall_rpm_high"]),
            pedal ** 0.72,
        )

        # Converter slip matters only while coupled RPM is below stall region,
        # then fades out as lock-up comes in.
        slip_need = max(0.0, stall - coupled)
        slip = min(float(self.tc["slip_rpm_max"]), slip_need) * (1.0 - lock)

        target = max(idle, coupled + slip)

        # Gentle pedal at parking-lot speeds should not flare RPM.
        if abs(self.speed_kph) < 7.0 and pedal < 0.18:
            target = min(target, idle + 650.0)

        return clamp(target, idle, float(self.e["redline_rpm"]))

    def _engine_rpm_target(self, pedal, now):
        idle = float(self.e["idle_rpm"])

        if self.selector in {"P", "N"}:
            free_limit = float(self.e["free_rev_limit_rpm"])
            return idle + (free_limit - idle) * (pedal ** 1.25)

        if self.selector == "R":
            coupled = self.reverse_coupled_rpm()
            stall = lerp(
                float(self.tc["stall_rpm_low"]),
                float(self.tc["stall_rpm_high"]) * 0.82,
                pedal ** 0.75,
            )
            return clamp(max(idle, coupled, stall if pedal > 0.05 else idle), idle, 4800.0)

        if self.shifting:
            duration = max(1e-6, self.shift_end - self.shift_started)
            phase = smoothstep((now - self.shift_started) / duration)
            from_rpm = self._drive_rpm_for_gear(self.shift_from, pedal)
            to_rpm = self._drive_rpm_for_gear(self.shift_to, pedal)
            return lerp(from_rpm, to_rpm, phase)

        return self._drive_rpm_for_gear(self.gear, pedal)

    def _start_shift(self, target_gear, now):
        target_gear = int(clamp(target_gear, 1, len(self.t["ratios"])))
        if target_gear == self.gear or self.shifting:
            return False

        self.shifting = True
        self.shift_from = self.gear
        self.shift_to = target_gear
        self.shift_started = now
        self.shift_end = now + float(self.t["shift_duration_s"])
        return True

    def _finish_shift_if_due(self, now):
        if self.shifting and now >= self.shift_end:
            self.gear = self.shift_to
            self.shifting = False
            self.last_shift_end = now

    def _shift_dwell_ready(self, now):
        return (now - self.last_shift_end) >= float(self.t["min_shift_dwell_s"])

    def _predicted_rpm(self, gear):
        return max(float(self.e["idle_rpm"]), self.coupled_rpm(gear))

    def _kickdown_target(self, pedal):
        if self.gear <= 1:
            return self.gear

        min_rpm = float(self.t["kickdown_min_rpm"])
        max_rpm = float(self.t["kickdown_max_rpm"])
        best = self.gear

        # Pick the lowest safe gear that lands in a useful torque band.
        for candidate in range(1, self.gear):
            predicted = self._predicted_rpm(candidate)
            if min_rpm <= predicted <= max_rpm:
                best = candidate
                break

        return best

    def _transmission_logic(self, pedal, raw_pedal, brake, now):
        if self.selector != "D":
            return

        self._finish_shift_if_due(now)
        if self.shifting or not self._shift_dwell_ready(now):
            return

        ratios = self.t["ratios"]
        max_gear = len(ratios)
        pedal_delta = raw_pedal - self.last_raw_pedal

        # Approaching a stop, a real TCM preselects a launch gear rather than
        # stepping through every ratio after the vehicle has stopped.
        if abs(self.speed_kph) < 7.0 and brake > 0.08 and self.gear > 1:
            self._start_shift(1, now)
            return

        # Kickdown only on a meaningful demand increase or very high pedal.
        if (
            self.gear > 1
            and raw_pedal >= float(self.t["kickdown_throttle"])
            and (pedal_delta >= float(self.t["kickdown_delta"]) or raw_pedal >= 0.90)
        ):
            target = self._kickdown_target(pedal)
            if target < self.gear:
                self._start_shift(target, now)
                return

        current_rpm = self._predicted_rpm(self.gear)
        up_rpm = interp_map(self.t["upshift_rpm_map"], pedal)
        down_rpm = interp_map(self.t["downshift_rpm_map"], pedal)

        # Upshift: require RPM threshold, road-speed threshold, and a usable
        # post-shift RPM. 9th is deliberately a light-load cruising gear.
        if self.gear < max_gear:
            next_gear = self.gear + 1
            min_speed = float(self.t["min_speed_for_gear_kph"][next_gear - 1])
            next_rpm = self._predicted_rpm(next_gear)
            ninth_ok = not (
                next_gear == 9
                and pedal > float(self.t["ninth_max_throttle"])
            )

            if (
                current_rpm >= up_rpm
                and abs(self.speed_kph) >= min_speed
                and next_rpm >= float(self.t["min_post_upshift_rpm"])
                and ninth_ok
            ):
                self._start_shift(next_gear, now)
                return

        # Downshift with wide hysteresis. This eliminates 2↔3 / 3↔4 hunting.
        if self.gear > 1 and current_rpm <= down_rpm:
            candidate = self.gear - 1
            predicted = self._predicted_rpm(candidate)
            if predicted <= float(self.t["kickdown_max_rpm"]):
                self._start_shift(candidate, now)

    def _shift_torque_multiplier(self, pedal, now):
        if not self.shifting:
            return 1.0

        duration = max(1e-6, self.shift_end - self.shift_started)
        phase = clamp((now - self.shift_started) / duration, 0.0, 1.0)

        cut = lerp(
            float(self.t["shift_torque_cut_min"]),
            float(self.t["shift_torque_cut_max"]),
            pedal,
        )

        # Smooth bell-shaped torque reduction. No hard PWM drop.
        return 1.0 - cut * math.sin(math.pi * phase)

    def _engine_drive_force(self, pedal, now):
        direction = 1.0 if self.selector == "D" else (-1.0 if self.selector == "R" else 0.0)
        if direction == 0.0:
            return 0.0

        if self.selector == "D":
            ratio = float(self.t["ratios"][self.gear - 1])
        else:
            ratio = float(self.t["reverse_ratio"])

        # A progressive accelerator map like a normal road vehicle.
        demand = pedal ** 0.88
        engine_torque = self.torque_nm(self.rpm) * demand

        force = (
            engine_torque
            * ratio
            * float(self.t["final_drive"])
            * float(self.v["drivetrain_efficiency"])
            / float(self.v["wheel_radius_m"])
        )

        force = min(force, float(self.v["max_drive_force_n"]))
        force *= self._shift_torque_multiplier(pedal, now)
        return force * direction

    def _creep_force(self, pedal, brake):
        if self.selector not in {"D", "R"}:
            return 0.0
        if pedal > 0.03 or brake > 0.08:
            return 0.0

        direction = 1.0 if self.selector == "D" else -1.0
        signed_kph = self.speed_kph * direction
        target = float(self.v["creep_target_kph"])

        if signed_kph >= target:
            return 0.0

        fraction = clamp(1.0 - max(0.0, signed_kph) / target, 0.0, 1.0)
        return direction * float(self.v["creep_force_n"]) * fraction

    def _resistance_force(self, pedal):
        if abs(self.speed_mps) < 0.02:
            return 0.0

        direction = 1.0 if self.speed_mps > 0 else -1.0
        speed = abs(self.speed_mps)
        mass = float(self.v["mass_kg"])

        rolling = float(self.v["rolling_resistance_coeff"]) * mass * G
        aero = (
            0.5
            * float(self.v["air_density_kg_m3"])
            * float(self.v["drag_area_m2"])
            * speed * speed
        )

        force = rolling + aero

        if pedal < 0.025 and self.selector in {"D", "R"}:
            force += mass * float(self.eb["in_gear_extra_decel_mps2"])

        return -direction * force

    def _brake_force(self, brake):
        if brake <= 0.0 or abs(self.speed_mps) < 0.01:
            return 0.0

        mass = float(self.v["mass_kg"])
        # Soft first half, strong second half like a boosted road-car pedal.
        decel = float(self.v["max_brake_decel_mps2"]) * (brake ** 1.65)
        return -math.copysign(mass * decel, self.speed_mps)

    def _motor_target_from_speed(self):
        if self.selector in {"P", "N"}:
            return 0.0

        reference = float(self.s["motor_reference_kph"])
        speed = abs(self.speed_kph)

        if self.selector == "R":
            speed = min(speed, float(self.s["reverse_max_kph"]))
            reference = float(self.s["reverse_max_kph"])

        if speed < 0.05:
            return 0.0

        x = clamp(speed / max(1e-6, reference), 0.0, 1.0)
        minimum = float(self.m["min_effective_drive"])
        mapped = minimum + (1.0 - minimum) * (x ** float(self.m["speed_curve_exponent"]))

        return mapped if self.selector == "D" else -mapped

    def update(self, throttle, brake, steering, dt):
        dt = clamp(float(dt), 0.0001, 0.05)
        self.sim_time += dt
        now = self.sim_time
        pedal = clamp(float(throttle), 0.0, 1.0)
        brake = clamp(float(brake), 0.0, 1.0)

        # Engine/throttle response is deliberately filtered; keyboard steps or
        # pedal sensor noise cannot become torque spikes.
        tau = (
            float(self.e["throttle_response_up_s"])
            if pedal > self.effective_throttle
            else float(self.e["throttle_response_down_s"])
        )
        self.effective_throttle = first_order(
            self.effective_throttle,
            pedal,
            tau,
            dt,
        )

        self._transmission_logic(self.effective_throttle, pedal, brake, now)

        rpm_target = self._engine_rpm_target(self.effective_throttle, now)
        rpm_rate = (
            float(self.e["rpm_response_up_per_s"])
            if rpm_target >= self.rpm
            else float(self.e["rpm_response_down_per_s"])
        )
        self.rpm = approach(self.rpm, rpm_target, rpm_rate, dt)

        drive_force = self._engine_drive_force(self.effective_throttle, now)
        drive_force += self._creep_force(self.effective_throttle, brake)
        resist_force = self._resistance_force(self.effective_throttle)
        brake_force = self._brake_force(brake)

        mass = float(self.v["mass_kg"])
        acceleration = (drive_force + resist_force + brake_force) / mass

        old_speed = self.speed_mps
        new_speed = old_speed + acceleration * dt

        # Do not let braking / resistance numerically push through zero.
        if old_speed > 0.0 and new_speed < 0.0 and drive_force <= 0.0:
            new_speed = 0.0
        if old_speed < 0.0 and new_speed > 0.0 and drive_force >= 0.0:
            new_speed = 0.0

        if self.selector == "D":
            new_speed = max(0.0, new_speed)
        elif self.selector == "R":
            reverse_limit = float(self.s["reverse_max_kph"]) / 3.6
            new_speed = clamp(new_speed, -reverse_limit, 0.0)

        if self.selector == "P":
            new_speed = 0.0

        virtual_max = float(self.s.get("virtual_max_kph", 185.0)) / 3.6
        new_speed = clamp(new_speed, -float(self.s["reverse_max_kph"]) / 3.6, virtual_max)

        # Brake hold at walking speed.
        if brake > 0.12 and abs(new_speed) < 0.18:
            new_speed = 0.0

        self.speed_mps = new_speed

        motor_target = self._motor_target_from_speed()
        motor_rate = (
            float(self.m["output_slew_up_per_s"])
            if abs(motor_target) > abs(self.motor)
            else float(self.m["output_slew_down_per_s"])
        )
        self.motor = approach(self.motor, motor_target, motor_rate, dt)
        if abs(self.motor) < 0.002:
            self.motor = 0.0

        self.last_pedal = self.effective_throttle
        self.last_raw_pedal = pedal
        self._finish_shift_if_due(now)

        return self.snapshot(pedal, brake, steering)

    def snapshot(self, throttle, brake, steering):
        shift_progress = 0.0
        if self.shifting:
            duration = max(1e-6, self.shift_end - self.shift_started)
            shift_progress = clamp(
                (self.sim_time - self.shift_started) / duration,
                0.0,
                1.0,
            )

        return {
            "selector": self.selector,
            "gear": self.gear if self.selector == "D" else self.selector,
            "display_gear": self.shift_to if self.shifting and self.selector == "D" else (
                self.gear if self.selector == "D" else self.selector
            ),
            "speed_kph": round(abs(self.speed_kph), 2),
            "signed_speed_kph": round(self.speed_kph, 2),
            "rpm": round(self.rpm),
            "throttle": round(float(throttle), 4),
            "effective_throttle": round(self.effective_throttle, 4),
            "brake": round(float(brake), 4),
            "steering": round(float(steering), 4),
            "motor_output": round(self.motor, 4),
            "shifting": self.shifting,
            "shift_from": self.shift_from if self.shifting else None,
            "shift_to": self.shift_to if self.shifting else None,
            "shift_progress": round(shift_progress, 4),
        }
