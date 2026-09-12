#!/usr/bin/env python3
import asyncio
import json
import time
from pathlib import Path
from aiohttp import web
from smbus2 import SMBus

I2C_BUS = 1
PCA_ADDR = 0x40
PCA_FREQ_HZ = 50
ESC_CHANNEL = 1

MIN_US = 1000
CENTER_US = 1500
MAX_US = 2000
SAFE_MIN_US = 900
SAFE_MAX_US = 2100

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

class PCA9685:
    MODE1 = 0x00
    MODE2 = 0x01
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self, bus=I2C_BUS, addr=PCA_ADDR, freq=PCA_FREQ_HZ):
        self.addr = addr
        self.freq = float(freq)
        self.bus = SMBus(bus)
        self._configure()

    def _write(self, reg, value):
        self.bus.write_byte_data(self.addr, reg, value & 0xFF)

    def _read(self, reg):
        return self.bus.read_byte_data(self.addr, reg)

    def _configure(self):
        self._write(self.MODE2, 0x04)
        old_mode = self._read(self.MODE1)
        sleep_mode = (old_mode & 0x7F) | 0x10
        self._write(self.MODE1, sleep_mode)
        prescale = int(round(25_000_000.0 / (4096.0 * self.freq)) - 1)
        self._write(self.PRESCALE, prescale)
        self._write(self.MODE1, old_mode)
        time.sleep(0.005)
        self._write(self.MODE1, old_mode | 0xA1)
        time.sleep(0.005)

    def pulse_us(self, channel, us):
        counts = int(round(float(us) * self.freq * 4096.0 / 1_000_000.0))
        counts = max(0, min(4095, counts))
        reg = self.LED0_ON_L + 4 * int(channel)
        self.bus.write_i2c_block_data(
            self.addr, reg,
            [0, 0, counts & 0xFF, (counts >> 8) & 0x0F]
        )

    def signal_off(self, channel):
        reg = self.LED0_ON_L + 4 * int(channel)
        self.bus.write_i2c_block_data(self.addr, reg, [0, 0, 0, 0x10])

    def close(self):
        self.bus.close()

class ESCLab:
    def __init__(self):
        self.pca = PCA9685()
        self.current_us = CENTER_US
        self.signal_enabled = True
        self.sequence_running = False
        self.last_action = "startup -> center"
        self.lock = asyncio.Lock()
        self.log_file = LOG_DIR / time.strftime("esc_lab_%Y%m%d_%H%M%S.jsonl")
        self.set_pulse_sync(CENTER_US, "startup-center")

    def log(self, event, **extra):
        row = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "monotonic": time.monotonic(),
            "event": event,
            "pulse_us": self.current_us,
            "signal_enabled": self.signal_enabled,
            **extra,
        }
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def set_pulse_sync(self, us, reason="manual"):
        us = int(round(float(us)))
        if not SAFE_MIN_US <= us <= SAFE_MAX_US:
            raise ValueError(f"pulse must be {SAFE_MIN_US}..{SAFE_MAX_US} us")
        self.pca.pulse_us(ESC_CHANNEL, us)
        self.current_us = us
        self.signal_enabled = True
        self.last_action = f"{reason}: {us} us"
        self.log("pulse", reason=reason, requested_us=us)

    async def set_pulse(self, us, reason="manual"):
        async with self.lock:
            self.set_pulse_sync(us, reason)

    async def off(self):
        async with self.lock:
            self.pca.signal_off(ESC_CHANNEL)
            self.signal_enabled = False
            self.last_action = "PWM signal OFF"
            self.log("signal_off")

    async def run_sequence(self, name):
        if self.sequence_running:
            raise RuntimeError("another sequence is already running")
        self.sequence_running = True
        try:
            sequences = {
                "remembered_min_max_center": [
                    (MIN_US, 1.0, "MIN"),
                    (MAX_US, 2.0, "MAX"),
                    (CENTER_US, 3.0, "CENTER"),
                ],
                "max_min_center": [
                    (MAX_US, 2.0, "MAX"),
                    (MIN_US, 1.0, "MIN"),
                    (CENTER_US, 3.0, "CENTER"),
                ],
                "center_max_min_center": [
                    (CENTER_US, 2.0, "CENTER"),
                    (MAX_US, 2.0, "MAX"),
                    (MIN_US, 2.0, "MIN/REVERSE"),
                    (CENTER_US, 3.0, "CENTER"),
                ],
            }
            seq = sequences.get(name)
            if not seq:
                raise ValueError("unknown sequence")
            self.log("sequence_start", name=name)
            for us, seconds, label in seq:
                await self.set_pulse(us, f"sequence:{name}:{label}")
                await asyncio.sleep(seconds)
            self.log("sequence_end", name=name)
        finally:
            self.sequence_running = False

    def state(self):
        return {
            "i2c_bus": I2C_BUS,
            "pca_address": hex(PCA_ADDR),
            "frequency_hz": PCA_FREQ_HZ,
            "esc_channel": ESC_CHANNEL,
            "pulse_us": self.current_us,
            "signal_enabled": self.signal_enabled,
            "sequence_running": self.sequence_running,
            "last_action": self.last_action,
            "log_file": str(self.log_file),
        }

    def shutdown(self):
        try:
            self.set_pulse_sync(CENTER_US, "shutdown-center")
            time.sleep(0.2)
        finally:
            self.pca.close()

HTML = '''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RCXAZ 30A ESC Lab</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#e9eef7;background:#0a0e14}
body{margin:0;padding:22px;max-width:1100px;margin:auto}
h1{font-size:26px;margin:0 0 6px}.sub{color:#98a6b8;margin-bottom:20px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:#121923;border:1px solid #273243;border-radius:14px;padding:18px}
.full{grid-column:1/-1}
button{border:1px solid #3b4b62;background:#1b2635;color:#eef4ff;border-radius:10px;padding:11px 14px;margin:4px;cursor:pointer}
button:hover{background:#26364a}.danger{border-color:#814646}.primary{border-color:#4b75a8}
input[type=range]{width:100%}
.big{font-size:34px;font-weight:700}.muted{color:#92a0b1;font-size:13px}
.warn{background:#2a2112;border:1px solid #725522;padding:12px;border-radius:10px}
pre{white-space:pre-wrap;background:#090d12;padding:12px;border-radius:10px;max-height:250px;overflow:auto}
textarea{width:100%;height:120px;background:#090d12;color:#eef4ff;border:1px solid #344155;border-radius:8px}
@media(max-width:760px){.grid{grid-template-columns:1fr}.full{grid-column:auto}}
</style>
</head>
<body>
<h1>RCXAZ 30A ESC Lab</h1>
<div class="sub">PCA9685 CH1 / 50 Hz / endpoint·arming·beep 실험 전용</div>
<div class="warn"><b>실험 전:</b> 바퀴를 공중에 띄우십시오. 정상 RC 서버와 동시에 실행하지 마십시오. MIN/MAX 출력은 모터를 즉시 회전시킬 수 있습니다.</div>
<div class="grid">
<section class="card">
<h2>현재 출력</h2>
<div class="big"><span id="pulse">1500</span> µs</div>
<div id="state" class="muted">loading...</div>
<input id="slider" type="range" min="900" max="2100" step="5" value="1500">
<div>
<button onclick="pulse(1000)">MIN 1000</button>
<button class="primary" onclick="pulse(1500)">CENTER 1500</button>
<button onclick="pulse(2000)">MAX 2000</button>
</div>
<div>
<button onclick="adjust(-25)">-25</button><button onclick="adjust(-5)">-5</button>
<button onclick="adjust(5)">+5</button><button onclick="adjust(25)">+25</button>
</div>
<button class="danger" onclick="signalOff()">PWM SIGNAL OFF</button>
</section>

<section class="card">
<h2>전원 투입식 테스트</h2>
<p>ESC 전원을 끈 상태에서 시작 PWM을 먼저 출력하고, 그 다음 ESC 전원을 켜서 소리/LED를 관찰하십시오.</p>
<button onclick="pulse(1000)">MIN 선출력</button>
<button onclick="pulse(1500)">CENTER 선출력</button>
<button onclick="pulse(2000)">MAX 선출력</button>
<p class="muted">시작 신호를 바꿔가며 어느 위치에서 초기화음이 돌아오는지 확인하기 위한 기능입니다.</p>
</section>

<section class="card full">
<h2>자동 후보 시퀀스</h2>
<p><b>A — 기억하신 순서:</b> 1000 µs 1초 → 2000 µs 2초 → 1500 µs 3초</p>
<button onclick="sequence('remembered_min_max_center')">A 실행</button>
<p><b>B — 흔한 PWM ESC 계열:</b> 2000 µs 2초 → 1000 µs 1초 → 1500 µs 3초</p>
<button onclick="sequence('max_min_center')">B 실행</button>
<p><b>C — 양방향 3점 확인:</b> 1500 → 2000 → 1000 → 1500</p>
<button onclick="sequence('center_max_min_center')">C 실행</button>
<p class="muted">이 세 시퀀스는 RCXAZ 30A mini의 공식 절차라고 단정한 것이 아니라, 소리/LED 반응을 찾기 위한 실험 프리셋입니다.</p>
</section>

<section class="card">
<h2>중립점 탐색</h2>
<p>1400~1600 µs에서 조금씩 움직이면서 LED·모터·초기화음을 확인하십시오.</p>
<button onclick="pulse(1400)">1400</button><button onclick="pulse(1450)">1450</button>
<button onclick="pulse(1475)">1475</button><button onclick="pulse(1500)">1500</button>
<button onclick="pulse(1525)">1525</button><button onclick="pulse(1550)">1550</button>
<button onclick="pulse(1600)">1600</button>
</section>

<section class="card">
<h2>관찰 메모</h2>
<textarea id="note" placeholder="예: MAX 선출력 후 ESC ON -> 띠-띠 2회, LED 점멸"></textarea>
<button onclick="saveNote()">현재 µs와 함께 저장</button>
<div class="muted">logs/esc_lab_*.jsonl에 저장됩니다.</div>
</section>

<section class="card full">
<h2>브라우저 로그</h2>
<pre id="log">ready</pre>
</section>
</div>

<script>
let current=1500;
const logEl=document.getElementById('log');
function log(s){logEl.textContent=new Date().toLocaleTimeString()+"  "+s+"\\n"+logEl.textContent.slice(0,5000)}
async function api(url,body={}){
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const t=await r.text(); if(!r.ok) throw new Error(t); return t?JSON.parse(t):{};
}
async function pulse(us){try{const s=await api('/api/pulse',{us});current=s.pulse_us;render(s);log("pulse "+current+" us")}catch(e){log("ERROR "+e)}}
function adjust(d){pulse(current+d)}
async function signalOff(){try{const s=await api('/api/off');render(s);log("PWM signal OFF")}catch(e){log("ERROR "+e)}}
async function sequence(name){
 if(!confirm("바퀴가 공중에 떠 있고 갑작스러운 모터 회전에 대비했습니까?")) return;
 try{await api('/api/sequence',{name});log("sequence start: "+name)}catch(e){log("ERROR "+e)}
}
async function saveNote(){try{await api('/api/note',{note:document.getElementById('note').value});log("note saved @ "+current+" us")}catch(e){log("ERROR "+e)}}
function render(s){
 current=s.pulse_us; document.getElementById('pulse').textContent=current;
 document.getElementById('slider').value=current;
 document.getElementById('state').textContent=`signal=${s.signal_enabled?'ON':'OFF'} / CH${s.esc_channel} / ${s.frequency_hz}Hz / ${s.last_action}`;
}
document.getElementById('slider').addEventListener('change',e=>pulse(Number(e.target.value)));
async function refresh(){
 try{
   const r=await fetch('/api/state');
   if(!r.ok) throw new Error('HTTP '+r.status);
   render(await r.json());
 }catch(e){
   document.getElementById('state').textContent='API ERROR: '+e;
   log('API ERROR '+e);
 }
}
setInterval(refresh,700);refresh();
</script>
</body>
</html>'''

lab = ESCLab()

async def index(request):
    return web.Response(text=HTML, content_type="text/html")

async def state(request):
    return web.json_response(lab.state())

async def pulse_handler(request):
    data = await request.json()
    await lab.set_pulse(data["us"], "web-manual")
    return web.json_response(lab.state())

async def off_handler(request):
    await lab.off()
    return web.json_response(lab.state())

async def sequence_handler(request):
    data = await request.json()
    name = data["name"]
    asyncio.create_task(lab.run_sequence(name))
    return web.json_response({"ok": True, "name": name})

async def note_handler(request):
    data = await request.json()
    lab.log("note", note=str(data.get("note", "")))
    return web.json_response({"ok": True})

async def cleanup(app):
    lab.shutdown()

app = web.Application()
app.add_routes([
    web.get("/", index),
    web.get("/api/state", state),
    web.post("/api/pulse", pulse_handler),
    web.post("/api/off", off_handler),
    web.post("/api/sequence", sequence_handler),
    web.post("/api/note", note_handler),
])
app.on_cleanup.append(cleanup)

if __name__ == "__main__":
    print("RCXAZ 30A ESC Lab")
    print("Open: http://<PI_IP>:8770")
    print("Stop the normal RC project before using this lab.")
    web.run_app(app, host="0.0.0.0", port=8770, access_log=None)
