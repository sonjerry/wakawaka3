import math

def clamp(v, lo, hi): return max(lo, min(hi, v))
def lerp(a,b,t): return a + (b-a)*t
def approach(cur,target,rate,dt):
    d=rate*dt
    return min(target,cur+d) if cur<target else max(target,cur-d)

class VehicleModel:
    def __init__(self, cfg):
        self.cfg=cfg
        self.v=cfg["vehicle"]; self.s=cfg["speed"]; self.e=cfg["engine"]
        self.t=cfg["transmission"]; self.m=cfg["esc_model"]
        self.selector="P"; self.gear=1; self.speed_mps=0.0
        self.rpm=float(self.e["idle_rpm"]); self.motor=0.0
        self.shifting=False; self.pending_gear=1; self.shift_end=0.0; self.last_shift=-999.0; self.sim_time=0.0; self.prev_throttle=0.0

    @property
    def speed_kph(self): return self.speed_mps*3.6

    def set_selector(self, s):
        s=s.upper()
        if s not in {"P","R","N","D"}: return False
        if s in {"D","R"} and self.selector in {"D","R"} and s!=self.selector and abs(self.speed_kph)>1.0:
            return False
        if s=="P" and abs(self.speed_kph)>0.5: return False
        self.selector=s
        return True

    def wheel_rpm(self):
        return abs(self.speed_mps)/(2*math.pi*float(self.v["wheel_radius_m"]))*60.0

    def rpm_for_gear(self,g):
        return max(float(self.e["idle_rpm"]), self.wheel_rpm()*float(self.t["ratios"][g-1])*float(self.t["final_drive"]))

    def torque_factor(self,rpm):
        pts=self.e["torque_curve"]
        if rpm<=pts[0][0]: return float(pts[0][1])
        for (r0,t0),(r1,t1) in zip(pts,pts[1:]):
            if r0<=rpm<=r1:
                return lerp(float(t0),float(t1),(rpm-r0)/(r1-r0))
        return float(pts[-1][1])

    def start_shift(self,g,now):
        g=int(clamp(g,1,len(self.t["ratios"])))
        if g==self.gear or self.shifting or now-self.last_shift<float(self.t["min_shift_interval_s"]): return
        self.shifting=True; self.pending_gear=g
        self.shift_end=now+float(self.t["shift_duration_s"]); self.last_shift=now

    def transmission(self,throttle,now):
        if self.selector!="D": return
        rpm=self.rpm
        if self.shifting:
            if now>=self.shift_end:
                self.gear=self.pending_gear
                # 새 기어가 물리는 순간 wheel-linked RPM으로 즉시 떨어뜨려
                # 실제 자동변속기의 명확한 RPM drop을 만든다.
                self.rpm=min(self.rpm, self.rpm_for_gear(self.gear))
                self.shifting=False
            return
        kickdown_event = throttle>=float(self.t["kickdown_throttle"]) and self.prev_throttle<float(self.t["kickdown_throttle"])
        if kickdown_event and self.gear>1:
            target=float(self.t["kickdown_target_rpm"])
            for g in range(self.gear-1,0,-1):
                r=self.rpm_for_gear(g)
                if target<=r<=float(self.e["redline_rpm"]):
                    self.start_shift(g,now); return
        if rpm>=float(self.t["upshift_rpm"]) and self.gear<len(self.t["ratios"]):
            self.start_shift(self.gear+1,now)
        elif rpm<=float(self.t["downshift_rpm"]) and self.gear>1:
            self.start_shift(self.gear-1,now)

    def engine_target(self,throttle):
        idle=float(self.e["idle_rpm"]); red=float(self.e["redline_rpm"])
        if self.selector in {"P","N"}: return idle+throttle*(red-idle)*0.72
        rpm=self.wheel_rpm()*(float(self.t["ratios"][0])*0.85 if self.selector=="R" else float(self.t["ratios"][self.gear-1]))*float(self.t["final_drive"])
        if abs(self.speed_kph)<4: rpm += throttle*1400
        return clamp(rpm,idle,red)

    def update(self,throttle,brake,steering,dt):
        self.sim_time += dt
        now=self.sim_time
        throttle=clamp(float(throttle),0,1); brake=clamp(float(brake),0,1)
        self.transmission(throttle,now)
        self.prev_throttle=throttle
        self.rpm=approach(self.rpm,self.engine_target(throttle),float(self.e["inertia_response_per_s"])*900,dt)

        direction=1 if self.selector=="D" else (-1 if self.selector=="R" else 0)
        ratio=float(self.t["ratios"][self.gear-1]) if self.selector=="D" else (float(self.t["ratios"][0])*0.80 if self.selector=="R" else 0)
        drive=0.0
        if direction and throttle>0:
            tq=float(self.e["max_virtual_torque_nm"])*self.torque_factor(self.rpm)*throttle
            drive=tq*ratio*float(self.t["final_drive"])*float(self.v["drivetrain_efficiency"])/float(self.v["wheel_radius_m"])*direction
        if self.shifting: drive*=1.0-float(self.t["torque_cut_fraction"])

        resist=0.0
        if abs(self.speed_mps)>0.01:
            sign=1 if self.speed_mps>0 else -1
            resist=-(float(self.v["rolling_force_n"])+float(self.v["aero_drag_coeff"])*self.speed_mps**2)*sign
            if throttle<0.03 and self.selector in {"D","R"}:
                resist-=float(self.v["engine_brake_force_n"])*sign

        bforce=0.0 if abs(self.speed_mps)<=0.01 else -math.copysign(brake*float(self.v["max_brake_force_n"]),self.speed_mps)
        old=self.speed_mps
        new=old+(drive+resist+bforce)/float(self.v["mass_kg"])*dt
        if old>0 and new<0 and drive<=0: new=0
        if old<0 and new>0 and drive>=0: new=0
        if self.selector=="D" and new<0: new=0
        if self.selector=="R" and new>0: new=0
        maxf=float(self.s["max_forward_kph"])/3.6; maxr=float(self.s["max_reverse_kph"])/3.6
        self.speed_mps=clamp(new,-maxr,maxf)

        norm=self.speed_mps/(maxf if self.speed_mps>=0 else maxr)
        if abs(norm)>0.001:
            mn=float(self.m["min_effective_drive"])
            target=math.copysign(mn+(1-mn)*min(1,abs(norm)),norm)
        else: target=0.0
        if self.selector in {"P","N"}: target=0.0
        if self.shifting: target*=1.0-float(self.m["shift_output_drop"])
        rate=float(self.m["output_slew_up_per_s"] if abs(target)>abs(self.motor) else self.m["output_slew_down_per_s"])
        self.motor=approach(self.motor,target,rate,dt)
        return self.snapshot(throttle,brake,steering)

    def snapshot(self,throttle,brake,steering):
        return {
            "selector":self.selector,
            "gear":self.gear if self.selector=="D" else self.selector,
            "speed_kph":round(abs(self.speed_kph),2),
            "signed_speed_kph":round(self.speed_kph,2),
            "rpm":round(self.rpm),
            "throttle":round(throttle,4),"brake":round(brake,4),"steering":round(steering,4),
            "motor_output":round(self.motor,4),"shifting":self.shifting,
        }
