import asyncio
from pathlib import Path

def cpu_temp():
    try: return round(float(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip())/1000,1)
    except Exception: return None

async def throttled():
    try:
        p=await asyncio.create_subprocess_exec("vcgencmd","get_throttled",stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        out,_=await asyncio.wait_for(p.communicate(),timeout=.8); text=out.decode().strip()
        if "0x" in text:
            v=int(text.split("0x",1)[1],16); return {"power_raw":f"0x{v:x}","undervoltage":bool(v&1),"throttled":bool(v&4)}
    except Exception: pass
    return {"power_raw":None,"undervoltage":False,"throttled":False}
