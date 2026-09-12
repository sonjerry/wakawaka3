const $=id=>document.getElementById(id);let ws,keys={w:false,a:false,s:false,d:false},arm=false;
async function video(){try{let c=await fetch("/api/config").then(r=>r.json());$("cameraFrame").src=c.video_url;$("cameraHost").textContent=c.video_url.replace(/\?.*/,"")}catch{}}
function connect(){let p=location.protocol==="https:"?"wss":"ws";ws=new WebSocket(`${p}://${location.host}/ws`);ws.onopen=sendKeys;ws.onmessage=e=>{let d=JSON.parse(e.data);if(d.type==="state")render(d)};ws.onclose=()=>setTimeout(connect,800)}
function send(o){if(ws&&ws.readyState===1)ws.send(JSON.stringify(o))}function sendKeys(){send({type:"keys",state:keys})}function gear(g){send({type:"gear",gear:g})}
document.querySelectorAll(".gears button").forEach(b=>b.onclick=()=>gear(b.dataset.gear));
$("armBtn").onclick=()=>{arm=!arm;send({type:"arm",armed:arm})};$("estopBtn").onclick=()=>{arm=false;send({type:"estop"})};
let map={KeyW:"w",KeyA:"a",KeyS:"s",KeyD:"d"};
onkeydown=e=>{if(map[e.code]){e.preventDefault();keys[map[e.code]]=true;sendKeys()}if(!e.repeat){if(e.code==="Digit1")gear("P");if(e.code==="Digit2")gear("R");if(e.code==="Digit3")gear("N");if(e.code==="Digit4")gear("D")}};
onkeyup=e=>{if(map[e.code]){keys[map[e.code]]=false;sendKeys()}};onblur=()=>{keys={w:false,a:false,s:false,d:false};sendKeys()};
function cls(el,s){el.classList.remove("ok","bad");el.classList.add(s?"ok":"bad")}function warn(el,s){el.classList.remove("on","warn","bad");if(s)el.classList.add(s)}
function gauge(el,f){el.style.setProperty("--p",`${Math.max(0,Math.min(.78,f*.78))*100}%`)}
function render(d){let v=d.vehicle,i=d.input,l=d.link,p=d.pi||{};
 $("rpmValue").textContent=(v.rpm/1000).toFixed(1);$("speedValue").textContent=Math.round(v.speed_kph);$("gearValue").textContent=v.gear;$("steerValue").textContent=`${Math.round(v.steering*35)}°`;
 gauge($("rpmGauge"),v.rpm/6500);gauge($("speedGauge"),v.speed_kph/45);$("throttleBar").style.width=`${v.throttle*100}%`;$("brakeBar").style.width=`${v.brake*100}%`;$("motorBar").style.width=`${Math.abs(v.motor_output)*100}%`;
 let a=v.steering*28;$("fl").setAttribute("transform",`rotate(${a} 78 52)`);$("fr").setAttribute("transform",`rotate(${a} 162 52)`);document.querySelectorAll(".gears button").forEach(b=>b.classList.toggle("active",b.dataset.gear===v.selector));
 $("shiftBanner").textContent=v.shifting?"SHIFT":"";$("inputStatus").textContent=i.mode==="wheel"?`INPUT · ${i.device||"WHEEL"}`:"INPUT · WASD";cls($("inputStatus"),true);$("linkStatus").textContent=l.pi_connected?"CONTROL · ONLINE":"CONTROL · LOST";cls($("linkStatus"),l.pi_connected);$("latency").textContent=l.rtt_ms==null?"-- ms":`${l.rtt_ms.toFixed(1)} ms`;
 $("axisDebug").textContent="INPUT DEBUG: "+i.mode+" "+Object.entries(i.raw_axes||{}).map(([k,x])=>`A${k}:${x}`).join("  ");
 warn($("warnControl"),l.pi_connected?"on":"bad");warn($("warnInput"),"on");warn($("warnUndervolt"),p.undervoltage?"bad":"on");warn($("warnArmed"),p.armed?"on":"warn");warn($("warnFailsafe"),p.failsafe?"bad":"on");warn($("warnTemp"),p.cpu_temp_c>=75?"bad":"on");$("warnTemp").textContent=p.cpu_temp_c==null?"PI TEMP":`PI TEMP ${p.cpu_temp_c.toFixed(1)}°C`;
 arm=!!l.arm_requested;$("armBtn").classList.toggle("armed",!!p.armed);$("armBtn").textContent=p.armed?"ESC ARMED":(arm?"ARMING...":"ARM ESC")}
video();connect();
