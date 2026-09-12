import asyncio, json, time
from aiohttp import web, WSMsgType
from config import load_config
from hardware import Hardware
from telemetry import cpu_temp, throttled

class Server:
    def __init__(self):
        self.cfg=load_config(); self.hw=Hardware(self.cfg); self.last_cmd=0.0; self.last_seq=None
        self.payload={}; self.failsafe=True; self.clients=set(); self.running=True; self.last_hw=time.monotonic()
        self.power={"power_raw":None,"undervoltage":False,"throttled":False}

    def fail(self):
        self.failsafe=True; self.hw.safe(bool(self.cfg["failsafe"]["center_steering"]))

    async def health(self,r):
        age=time.monotonic()-self.last_cmd if self.last_cmd else None
        return web.json_response({"ok":True,"armed":self.hw.esc.armed,"failsafe":self.failsafe,"command_age_s":age,"cpu_temp_c":cpu_temp(),**self.power})

    async def ws(self,r):
        ws=web.WebSocketResponse(heartbeat=2,autoping=True); await ws.prepare(r); self.clients.add(ws)
        try:
            async for m in ws:
                if m.type!=WSMsgType.TEXT: continue
                try: d=json.loads(m.data)
                except Exception: continue
                if d.get("type")=="control":
                    self.payload=d; self.last_seq=d.get("seq"); self.last_cmd=time.monotonic(); self.failsafe=False
        finally: self.clients.discard(ws); self.fail()
        return ws

    async def hw_loop(self):
        timeout=float(self.cfg["failsafe"]["command_timeout_s"])
        while self.running:
            start=time.monotonic(); dt=min(.05,max(.0001,start-self.last_hw)); self.last_hw=start
            age=start-self.last_cmd if self.last_cmd else 999
            if age>timeout:
                if not self.failsafe: self.fail()
            else:
                p=self.payload
                motor=float(p.get("motor",0)); sel=str(p.get("selector","N"))
                can_start_arm = sel in {"P","N"} and abs(motor) < 0.03
                self.hw.esc.request_arm(bool(p.get("armed",False)), can_start=can_start_arm)
                self.hw.steering.update(float(p.get("steering",0)),dt)
                motor=0 if sel in {"P","N"} else (-abs(motor) if sel=="R" else abs(motor))
                self.hw.esc.update(motor,dt)
            await asyncio.sleep(max(0,.01-(time.monotonic()-start)))

    async def power_loop(self):
        while self.running: self.power=await throttled(); await asyncio.sleep(1)

    async def tel_loop(self):
        while self.running:
            age=time.monotonic()-self.last_cmd if self.last_cmd else None
            p={"type":"telemetry","ack_seq":self.last_seq,"armed":self.hw.esc.armed,"failsafe":self.failsafe,
               "command_age_ms":round(age*1000,1) if age is not None else None,"cpu_temp_c":cpu_temp(),
               **self.power,"esc_output":round(self.hw.esc.value,4),"steering_output":round(self.hw.steering.value,4)}
            dead=[]
            for ws in list(self.clients):
                try: await ws.send_json(p)
                except Exception: dead.append(ws)
            for ws in dead: self.clients.discard(ws)
            await asyncio.sleep(float(self.cfg["telemetry"]["interval_s"]))

    async def startup(self,a):
        self.hw.safe(True); a["tasks"]=[asyncio.create_task(self.hw_loop()),asyncio.create_task(self.power_loop()),asyncio.create_task(self.tel_loop())]
    async def cleanup(self,a):
        self.running=False
        for t in a.get("tasks",[]): t.cancel()
        self.hw.deinit()
    def app(self):
        a=web.Application(); a.router.add_get("/health",self.health); a.router.add_get("/ws/control",self.ws)
        a.on_startup.append(self.startup); a.on_cleanup.append(self.cleanup); return a

if __name__=="__main__":
    s=Server(); c=s.cfg["server"]; web.run_app(s.app(),host=c["host"],port=int(c["port"]),access_log=None)
