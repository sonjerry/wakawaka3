import asyncio
import json
import time

from aiohttp import web, WSMsgType

from config import load_all, ROOT
from input_manager import InputManager
from vehicle import VehicleModel
from pi_client import PiClient


BOOT_DURATION_S = 2.35
CONTROL_REVISION = 3
START_BRAKE_THRESHOLD = 0.20
GEAR_BRAKE_THRESHOLD = 0.18
STOP_SPEED_THRESHOLD_KPH = 0.5


class App:
    def __init__(self):
        cfg = load_all()
        self.cfg = cfg["laptop"]
        self.input = InputManager(cfg["input"])
        self.vehicle = VehicleModel(cfg["vehicle"])
        self.pi = PiClient(self.cfg["pi"])

        self.clients = set()
        self.keys = {k: False for k in "wasd"}
        self.seq = 0
        self.running = True

        self.latest_input = {
            "steering": 0.0,
            "throttle": 0.0,
            "brake": 0.0,
            "mode": "keyboard",
            "device": None,
            "raw_axes": {},
        }
        self.state = self.vehicle.snapshot(0.0, 0.0, 0.0)

        self.ignition_state = "off"  # off / boot / on
        self.ignition_since = time.monotonic()
        self.ui_notice = "HOLD BRAKE · PRESS START"
        self.notice_until = 0.0

    def set_notice(self, text, duration=2.2):
        self.ui_notice = text
        self.notice_until = time.monotonic() + duration

    def ignition_payload(self):
        return {
            "state": self.ignition_state,
            "elapsed_s": round(time.monotonic() - self.ignition_since, 3),
            "boot_duration_s": BOOT_DURATION_S,
        }

    def ignition_is_on(self):
        return self.ignition_state == "on"

    def pi_drive_ready(self):
        return bool(self.pi.connected and self.pi.last_telemetry.get("armed", False)
                    and self.pi.last_telemetry.get("control_revision") == CONTROL_REVISION)

    def toggle_ignition(self):
        brake = float(self.latest_input.get("brake", 0.0))
        speed = abs(float(self.state.get("speed_kph", 0.0)))

        if self.ignition_state == "off":
            if brake < START_BRAKE_THRESHOLD:
                self.set_notice("HOLD BRAKE TO START")
                return
            if self.vehicle.selector not in {"P", "N"}:
                self.set_notice("START AVAILABLE IN P / N")
                return
            if speed > STOP_SPEED_THRESHOLD_KPH:
                self.set_notice("STOP VEHICLE BEFORE START")
                return

            self.vehicle.shutdown()
            self.ignition_state = "boot"
            self.ignition_since = time.monotonic()
            self.set_notice("SYSTEM CHECK", duration=BOOT_DURATION_S)
            return

        if self.ignition_state == "boot":
            self.set_notice("SYSTEM CHECK IN PROGRESS")
            return

        # ENGINE ON -> OFF. Prevent accidental power-off while moving.
        if speed > STOP_SPEED_THRESHOLD_KPH:
            self.set_notice("STOP VEHICLE BEFORE ENGINE OFF")
            return
        if self.vehicle.selector != "P":
            self.set_notice("SHIFT TO P BEFORE ENGINE OFF")
            return

        self.vehicle.shutdown()
        self.ignition_state = "off"
        self.ignition_since = time.monotonic()
        self.set_notice("IGNITION OFF")

    def request_gear(self, gear):
        gear = str(gear).upper()
        if gear not in {"P", "R", "N", "D"}:
            return

        if gear == self.vehicle.selector:
            return

        if not self.ignition_is_on():
            self.set_notice("IGNITION REQUIRED")
            return

        brake = float(self.latest_input.get("brake", 0.0))
        if brake < GEAR_BRAKE_THRESHOLD:
            self.set_notice("HOLD BRAKE TO SHIFT")
            return

        if self.vehicle.set_selector(gear):
            self.set_notice(f"{gear} SELECTED", duration=1.0)
        else:
            self.set_notice("SHIFT DENIED · VEHICLE SPEED")

    async def ws_dashboard(self, request):
        ws = web.WebSocketResponse(heartbeat=10)
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

                msg_type = data.get("type")
                if msg_type == "keys":
                    self.keys = {
                        k: bool(data.get("state", {}).get(k, False))
                        for k in "wasd"
                    }
                    self.input.set_keyboard(self.keys)

                elif msg_type == "gear":
                    self.request_gear(data.get("gear", "P"))

                elif msg_type == "ignition_toggle":
                    self.toggle_ignition()

                elif msg_type == "estop":
                    self.vehicle.shutdown()
                    self.ignition_state = "off"
                    self.ignition_since = time.monotonic()
                    self.set_notice("EMERGENCY STOP", duration=3.0)
        finally:
            self.clients.discard(ws)
            if not self.clients:
                self.keys = {k: False for k in "wasd"}
                self.input.set_keyboard(self.keys)

        return ws

    async def api_config(self, request):
        host = self.cfg["pi"]["host"]
        video = self.cfg["video"]
        return web.json_response({
            "pi_host": host,
            "video_url": (
                f"http://{host}:{video['webrtc_port']}/{video['path']}"
                "?controls=false&muted=true&autoplay=true&playsInline=true"
            ),
        })

    def update_default_notice(self):
        if time.monotonic() <= self.notice_until:
            return

        brake = float(self.latest_input.get("brake", 0.0))
        if self.ignition_state == "off":
            self.ui_notice = "HOLD BRAKE · PRESS START"
        elif self.ignition_state == "boot":
            self.ui_notice = "SYSTEM CHECK"
        elif not self.pi.connected:
            self.ui_notice = "CONTROL LINK OFFLINE"
        elif self.pi.last_telemetry.get("control_revision") != CONTROL_REVISION:
            self.ui_notice = "UPDATE BOTH LAPTOP AND PI"
        elif not self.pi.last_telemetry.get("armed", False):
            self.ui_notice = "DRIVE SYSTEM ARMING"
        elif brake >= GEAR_BRAKE_THRESHOLD:
            self.ui_notice = "BRAKE HELD · SHIFT UNLOCKED"
        else:
            self.ui_notice = "DRIVE READY · HOLD BRAKE TO SHIFT"

    async def sim_loop(self):
        hz = float(self.cfg["simulation"]["hz"])
        period = 1.0 / hz
        last = time.monotonic()

        while self.running:
            started = time.monotonic()
            dt = min(0.05, max(0.0001, started - last))
            last = started

            self.latest_input = self.input.update(dt, self.vehicle.speed_kph)

            if (
                self.ignition_state == "boot"
                and started - self.ignition_since >= BOOT_DURATION_S
            ):
                self.ignition_state = "on"
                self.ignition_since = time.monotonic()
                self.vehicle.power_on()
                self.set_notice("ENGINE ON · DRIVE SYSTEM ARMING", duration=1.8)

            if self.ignition_is_on():
                self.state = self.vehicle.update(
                    self.latest_input["throttle"],
                    self.latest_input["brake"],
                    self.latest_input["steering"],
                    dt,
                )
            else:
                # Inputs are still read while off so brake-to-start works, but
                # vehicle and actuator commands remain zeroed.
                self.vehicle.shutdown()
                self.state = self.vehicle.snapshot(
                    0.0,
                    self.latest_input["brake"],
                    0.0,
                )

            self.update_default_notice()
            await asyncio.sleep(max(0.0, period - (time.monotonic() - started)))

    async def control_loop(self):
        period = 1.0 / float(self.cfg["pi"]["command_hz"])

        while self.running:
            started = time.monotonic()
            self.seq += 1

            ignition_on = self.ignition_is_on()
            pi_armed = self.pi_drive_ready()

            # Pi must arm in P/N with neutral motor. Even if the user selects
            # D/R immediately after startup, keep the hardware command in P
            # until Pi confirms armed, then release the requested selector.
            if ignition_on and pi_armed:
                selector_out = self.state["selector"]
                motor_out = self.state["motor_output"]
                steering_out = self.state["steering"]
                brake_out = self.state["brake"]
            elif ignition_on:
                selector_out = "P"
                motor_out = 0.0
                steering_out = self.state["steering"]
                brake_out = self.state["brake"]
            else:
                selector_out = "P"
                motor_out = 0.0
                steering_out = 0.0
                brake_out = 0.0

            await self.pi.send({
                "type": "control",
                "control_revision": CONTROL_REVISION,
                "seq": self.seq,
                "ts": time.time(),
                "steering": steering_out,
                "motor": motor_out,
                "brake": brake_out,
                "signed_speed_kph": self.state.get("signed_speed_kph", 0.0),
                "selector": selector_out,
                "armed": ignition_on and pi_armed,
            })

            await asyncio.sleep(max(0.0, period - (time.monotonic() - started)))

    async def dash_loop(self):
        period = 1.0 / float(self.cfg["simulation"]["dashboard_hz"])

        while self.running:
            started = time.monotonic()
            brake = float(self.latest_input.get("brake", 0.0))

            packet = {
                "type": "state",
                "vehicle": self.state,
                "input": self.latest_input,
                "link": {
                    "pi_connected": self.pi.connected,
                    "rtt_ms": (
                        round(self.pi.last_rtt_ms, 1)
                        if self.pi.last_rtt_ms is not None
                        else None
                    ),
                    "drive_ready": self.pi_drive_ready(),
                },
                "interlock": {
                    "brake_held": brake >= GEAR_BRAKE_THRESHOLD,
                    "start_brake_held": brake >= START_BRAKE_THRESHOLD,
                    "gear_brake_threshold": GEAR_BRAKE_THRESHOLD,
                },
                "ignition": self.ignition_payload(),
                "notice": self.ui_notice,
                "pi": self.pi.last_telemetry,
            }

            dead = []
            for ws in list(self.clients):
                try:
                    await ws.send_json(packet)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.discard(ws)

            await asyncio.sleep(max(0.0, period - (time.monotonic() - started)))

    async def startup(self, app):
        await self.pi.start()
        app["tasks"] = [
            asyncio.create_task(self.sim_loop()),
            asyncio.create_task(self.control_loop()),
            asyncio.create_task(self.dash_loop()),
        ]

    async def cleanup(self, app):
        self.running = False
        for task in app.get("tasks", []):
            task.cancel()
        await self.pi.close()

    def webapp(self):
        app = web.Application()
        static_dir = ROOT / "laptop" / "static"
        app.router.add_get("/ws", self.ws_dashboard)
        app.router.add_get("/api/config", self.api_config)
        app.router.add_get("/", lambda _: web.FileResponse(static_dir / "index.html"))
        app.router.add_static("/static/", static_dir, name="static")
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.cleanup)
        return app


if __name__ == "__main__":
    app_obj = App()
    server_cfg = app_obj.cfg["server"]
    web.run_app(
        app_obj.webapp(),
        host=server_cfg["host"],
        port=int(server_cfg["port"]),
        access_log=None,
    )
