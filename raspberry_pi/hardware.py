import time, board, busio
from adafruit_pca9685 import PCA9685

def clamp(v,lo,hi): return max(lo,min(hi,v))
def approach(c,t,r,dt):
    d=r*dt
    return min(t,c+d) if c<t else max(t,c-d)

class PCA:
    def __init__(self,cfg):
        c=cfg["pca9685"]; self.freq=float(c["frequency_hz"])
        self.i2c=busio.I2C(board.SCL,board.SDA); self.pca=PCA9685(self.i2c,address=int(c["address"])); self.pca.frequency=self.freq
    def pulse(self,ch,us):
        duty=int(clamp(float(us)/(1_000_000/self.freq),0,1)*65535); self.pca.channels[int(ch)].duty_cycle=duty
    def deinit(self): self.pca.deinit()

class Steering:
    def __init__(self,pca,cfg): self.pca=pca; self.c=cfg["steering"]; self.value=0.0
    def update(self,target,dt):
        if self.c.get("invert"): target=-target
        self.value=approach(self.value,clamp(float(target),-1,1),float(self.c["max_slew_per_s"]),dt)
        ctr=float(self.c["center_us"])
        us=ctr+((-self.value)*(float(self.c["left_us"])-ctr) if self.value<0 else self.value*(float(self.c["right_us"])-ctr))
        self.pca.pulse(self.c["channel"],us)
    def center(self): self.value=0.0; self.pca.pulse(self.c["channel"],self.c["center_us"])

class ESC:
    def __init__(self,pca,cfg):
        self.pca=pca; self.c=cfg["esc"]; self.armed=False; self.arm_at=None; self.value=0.0; self.block_until=0.0; self.neutral()
    def neutral(self): self.pca.pulse(self.c["channel"],self.c["neutral_us"])
    def disarm(self): self.armed=False; self.arm_at=None; self.value=0.0; self.block_until=0.0; self.neutral()
    def request_arm(self,on,can_start=True):
        now=time.monotonic()
        if not on: self.disarm(); return
        if self.armed: return
        if not can_start:
            self.arm_at=None; self.neutral(); return
        if self.arm_at is None: self.arm_at=now; self.neutral(); return
        if now-self.arm_at>=float(self.c["arm_hold_s"]): self.armed=True
    def pulse_for(self,v):
        if abs(v)<=float(self.c["output_deadband"]): return float(self.c["neutral_us"])
        if v>0: return float(self.c["forward_min_us"])+v*(float(self.c["forward_max_us"])-float(self.c["forward_min_us"]))
        m=abs(v); return float(self.c["reverse_min_us"])+m*(float(self.c["reverse_max_us"])-float(self.c["reverse_min_us"]))
    def update(self,target,dt):
        now=time.monotonic()
        if not self.armed: self.value=0.0; self.neutral(); return
        target=clamp(float(target),-1,1)
        td=1 if target>0.03 else (-1 if target<-0.03 else 0); cd=1 if self.value>0.03 else (-1 if self.value<-0.03 else 0)
        if cd and td and cd!=td:
            target=0.0; self.block_until=max(self.block_until,now+float(self.c["direction_neutral_hold_s"]))
        if now<self.block_until: target=0.0
        self.value=approach(self.value,target,float(self.c["output_slew_per_s"]),dt)
        if abs(self.value)<0.01: self.value=0.0
        self.pca.pulse(self.c["channel"],self.pulse_for(self.value))

class Hardware:
    def __init__(self,cfg):
        self.pca=PCA(cfg); self.steering=Steering(self.pca,cfg); self.esc=ESC(self.pca,cfg)
    def safe(self,center=True):
        self.esc.disarm()
        if center: self.steering.center()
    def deinit(self): self.safe(True); self.pca.deinit()
