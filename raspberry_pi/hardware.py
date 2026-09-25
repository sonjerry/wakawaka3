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
        self.last_pulse_us = float(self.cfg["neutral_us"])
        self.last_mode = "ARM_NEUTRAL"
        self.write_neutral()

    @property
    def armed(self):
        # Kept for backwards compatibility with laptop telemetry.
        return self.ready

    def _write_pulse(self, pulse_us, mode):
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
        if self.cfg.get("invert_direction", False):
            value = -value
        neutral = float(self.cfg["neutral_us"])
        if abs(value) <= float(self.cfg["output_deadband"]):
            return neutral
        # The dashboard's 7% creep command must reproduce the pulse that the
        # previous version sent at 45% physical ESC output. Keep display and
        # receiver-signal percentages separate.
        magnitude = abs(value)
        logical_creep = float(self.cfg["creep_command"])
        physical_creep = float(self.cfg["creep_signal_fraction"])
        calibrated = physical_creep + max(0.0, magnitude - logical_creep) * (1.0 - physical_creep) / (1.0 - logical_creep)
        calibrated = clamp(calibrated, physical_creep, 1.0)
        if value > 0:
            lo = float(self.cfg["forward_min_us"])
            hi = float(self.cfg["forward_max_us"])
            return lo + calibrated * (hi - lo)
        lo = float(self.cfg["reverse_min_us"])
        hi = float(self.cfg["reverse_max_us"])
        return lo + calibrated * (hi - lo)

    def update(self, target, brake, dt):
        self.service_startup()

        if not self.ready or not self.drive_enabled:
            self.value = 0.0
            self.write_neutral()
            return

        brake = clamp(float(brake), 0.0, 1.0)
        if brake >= float(self.cfg.get("brake_deadband", 0.04)):
            # Virtual speed is not a physical wheel-speed measurement. Sending
            # reverse PWM here can drive the car backward instead of braking.
            self.value = 0.0
            self._write_pulse(float(self.cfg["neutral_us"]), "BRAKE_NEUTRAL")
            return

        target = clamp(float(target), -1.0, 1.0)
        target_dir = 1 if target > 0.03 else (-1 if target < -0.03 else 0)
        current_dir = 1 if self.value > 0.03 else (-1 if self.value < -0.03 else 0)
        now = time.monotonic()

        if current_dir and target_dir and current_dir != target_dir:
            target = 0.0
            self.direction_block_until = max(
                self.direction_block_until,
                now + float(self.cfg["direction_neutral_hold_s"]),
            )
        if now < self.direction_block_until:
            target = 0.0

        self.value = approach(self.value, target, float(self.cfg["output_slew_per_s"]), dt)
        if abs(self.value) < 0.01:
            self.value = 0.0
        self._write_pulse(self._pulse_for_drive(self.value), "DRIVE" if self.value else "NEUTRAL")


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
