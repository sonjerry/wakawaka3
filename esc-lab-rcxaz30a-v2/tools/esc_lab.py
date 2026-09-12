#!/usr/bin/env python3
import asyncio
import json
import time
from pathlib import Path
from aiohttp import web
from smbus2 import SMBus

I2C_BUS = 1
PCA_ADDR = 0x40
ESC_CHANNEL = 1
SAFE_MIN_US = 900
SAFE_MAX_US = 2100
FREQUENCIES = {40, 50, 60, 100, 200, 333}
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

class PCA9685:
    MODE1=0x00; MODE2=0x01; PRESCALE=0xFE; LED0_ON_L=0x06
    RESTART=0x80; SLEEP=0x10; AI=0x20; OUTDRV=0x04

    def __init__(self):
        self.addr=PCA_ADDR
        self.bus=SMBus(I2C_BUS)
        self.frequency=50
        self.output_mode="totem"
        self.configure(50, "totem")

    def _w(self, reg, val):
        self.bus.write_byte_data(self.addr, reg, val & 0xFF)

    def _r(self, reg):
        return self.bus.read_byte_data(self.addr, reg)

    def configure(self, frequency, output_mode):
        frequency=int(frequency)
        if frequency not in FREQUENCIES:
            raise ValueError("unsupported frequency")
        if output_mode not in {"totem","open-drain"}:
            raise ValueError("unsupported output mode")

        self._w(self.MODE2, self.OUTDRV if output_mode=="totem" else 0x00)
        old=self._r(self.MODE1)
        self._w(self.MODE1, (old & 0x7F) | self.SLEEP)
        prescale=int(round(25_000_000/(4096*frequency))-1)
        self._w(self.PRESCALE, int(clamp(prescale,3,255)))
        self._w(self.MODE1, old)
        time.sleep(0.005)
        self._w(self.MODE1, old | self.RESTART | self.AI)
        time.sleep(0.005)
        self.frequency=frequency
        self.output_mode=output_mode

    def pulse_us(self, channel, us):
        period=1_000_000/self.frequency
        us=clamp(float(us),0,period)
        counts=int(round(us/period*4096))
        counts=int(clamp(counts,0,4095))
        reg=self.LED0_ON_L+4*int(channel)
        self.bus.write_i2c_block_data(self.addr, reg, [0,0,counts&0xFF,(counts>>8)&0x0F])

    def signal_off(self, channel):
        reg=self.LED0_ON_L+4*int(channel)
        self.bus.write_i2c_block_data(self.addr, reg, [0,0,0,0x10])

    def close(self):
        self.bus.close()

class Lab:
    def __init__(self):
        self.pca=PCA9685()
        self.current_us=1550
        self.signal_enabled=True
        self.sequence_running=False
        self.lock=asyncio.Lock()
        self.last_action="startup -> 1550 us"
        self.log_file=LOG_DIR/time.strftime("esc_lab_%Y%m%d_%H%M%S.jsonl")
        self.set_pulse_sync(1550,"startup")

    def log(self,event,**extra):
        row={"time":time.strftime("%Y-%m-%d %H:%M:%S"),"event":event,
             "pulse_us":self.current_us,"frequency_hz":self.pca.frequency,
             "output_mode":self.pca.output_mode,"signal_enabled":self.signal_enabled,**extra}
        with self.log_file.open("a",encoding="utf-8") as f:
            f.write(json.dumps(row,ensure_ascii=False)+"\n")

    def state(self):
        return {"i2c_bus":I2C_BUS,"pca_address":hex(PCA_ADDR),"esc_channel":ESC_CHANNEL,
                "pulse_us":self.current_us,"frequency_hz":self.pca.frequency,
                "output_mode":self.pca.output_mode,"signal_enabled":self.signal_enabled,
                "sequence_running":self.sequence_running,"last_action":self.last_action,
                "log_file":str(self.log_file)}

    def set_pulse_sync(self,us,reason="manual"):
        us=int(round(float(us)))
        if not SAFE_MIN_US<=us<=SAFE_MAX_US:
            raise ValueError("pulse out of range")
        self.pca.pulse_us(ESC_CHANNEL,us)
        self.current_us=us
        self.signal_enabled=True
        self.last_action=f"{reason}: {us} us"
        self.log("pulse",reason=reason)

    async def set_pulse(self,us,reason="manual"):
        async with self.lock:
            self.set_pulse_sync(us,reason)

    async def set_config(self,frequency,output_mode):
        async with self.lock:
            self.pca.configure(frequency,output_mode)
            self.pca.pulse_us(ESC_CHANNEL,self.current_us)
            self.signal_enabled=True
            self.last_action=f"config: {frequency} Hz / {output_mode}"
            self.log("config")

    async def off(self):
        async with self.lock:
            self.pca.signal_off(ESC_CHANNEL)
            self.signal_enabled=False
            self.last_action="PWM SIGNAL OFF"
            self.log("signal_off")

    async def run_named(self,name):
        if self.sequence_running:
            raise RuntimeError("sequence already running")
        seqs={
          "remembered":[(1000,1.0),(2000,2.0),(1500,3.0)],
          "max_min_center":[(2000,2.0),(1000,1.0),(1500,3.0)],
          "center_max_min_center":[(1500,2.0),(2000,2.0),(1000,2.0),(1500,3.0)],
          "scan_up_1550":[*[(v,0.55) for v in range(1550,2001,10)],(1550,1.0)],
          "scan_down_1550":[*[(v,0.55) for v in range(1550,999,-10)],(1550,1.0)],
          "neutral_scan":[*[(v,0.45) for v in range(1300,1701,5)],(1550,1.0)],
        }
        pts=seqs.get(name)
        if not pts:
            raise ValueError("unknown sequence")
        self.sequence_running=True
        try:
            self.log("sequence_start",name=name)
            for us,hold in pts:
                await self.set_pulse(us,name)
                await asyncio.sleep(hold)
            self.log("sequence_end",name=name)
        finally:
            self.sequence_running=False

    def shutdown(self):
        try:
            self.set_pulse_sync(1550,"shutdown")
            time.sleep(0.15)
        finally:
            self.pca.close()

HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESC Lab v2</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#eaf0f7;background:#080c11}
body{max-width:1150px;margin:auto;padding:22px}
h1{margin:0 0 4px;font-size:27px}.sub{color:#8f9dad;margin-bottom:18px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:#111821;border:1px solid #293545;border-radius:14px;padding:17px}.full{grid-column:1/-1}
.warn{background:#2c2111;border:1px solid #6d5325;border-radius:11px;padding:12px;margin-bottom:14px}
button,select,input{font:inherit}button{background:#1a2634;color:#edf4ff;border:1px solid #3b4d63;border-radius:9px;padding:10px 13px;margin:4px;cursor:pointer}
button:hover{background:#25374b}button.danger{border-color:#87494d}button.primary{border-color:#4778b6}
.big{font-size:36px;font-weight:750}.muted{font-size:13px;color:#8d9cab}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
input[type=range]{width:100%}select{background:#0b1118;color:#edf4ff;border:1px solid #36465b;border-radius:8px;padding:8px}
pre{background:#070b10;border-radius:9px;padding:11px;max-height:260px;overflow:auto}
textarea{width:100%;height:100px;background:#080d13;color:#eef4ff;border:1px solid #344155;border-radius:8px}
@media(max-width:780px){.grid{grid-template-columns:1fr}.full{grid-column:auto}}
</style>
</head><body>
<h1>RCXAZ 30A ESC Lab v2</h1>
<div class="sub">PCA9685 CH1 · PWM protocol explorer</div>
<div class="warn"><b>주의:</b> 바퀴를 공중에 띄우고 정상 RC 서버를 종료하십시오.</div>

<div class="grid">
<section class="card">
<h2>현재 출력</h2>
<div class="big"><span id="pulse">1550</span> µs</div>
<div id="status" class="muted">loading...</div>
<input id="slider" type="range" min="900" max="2100" step="5" value="1550">
<div class="row">
<button onclick="setPulse(1000)">1000</button><button onclick="setPulse(1500)">1500</button>
<button class="primary" onclick="setPulse(1550)">1550</button><button onclick="setPulse(2000)">2000</button>
</div>
<div class="row">
<button onclick="delta(-25)">-25</button><button onclick="delta(-10)">-10</button><button onclick="delta(-5)">-5</button>
<button onclick="delta(5)">+5</button><button onclick="delta(10)">+10</button><button onclick="delta(25)">+25</button>
</div>
<button class="danger" onclick="signalOff()">PWM SIGNAL OFF</button>
</section>

<section class="card">
<h2>PWM 설정</h2>
<label>Frequency</label>
<select id="freq"><option>40</option><option selected>50</option><option>60</option><option>100</option><option>200</option><option>333</option></select>
<label>Output mode</label>
<select id="mode"><option value="totem" selected>Totem-pole</option><option value="open-drain">Open-drain</option></select>
<div><button class="primary" onclick="applyConfig()">적용</button></div>
</section>

<section class="card full">
<h2>Power-on preset</h2>
<p>ESC 전원을 끈 뒤 하나를 눌러 PWM을 먼저 출력하고, 그 상태에서 ESC 전원을 켜십시오.</p>
<button onclick="setPulse(1000)">MIN 1000</button><button onclick="setPulse(1500)">CENTER 1500</button>
<button class="primary" onclick="setPulse(1550)">CENTER? 1550</button><button onclick="setPulse(2000)">MAX 2000</button>
</section>

<section class="card full">
<h2>자동 스캔</h2>
<p>1550 → 2000, 10 µs씩</p><button onclick="sequence('scan_up_1550')">상향 스캔</button>
<p>1550 → 1000, 10 µs씩</p><button onclick="sequence('scan_down_1550')">하향 스캔</button>
<p>1300~1700, 5 µs씩</p><button onclick="sequence('neutral_scan')">중립 정밀 스캔</button>
</section>

<section class="card">
<h2>캘리브레이션 후보</h2>
<button onclick="sequence('remembered')">1000(1s) → 2000(2s) → 1500</button>
<button onclick="sequence('max_min_center')">2000(2s) → 1000(1s) → 1500</button>
<button onclick="sequence('center_max_min_center')">1500 → 2000 → 1000 → 1500</button>
</section>

<section class="card">
<h2>관찰 메모</h2>
<textarea id="note" placeholder="예: 1550에서 점멸→지속점등"></textarea>
<button onclick="saveNote()">로그 저장</button>
</section>

<section class="card full"><h2>브라우저 로그</h2><pre id="log">ready</pre></section>
</div>

<script>
let current=1550;
const $=id=>document.getElementById(id);
function writeLog(t){$('log').textContent=new Date().toLocaleTimeString()+'  '+t+'\\n'+$('log').textContent.slice(0,7000)}
async function post(url,body={}){
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const tx=await r.text(); if(!r.ok) throw new Error(tx||('HTTP '+r.status)); return tx?JSON.parse(tx):{};
}
function render(s){
 current=Number(s.pulse_us); $('pulse').textContent=current; $('slider').value=current;
 $('freq').value=String(s.frequency_hz); $('mode').value=s.output_mode;
 $('status').textContent=`signal=${s.signal_enabled?'ON':'OFF'} · CH${s.esc_channel} · ${s.frequency_hz}Hz · ${s.output_mode} · ${s.last_action}`;
}
async function setPulse(us){try{const s=await post('/api/pulse',{us:Number(us)});render(s);writeLog('pulse '+us+' us')}catch(e){writeLog('ERROR '+e)}}
function delta(d){setPulse(current+d)}
async function applyConfig(){try{const s=await post('/api/config',{frequency:Number($('freq').value),output_mode:$('mode').value});render(s);writeLog('CONFIG '+s.frequency_hz+'Hz / '+s.output_mode)}catch(e){writeLog('ERROR '+e)}}
async function signalOff(){try{const s=await post('/api/off');render(s);writeLog('PWM OFF')}catch(e){writeLog('ERROR '+e)}}
async function sequence(name){if(!confirm('바퀴가 공중에 떠 있습니까?'))return;try{await post('/api/sequence',{name});writeLog('SEQUENCE '+name)}catch(e){writeLog('ERROR '+e)}}
async function saveNote(){try{await post('/api/note',{note:$('note').value});writeLog('NOTE SAVED @ '+current+' us')}catch(e){writeLog('ERROR '+e)}}
$('slider').addEventListener('change',e=>setPulse(Number(e.target.value)));
async function refresh(){try{const r=await fetch('/api/state');if(!r.ok)throw new Error('HTTP '+r.status);render(await r.json())}catch(e){$('status').textContent='API ERROR: '+e}}
setInterval(refresh,700);refresh();
</script>
</body></html>'''

lab=Lab()

async def index(req): return web.Response(text=HTML,content_type="text/html")
async def state(req): return web.json_response(lab.state())
async def pulse(req):
    d=await req.json(); await lab.set_pulse(d["us"],"manual"); return web.json_response(lab.state())
async def config(req):
    d=await req.json(); await lab.set_config(d["frequency"],d["output_mode"]); return web.json_response(lab.state())
async def off(req):
    await lab.off(); return web.json_response(lab.state())
async def sequence(req):
    d=await req.json(); asyncio.create_task(lab.run_named(d["name"])); return web.json_response({"ok":True,"name":d["name"]})
async def note(req):
    d=await req.json(); lab.log("note",note=str(d.get("note",""))); return web.json_response({"ok":True})
async def cleanup(app): lab.shutdown()

app=web.Application()
app.add_routes([web.get("/",index),web.get("/api/state",state),web.post("/api/pulse",pulse),web.post("/api/config",config),web.post("/api/off",off),web.post("/api/sequence",sequence),web.post("/api/note",note)])
app.on_cleanup.append(cleanup)

if __name__=="__main__":
    print("ESC Lab v2")
    print("Open: http://<PI_IP>:8770")
    web.run_app(app,host="0.0.0.0",port=8770,access_log=None)
