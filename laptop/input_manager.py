import math, time
try:
    import pygame
except Exception:
    pygame = None

def clamp(v, lo, hi): return max(lo, min(hi, v))

def approach(cur, target, rate, dt):
    d = rate * dt
    return min(target, cur + d) if cur < target else max(target, cur - d)

class InputManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.device = None
        self.device_name = None
        self.mode = "keyboard"
        self.raw_axes = {}
        self.keys = {k: False for k in "wasd"}
        self.k_throttle = self.k_brake = self.k_steer = 0.0
        self.last_scan = 0.0
        if pygame:
            try:
                pygame.init()
                pygame.joystick.init()
            except Exception:
                pass

    def set_keyboard(self, state):
        for k in self.keys:
            self.keys[k] = bool(state.get(k, False))

    def _scan(self):
        now = time.monotonic()
        if now - self.last_scan < 2:
            return
        self.last_scan = now
        if not pygame:
            self.device = None
            self.mode = "keyboard"
            return
        try:
            pygame.joystick.quit()
            pygame.joystick.init()
            best = None
            tokens = [s.lower() for s in self.cfg.get("device_name_contains", [])]
            for i in range(pygame.joystick.get_count()):
                j = pygame.joystick.Joystick(i)
                j.init()
                if best is None:
                    best = j
                if any(t in j.get_name().lower() for t in tokens):
                    best = j
                    break
            self.device = best
            self.device_name = best.get_name() if best else None
            self.mode = "wheel" if best else "keyboard"
        except Exception:
            self.device = None
            self.device_name = None
            self.mode = "keyboard"

    def _pedal(self, raw, invert):
        v = (raw + 1.0) * 0.5
        if invert:
            v = 1.0 - v
        dz = float(self.cfg["deadzone"]["pedal"])
        return 0.0 if v < dz else clamp((v-dz)/(1-dz), 0, 1)

    def _wheel(self):
        try:
            pygame.event.pump()
            self.raw_axes = {
                str(i): round(self.device.get_axis(i), 4)
                for i in range(self.device.get_numaxes())
            }
            a = self.cfg["axes"]
            inv = self.cfg["invert"]
            s = self.device.get_axis(int(a["steering"]))
            if inv.get("steering"): s = -s
            dz = float(self.cfg["deadzone"]["steering"])
            s = 0.0 if abs(s) < dz else math.copysign((abs(s)-dz)/(1-dz), s)
            return {
                "steering": clamp(s, -1, 1),
                "throttle": self._pedal(self.device.get_axis(int(a["throttle"])), bool(inv.get("throttle"))),
                "brake": self._pedal(self.device.get_axis(int(a["brake"])), bool(inv.get("brake"))),
            }
        except Exception:
            self.device = None
            self.device_name = None
            self.mode = "keyboard"
            return None

    def _keyboard(self, dt, signed_speed_kph=0.0):
        c = self.cfg["keyboard"]
        tt, bt = (1.0 if self.keys["w"] else 0.0), (1.0 if self.keys["s"] else 0.0)
        self.k_throttle = approach(self.k_throttle, tt, c["throttle_rise_per_s"] if tt else c["throttle_fall_per_s"], dt)
        self.k_brake = approach(self.k_brake, bt, c["brake_rise_per_s"] if bt else c["brake_fall_per_s"], dt)
        st = -1.0 if self.keys["a"] and not self.keys["d"] else (1.0 if self.keys["d"] and not self.keys["a"] else 0.0)
        if st:
            self.k_steer = approach(self.k_steer, st, c["steering_rise_per_s"], dt)
        elif signed_speed_kph > float(c.get("steering_self_center_start_kph", 0.5)):
            full = float(c.get("steering_self_center_full_kph", 20.0))
            rate = float(c["steering_return_per_s"]) * clamp(signed_speed_kph / max(0.1, full), 0.0, 1.0)
            self.k_steer = approach(self.k_steer, 0.0, rate, dt)
        return {"steering": self.k_steer, "throttle": self.k_throttle, "brake": self.k_brake}

    def update(self, dt, signed_speed_kph=0.0):
        self._scan()
        if self.device:
            v = self._wheel()
            if v:
                return {**v, "mode": "wheel", "device": self.device_name, "raw_axes": self.raw_axes}
        return {**self._keyboard(dt, signed_speed_kph), "mode": "keyboard", "device": None, "raw_axes": self.raw_axes}
