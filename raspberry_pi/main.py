import asyncio
import json
import time
from aiohttp import web, WSMsgType
from config import load_config
from hardware import Hardware
from telemetry import cpu_temp, throttled


class Server:
    def __init__(self):
        self.cfg = load_config()
        self.hw = Hardware(self.cfg)
        self.last_cmd = 0.0
        self.last_seq = None
        self.payload = {}
        self.failsafe = True
        self.clients = set()
        self.running = True
        self.last_hw = time.monotonic()
        self.power = {"power_raw": None, "undervoltage": False, "throttled": False}

    def fail(self):
        self.failsafe = True
        self.hw.safe(bool(self.cfg["failsafe"]["center_steering"]))

    def esc_status(self):
        return {
            "esc_ready": self.hw.esc.ready,
            "armed": self.hw.esc.armed,
            "drive_enabled": self.hw.esc.drive_enabled,
            "esc_output": round(self.hw.esc.value, 4),
            "esc_pulse_us": round(self.hw.esc.last_pulse_us, 1),
            "esc_mode": self.hw.esc.last_mode,
            "steering_output": round(self.hw.steering.value, 4),
            "steering_center_us": round(self.hw.steering.center_pulse_us, 1),
        }

    async def health(self, request):
        age = time.monotonic() - self.last_cmd if self.last_cmd else None
        return web.json_response({
            "ok": True,
            "failsafe": self.failsafe,
            "command_age_s": age,
            "cpu_temp_c": cpu_temp(),
            **self.power,
            **self.esc_status(),
        })

    async def ws(self, request):
        ws = web.WebSocketResponse(heartbeat=2, autoping=True)
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue
                if data.get("type") == "control":
                    self.payload = data
                    self.last_seq = data.get("seq")
                    self.last_cmd = time.monotonic()
                    self.failsafe = False
        finally:
            self.clients.discard(ws)
            self.fail()
        return ws

    async def hw_loop(self):
        timeout = float(self.cfg["failsafe"]["command_timeout_s"])
        while self.running:
            start = time.monotonic()
            dt = min(0.05, max(0.0001, start - self.last_hw))
            self.last_hw = start

            # Always service the ESC startup neutral handshake, even before a
            # laptop is connected.
            self.hw.esc.service_startup()

            age = start - self.last_cmd if self.last_cmd else 999.0
            if age > timeout:
                if not self.failsafe:
                    self.fail()
            else:
                p = self.payload
                selector = str(p.get("selector", "P"))
                drive_enabled = bool(p.get("armed", False))
                self.hw.esc.set_drive_enabled(drive_enabled)
                self.hw.steering.update(float(p.get("steering", 0.0)), dt)

                motor = float(p.get("motor", 0.0))
                if selector in {"P", "N"}:
                    motor = 0.0
                elif selector == "R":
                    motor = -abs(motor)
                else:
                    motor = abs(motor)

                self.hw.esc.update(
                    target=motor,
                    brake=float(p.get("brake", 0.0)),
                    signed_speed_kph=float(p.get("signed_speed_kph", 0.0)),
                    dt=dt,
                )

            await asyncio.sleep(max(0.0, 0.01 - (time.monotonic() - start)))

    async def power_loop(self):
        while self.running:
            self.power = await throttled()
            await asyncio.sleep(1.0)

    async def tel_loop(self):
        while self.running:
            age = time.monotonic() - self.last_cmd if self.last_cmd else None
            packet = {
                "type": "telemetry",
                "ack_seq": self.last_seq,
                "failsafe": self.failsafe,
                "command_age_ms": round(age * 1000.0, 1) if age is not None else None,
                "cpu_temp_c": cpu_temp(),
                **self.power,
                **self.esc_status(),
            }
            dead = []
            for ws in list(self.clients):
                try:
                    await ws.send_json(packet)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.discard(ws)
            await asyncio.sleep(float(self.cfg["telemetry"]["interval_s"]))

    async def startup(self, app):
        self.hw.safe(True)
        app["tasks"] = [
            asyncio.create_task(self.hw_loop()),
            asyncio.create_task(self.power_loop()),
            asyncio.create_task(self.tel_loop()),
        ]

    async def cleanup(self, app):
        self.running = False
        for task in app.get("tasks", []):
            task.cancel()
        self.hw.deinit()

    def app(self):
        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_get("/ws/control", self.ws)
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.cleanup)
        return app


if __name__ == "__main__":
    server = Server()
    cfg = server.cfg["server"]
    web.run_app(server.app(), host=cfg["host"], port=int(cfg["port"]), access_log=None)
