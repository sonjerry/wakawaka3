import time
from smbus2 import SMBus


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def approach(current, target, rate_per_s, dt):
    step = rate_per_s * dt
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
        # PCA9685 oscillator nominally 25 MHz.
        prescale = int(round(25_000_000.0 / (4096.0 * hz) - 1.0))
        prescale = max(3, min(255, prescale))

        old_mode = self._read(self.MODE1)
        sleep_mode = (old_mode & 0x7F) | self.SLEEP

        self._write(self.MODE1, sleep_mode)
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

        data = [
            on_count & 0xFF,
            (on_count >> 8) & 0x0F,
            off_count & 0xFF,
            (off_count >> 8) & 0x0F,
        ]
        self.bus.write_i2c_block_data(self.address, reg, data)

    def pulse_us(self, channel, pulse_us):
        period_us = 1_000_000.0 / self.frequency
        pulse_us = clamp(float(pulse_us), 0.0, period_us)
        counts = int(round((pulse_us / period_us) * 4096.0))
        counts = max(0, min(4095, counts))
        self.set_pwm(channel, 0, counts)

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

    def update(self, target, dt):
        if self.cfg.get("invert"):
            target = -target

        target = clamp(float(target), -1.0, 1.0)
        self.value = approach(
            self.value,
            target,
            float(self.cfg["max_slew_per_s"]),
            dt,
        )

        center = float(self.cfg["center_us"])
        if self.value < 0:
            pulse = center + (-self.value) * (float(self.cfg["left_us"]) - center)
        else:
            pulse = center + self.value * (float(self.cfg["right_us"]) - center)

        self.pca.pulse_us(self.cfg["channel"], pulse)

    def center(self):
        self.value = 0.0
        self.pca.pulse_us(self.cfg["channel"], float(self.cfg["center_us"]))


class ESCController:
    def __init__(self, pca, cfg):
        self.pca = pca
        self.cfg = cfg["esc"]

        self.armed = False
        self.arm_requested_at = None
        self.value = 0.0
        self.direction_block_until = 0.0

        self.write_neutral()

    def write_neutral(self):
        self.pca.pulse_us(
            self.cfg["channel"],
            float(self.cfg["neutral_us"]),
        )

    def disarm(self):
        self.armed = False
        self.arm_requested_at = None
        self.value = 0.0
        self.direction_block_until = 0.0
        self.write_neutral()

    def request_arm(self, requested, can_start=True):
        now = time.monotonic()

        if not requested:
            self.disarm()
            return

        if self.armed:
            return

        if not can_start:
            self.arm_requested_at = None
            self.write_neutral()
            return

        if self.arm_requested_at is None:
            self.arm_requested_at = now
            self.write_neutral()
            return

        if now - self.arm_requested_at >= float(self.cfg["arm_hold_s"]):
            self.armed = True

    def _pulse_for_value(self, value):
        value = clamp(float(value), -1.0, 1.0)
        neutral = float(self.cfg["neutral_us"])

        if abs(value) <= float(self.cfg["output_deadband"]):
            return neutral

        if value > 0:
            lo = float(self.cfg["forward_min_us"])
            hi = float(self.cfg["forward_max_us"])
            return lo + value * (hi - lo)

        mag = abs(value)
        lo = float(self.cfg["reverse_min_us"])
        hi = float(self.cfg["reverse_max_us"])
        return lo + mag * (hi - lo)

    def update(self, target, dt):
        now = time.monotonic()

        if not self.armed:
            self.value = 0.0
            self.write_neutral()
            return

        target = clamp(float(target), -1.0, 1.0)

        target_dir = 1 if target > 0.03 else (-1 if target < -0.03 else 0)
        current_dir = 1 if self.value > 0.03 else (-1 if self.value < -0.03 else 0)

        # A direction change must pass through neutral.
        if (
            current_dir != 0
            and target_dir != 0
            and current_dir != target_dir
        ):
            target = 0.0
            self.direction_block_until = max(
                self.direction_block_until,
                now + float(self.cfg["direction_neutral_hold_s"]),
            )

        if now < self.direction_block_until:
            target = 0.0

        self.value = approach(
            self.value,
            target,
            float(self.cfg["output_slew_per_s"]),
            dt,
        )

        if abs(self.value) < 0.01:
            self.value = 0.0

        self.pca.pulse_us(
            self.cfg["channel"],
            self._pulse_for_value(self.value),
        )


class Hardware:
    def __init__(self, cfg):
        self.pca = PCA9685(cfg)
        self.steering = SteeringController(self.pca, cfg)
        self.esc = ESCController(self.pca, cfg)

    def safe(self, center_steering=True):
        self.esc.disarm()
        if center_steering:
            self.steering.center()

    def deinit(self):
        try:
            self.safe(True)
        finally:
            self.pca.deinit()
