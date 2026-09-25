import asyncio, json, time
from aiohttp import ClientSession, WSMsgType

class PiClient:
    def __init__(self,cfg):
        self.cfg=cfg; self.ws=None; self.session=None; self.connected=False
        self.last_telemetry={}; self.last_rtt_ms=None; self.sent={}; self.stop=False

    @property
    def url(self):
        return f"ws://{self.cfg['host']}:{self.cfg['control_port']}{self.cfg['websocket_path']}"

    async def start(self):
        self.session=ClientSession()
        asyncio.create_task(self.loop())

    async def close(self):
        self.stop=True
        if self.ws: await self.ws.close()
        if self.session: await self.session.close()

    async def loop(self):
        while not self.stop:
            try:
                async with self.session.ws_connect(self.url,heartbeat=1,autoping=True,timeout=3) as ws:
                    self.last_telemetry={}
                    self.ws=ws; self.connected=True
                    async for msg in ws:
                        if msg.type==WSMsgType.TEXT:
                            d=json.loads(msg.data)
                            if d.get("type")=="telemetry":
                                self.last_telemetry=d
                                seq=d.get("ack_seq")
                                if seq in self.sent:
                                    self.last_rtt_ms=(time.monotonic()-self.sent.pop(seq))*1000
                                    for old in list(self.sent)[:-50]: self.sent.pop(old,None)
            except Exception:
                pass
            finally:
                self.connected=False; self.ws=None; self.last_telemetry={}
            await asyncio.sleep(float(self.cfg["reconnect_seconds"]))

    async def send(self,payload):
        if not self.connected or not self.ws: return
        if payload.get("seq") is not None: self.sent[payload["seq"]]=time.monotonic()
        try: await self.ws.send_json(payload)
        except Exception: self.connected=False
