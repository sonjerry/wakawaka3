import math
import time
from smbus2 import SMBus


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def approach(current, target, rate_per_s, dt):
    step = max(0.0, rate_per_s) * dt
    if current < target:
        return min(target, current + step)
    return max(target, current - step)


class PCA9685:
    MODE1 = 0x00
    MODE2 = 0x01
    PRESCALE = 0xFE
    LED0_ON_L = 0x06
    RESTART = 0x80
    SLEEP = 0x10
    AI = 0x20
    OUTDRV = 0x04

    def __init__(self, cfg):
        pcfg = cfg["pca9685"]
        self.address = int(pcfg["address"])
        self.frequency = float(pcfg["frequency_hz"])
        self.bus_num = int(pcfg.get("i2c_bus", 1))
        self.bus = SMBus(self.bus_num)
        self._write(self.MODE1, self.AI)
        self._write(self.MODE2, self.OUTDRV)
        time.sleep(0.01)
        self.set_frequency(self.frequency)

    def _write(self, reg, value):
        self.bus.write_byte_data(self.address, reg, value & 0xFF)

    def _read(self, reg):
        return self.bus.read_byte_data(self.address, reg)

    def set_frequency(self, hz):
        hz = float(hz)
        prescale = int(round(25_000_000.0 / (4096.0 * hz) - 1.0))
        prescale = max(3, min(255, prescale))
        old_mode = self._read(self.MODE1)
        self._write(self.MODE1, (old_mode & 0x7F) | self.SLEEP)
        self._write(self.PRESCALE, prescale)
        self._write(self.MODE1, old_mode)
        time.sleep(0.005)
        self._write(self.MODE1, old_mode | self.RESTART | self.AI)
        self.frequency = hz

    def set_pwm(self, channel, on_count, off_count):
        channel = int(channel)
        if not 0 <= channel <= 15:
            raise ValueError("PCA9685 channel must be 0..15")
        reg = self.LED0_ON_L + 4 * channel
        on_count &= 0x0FFF
        off_count &= 0x0FFF
        self.bus.write_i2c_block_data(self.address, reg, [
            on_count & 0xFF,
            (on_count >> 8) & 0x0F,
            off_count & 0xFF,
            (off_count >> 8) & 0x0F,
        ])

    def pulse_us(self, channel, pulse_us):
        period_us = 1_000_000.0 / self.frequency
        pulse_us = clamp(float(pulse_us), 0.0, period_us)
        counts = int(round((pulse_us / period_us) * 4096.0))
        self.set_pwm(channel, 0, max(0, min(4095, counts)))

    def all_off(self):
        for ch in range(16):
            self.set_pwm(ch, 0, 0)

    def deinit(self):
        try:
            self.all_off()
        finally:
            self.bus.close()


class SteeringController:
    def __init__(self, pca, cfg):
        self.pca = pca
        self.cfg = cfg["steering"]
        self.value = 0.0

    @property
    def center_pulse_us(self):
        return float(self.cfg["center_us"]) + float(self.cfg.get("center_trim_us", 0.0))

    def update(self, target, dt):
        if self.cfg.get("invert"):
            target = -target
        target = clamp(float(target), -1.0, 1.0)
        self.value = approach(self.value, target, float(self.cfg["max_slew_per_s"]), dt)

        center = self.center_pulse_us
        if self.value < 0:
            pulse = center + (-self.value) * (float(self.cfg["left_us"]) - center)
        else:
            pulse = center + self.value * (float(self.cfg["right_us"]) - center)
        self.pca.pulse_us(self.cfg["channel"], pulse)

    def center(self):
        self.value = 0.0
        self.pca.pulse_us(self.cfg["channel"], self.center_pulse_us)


class ESCController:
    """Receiver-style PPM/PWM ESC interface.

    The generic 30A brushed ESC family expects the throttle signal to be at
    the middle of its range at startup. We therefore continuously output
    neutral for startup_neutral_s before accepting any drive command.

    No undocumented full-throttle endpoint calibration is performed.
    """

    def __init__(self, pca, cfg):
        self.pca = pca
        self.cfg = cfg["esc"]
        self.value = 0.0
        self.drive_enabled = False
        self.ready = False
        self.started_at = time.monotonic()
        self.direction_block_until = 0.0
        self.selector = "P"
        self.last_pulse_us = float(self.cfg["neutral_us"])
        self.last_mode = "ARM_NEUTRAL"
        self.write_neutral()

    @property
    def armed(self):
        # Kept for backwards compatibility with laptop telemetry.
        return self.ready

    def _write_pulse(self, pulse_us, mode):
        neutral = float(self.cfg["neutral_us"])
        # Final direction boundary, including residual output during shifts.
        if self.selector == "D":
            pulse_us = clamp(pulse_us, neutral, float(self.cfg["forward_max_us"]))
        elif self.selector == "R":
            pulse_us = clamp(pulse_us, float(self.cfg["reverse_max_us"]), neutral)
        else:
            pulse_us = neutral
        self.last_pulse_us = float(pulse_us)
        self.last_mode = mode
        self.pca.pulse_us(self.cfg["channel"], self.last_pulse_us)

    def write_neutral(self):
        self._write_pulse(float(self.cfg["neutral_us"]), "NEUTRAL")

    def service_startup(self):
        if self.ready:
            return
        self.write_neutral()
        if time.monotonic() - self.started_at >= float(self.cfg.get("startup_neutral_s", 3.0)):
            self.ready = True
            self.last_mode = "READY"

    def set_drive_enabled(self, enabled):
        self.drive_enabled = bool(enabled)
        if not self.drive_enabled:
            self.value = 0.0
            self.write_neutral()

    def safe(self):
        # Failsafe disables motion but does not destroy the already-completed
        # ESC startup neutral handshake.
        self.set_drive_enabled(False)
        self.direction_block_until = 0.0

    def _pulse_for_drive(self, value):
        value = clamp(float(value), -1.0, 1.0)
        neutral = float(self.cfg["neutral_us"])
        if abs(value) <= float(self.cfg["output_deadband"]):
            return neutral
        # Direct calibration anchors: zero=neutral, 7%=measured creep,
        # 100%=endpoint. Sub-creep output allows smooth coast/brake decay.
        magnitude = abs(value)
        logical_creep = float(self.cfg["creep_command"])
        direction = "forward" if value > 0 else "reverse"
        creep = float(self.cfg[f"{direction}_creep_us"])
        endpoint = float(self.cfg[f"{direction}_max_us"])
        if magnitude <= logical_creep:
            return neutral + (creep - neutral) * magnitude / logical_creep
        return creep + (endpoint - creep) * (magnitude - logical_creep) / (1.0 - logical_creep)

    def update(self, target, brake, dt, selector="P"):
        self.service_startup()

        try:
            target, brake, dt = float(target), float(brake), float(dt)
            if not all(math.isfinite(v) for v in (target, brake, dt)):
                raise ValueError("non-finite control")
        except (TypeError, ValueError):
            self.value = 0.0
            self.write_neutral()
            return
        now = time.monotonic()
        if selector != self.selector:
            self.selector = selector if selector in {"P", "N", "D", "R"} else "P"
            self.value = 0.0
            self.direction_block_until = now + float(self.cfg["direction_neutral_hold_s"])
            self.write_neutral()

        if not self.ready or not self.drive_enabled or self.selector not in {"D", "R"}:
            self.value = 0.0
            self.write_neutral()
            return

        brake = clamp(float(brake), 0.0, 1.0)
        if brake > float(self.cfg["brake_deadband"]):
            # No-brake ESC: reduce pulse itself, never command opposing torque.
            amount = (brake - self.cfg["brake_deadband"]) / (1.0 - self.cfg["brake_deadband"])
            rate = self.cfg["brake_decay_min_us_per_s"] + (
                self.cfg["brake_decay_max_us_per_s"] - self.cfg["brake_decay_min_us_per_s"]
            ) * amount ** self.cfg["brake_decay_exponent"]
            pulse = approach(self.last_pulse_us, float(self.cfg["neutral_us"]), rate, clamp(dt, 0.0, 0.05))
            self.value = self._drive_for_pulse(pulse)
            self._write_pulse(pulse, "BRAKE_DECAY" if self.value else "NEUTRAL")
            return

        target = clamp(float(target), -1.0, 1.0)
        if (self.selector == "D" and target < 0) or (self.selector == "R" and target > 0):
            target = 0.0
            self.value = 0.0
        if now < self.direction_block_until:
            target = 0.0

        if target == 0.0 and now < self.direction_block_until:
            self.write_neutral()
            return
        if (self.selector == "D" and self.last_pulse_us < self.cfg["neutral_us"]) or (self.selector == "R" and self.last_pulse_us > self.cfg["neutral_us"]):
            self.write_neutral()
        pulse = approach(self.last_pulse_us, self._pulse_for_drive(target), float(self.cfg["drive_slew_us_per_s"]), clamp(dt, 0.0, 0.05))
        self.value = self._drive_for_pulse(pulse)
        self._write_pulse(pulse, "DRIVE" if self.value else "NEUTRAL")

    def _drive_for_pulse(self, pulse):
        neutral = float(self.cfg["neutral_us"])
        if pulse == neutral:
            return 0.0
        direction = "forward" if pulse > neutral else "reverse"
        distance = abs(pulse - neutral)
        creep = abs(float(self.cfg[f"{direction}_creep_us"]) - neutral)
        end = abs(float(self.cfg[f"{direction}_max_us"]) - neutral)
        command = float(self.cfg["creep_command"])
        magnitude = command * distance / creep if distance <= creep else command + (1-command) * (distance-creep)/(end-creep)
        return math.copysign(clamp(magnitude, 0.0, 1.0), pulse-neutral)


class Hardware:
    def __init__(self, cfg):
        self.pca = PCA9685(cfg)
        self.steering = SteeringController(self.pca, cfg)
        self.esc = ESCController(self.pca, cfg)

    def safe(self, center_steering=True):
        self.esc.safe()
        if center_steering:
            self.steering.center()

    def deinit(self):
        try:
            self.safe(True)
        finally:
            self.pca.deinit()
