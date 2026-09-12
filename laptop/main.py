import asyncio, json, time
from aiohttp import web, WSMsgType
from config import load_all, ROOT
from input_manager import InputManager
from vehicle import VehicleModel
from pi_client import PiClient

class App:
    def __init__(self):
        c=load_all(); self.cfg=c["laptop"]
        self.input=InputManager(c["input"]); self.vehicle=VehicleModel(c["vehicle"]); self.pi=PiClient(self.cfg["pi"])
        self.clients=set(); self.keys={k:False for k in "wasd"}; self.arm=False; self.seq=0; self.running=True
        self.latest_input={"steering":0,"throttle":0,"brake":0,"mode":"keyboard","device":None,"raw_axes":{}}
        self.state=self.vehicle.snapshot(0,0,0)

    async def ws_dashboard(self,request):
        ws=web.WebSocketResponse(heartbeat=10); await ws.prepare(request); self.clients.add(ws)
        try:
            async for msg in ws:
                if msg.type!=WSMsgType.TEXT: continue
                try: d=json.loads(msg.data)
                except Exception: continue
                if d.get("type")=="keys":
                    self.keys={k:bool(d.get("state",{}).get(k,False)) for k in "wasd"}; self.input.set_keyboard(self.keys)
                elif d.get("type")=="gear": self.vehicle.set_selector(str(d.get("gear","N")))
                elif d.get("type")=="arm": self.arm=bool(d.get("armed",False))
                elif d.get("type")=="estop":
                    self.arm=False; self.vehicle.set_selector("N"); self.vehicle.motor=0.0
        finally: self.clients.discard(ws)
        return ws

    async def api_config(self,request):
        h=self.cfg["pi"]["host"]; v=self.cfg["video"]
        return web.json_response({"pi_host":h,"video_url":f"http://{h}:{v['webrtc_port']}/{v['path']}?controls=false&muted=true&autoplay=true&playsInline=true"})

    async def sim_loop(self):
        hz=float(self.cfg["simulation"]["hz"]); period=1/hz; last=time.monotonic()
        while self.running:
            start=time.monotonic(); dt=min(0.05,max(0.0001,start-last)); last=start
            self.latest_input=self.input.update(dt)
            self.state=self.vehicle.update(self.latest_input["throttle"],self.latest_input["brake"],self.latest_input["steering"],dt)
            await asyncio.sleep(max(0,period-(time.monotonic()-start)))

    async def control_loop(self):
        period=1/float(self.cfg["pi"]["command_hz"])
        while self.running:
            start=time.monotonic(); self.seq+=1
            await self.pi.send({"type":"control","seq":self.seq,"ts":time.time(),"steering":self.state["steering"],
                "motor":self.state["motor_output"],"brake":self.state["brake"],"selector":self.state["selector"],"armed":self.arm})
            await asyncio.sleep(max(0,period-(time.monotonic()-start)))

    async def dash_loop(self):
        period=1/float(self.cfg["simulation"]["dashboard_hz"])
        while self.running:
            start=time.monotonic()
            p={"type":"state","vehicle":self.state,"input":self.latest_input,
               "link":{"pi_connected":self.pi.connected,"rtt_ms":round(self.pi.last_rtt_ms,1) if self.pi.last_rtt_ms is not None else None,"arm_requested":self.arm},
               "pi":self.pi.last_telemetry}
            dead=[]
            for ws in list(self.clients):
                try: await ws.send_json(p)
                except Exception: dead.append(ws)
            for ws in dead: self.clients.discard(ws)
            await asyncio.sleep(max(0,period-(time.monotonic()-start)))

    async def startup(self,app):
        await self.pi.start()
        app["tasks"]=[asyncio.create_task(self.sim_loop()),asyncio.create_task(self.control_loop()),asyncio.create_task(self.dash_loop())]

    async def cleanup(self,app):
        self.running=False
        for t in app.get("tasks",[]): t.cancel()
        await self.pi.close()

    def webapp(self):
        a=web.Application(); s=ROOT/"laptop"/"static"
        a.router.add_get("/ws",self.ws_dashboard); a.router.add_get("/api/config",self.api_config)
        a.router.add_get("/",lambda r:web.FileResponse(s/"index.html")); a.router.add_static("/static/",s,name="static")
        a.on_startup.append(self.startup); a.on_cleanup.append(self.cleanup); return a

if __name__=="__main__":
    x=App(); c=x.cfg["server"]; web.run_app(x.webapp(),host=c["host"],port=int(c["port"]),access_log=None)
