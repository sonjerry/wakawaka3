const $ = id => document.getElementById(id);

let ws;
let reconnectTimer = null;
let keys = { w: false, a: false, s: false, d: false };
let videoLoaded = false;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

async function initVideo() {
  try {
    const cfg = await fetch('/api/config').then(r => r.json());
    const frame = $('cameraFrame');
    frame.src = cfg.video_url;
    frame.addEventListener('load', () => { videoLoaded = true; });
    $('cameraHost').textContent = cfg.video_url.replace(/\?.*$/, '');
  } catch {
    $('cameraHost').textContent = 'VIDEO CONFIG ERROR';
  }
}

function connect() {
  clearTimeout(reconnectTimer);
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = sendKeys;
  ws.onmessage = event => {
    const packet = JSON.parse(event.data);
    if (packet.type === 'state') render(packet);
  };
  ws.onclose = () => { reconnectTimer = setTimeout(connect, 700); };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function sendKeys() { send({ type: 'keys', state: keys }); }
function requestGear(gear) { send({ type: 'gear', gear }); }

$('startBtn').addEventListener('click', () => send({ type: 'ignition_toggle' }));
$('estopBtn').addEventListener('click', () => send({ type: 'estop' }));
document.querySelectorAll('.gear-btn').forEach(btn => btn.addEventListener('click', () => requestGear(btn.dataset.gear)));

const keyMap = { KeyW: 'w', KeyA: 'a', KeyS: 's', KeyD: 'd' };
window.addEventListener('keydown', event => {
  if (keyMap[event.code]) {
    event.preventDefault();
    keys[keyMap[event.code]] = true;
    sendKeys();
  }
  if (!event.repeat) {
    if (event.code === 'Digit1') requestGear('P');
    if (event.code === 'Digit2') requestGear('R');
    if (event.code === 'Digit3') requestGear('N');
    if (event.code === 'Digit4') requestGear('D');
  }
});
window.addEventListener('keyup', event => {
  if (keyMap[event.code]) {
    event.preventDefault();
    keys[keyMap[event.code]] = false;
    sendKeys();
  }
});
window.addEventListener('blur', () => {
  keys = { w: false, a: false, s: false, d: false };
  sendKeys();
});

function setTopChip(el, state) {
  el.classList.remove('ok', 'warn', 'bad', 'off');
  if (state) el.classList.add(state);
}

function setTile(el, state) {
  el.classList.remove('on', 'warn', 'bad');
  if (state) el.classList.add(state);
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const GAUGE_START_DEG = 135;
const GAUGE_SWEEP_DEG = 270;
const GAUGE_CX = 120;
const GAUGE_CY = 120;

function polar(cx, cy, radius, degrees) {
  const r = degrees * Math.PI / 180;
  return { x: cx + radius * Math.cos(r), y: cy + radius * Math.sin(r) };
}

function arcPath(cx, cy, radius, startDeg, endDeg) {
  if (endDeg <= startDeg + 0.001) return '';
  const start = polar(cx, cy, radius, startDeg);
  const end = polar(cx, cy, radius, endDeg);
  const span = endDeg - startDeg;
  const large = span > 180 ? 1 : 0;
  return `M ${start.x.toFixed(3)} ${start.y.toFixed(3)} A ${radius} ${radius} 0 ${large} 1 ${end.x.toFixed(3)} ${end.y.toFixed(3)}`;
}

function valueAngle(value, min, max) {
  const f = clamp((value - min) / Math.max(1e-9, max - min), 0, 1);
  return GAUGE_START_DEG + GAUGE_SWEEP_DEG * f;
}

function createSvg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function buildGauge(tickGroupId, baseArcId, options) {
  const group = $(tickGroupId);
  group.textContent = '';

  const { min, max, minorStep, majorStep, labelScale = 1, redFrom = null } = options;
  const count = Math.round((max - min) / minorStep);

  for (let i = 0; i <= count; i++) {
    const value = min + i * minorStep;
    const major = Math.abs((value / majorStep) - Math.round(value / majorStep)) < 1e-6;
    const angle = valueAngle(value, min, max);
    const inner = polar(GAUGE_CX, GAUGE_CY, major ? 92 : 97, angle);
    const outer = polar(GAUGE_CX, GAUGE_CY, 105, angle);
    const red = redFrom !== null && value >= redFrom;

    group.appendChild(createSvg('line', {
      x1: inner.x.toFixed(3), y1: inner.y.toFixed(3),
      x2: outer.x.toFixed(3), y2: outer.y.toFixed(3),
      class: `gauge-tick${major ? ' major' : ''}${red ? ' red' : ''}`
    }));

    if (major) {
      const label = polar(GAUGE_CX, GAUGE_CY, 77, angle);
      const text = createSvg('text', {
        x: label.x.toFixed(3),
        y: label.y.toFixed(3),
        class: `gauge-tick-label${red ? ' red' : ''}`
      });
      const shown = value / labelScale;
      text.textContent = Number.isInteger(shown) ? String(shown) : shown.toFixed(1);
      group.appendChild(text);
    }
  }

  $(baseArcId).setAttribute('d', arcPath(GAUGE_CX, GAUGE_CY, 105, GAUGE_START_DEG, GAUGE_START_DEG + GAUGE_SWEEP_DEG));
}

function setGauge(needleId, arcId, value, min, max) {
  const angle = valueAngle(value, min, max);
  $(needleId).style.transform = `rotate(${angle}deg)`;
  $(arcId).setAttribute('d', arcPath(GAUGE_CX, GAUGE_CY, 105, GAUGE_START_DEG, angle));
}

function initGauges() {
  buildGauge('rpmTicks', 'rpmBaseArc', {
    min: 0, max: 6500, minorStep: 250, majorStep: 1000, labelScale: 1000, redFrom: 6000
  });
  buildGauge('speedTicks', 'speedBaseArc', {
    min: 0, max: 200, minorStep: 5, majorStep: 20, labelScale: 1
  });
  $('rpmRedArc').setAttribute('d', arcPath(
    GAUGE_CX, GAUGE_CY, 105,
    valueAngle(6000, 0, 6500),
    valueAngle(6500, 0, 6500)
  ));
  setGauge('rpmNeedle', 'rpmArc', 0, 0, 6500);
  setGauge('speedNeedle', 'speedArc', 0, 0, 200);
}

function selectorName(selector) {
  return ({ P: 'PARK', R: 'REVERSE', N: 'NEUTRAL', D: 'DRIVE' })[selector] || selector;
}

function render(packet) {
  const vehicle = packet.vehicle || {};
  const input = packet.input || {};
  const link = packet.link || {};
  const pi = packet.pi || {};
  const ignition = packet.ignition || { state: 'off', elapsed_s: 0, boot_duration_s: 2.35 };
  const interlock = packet.interlock || {};

  const off = ignition.state === 'off';
  const boot = ignition.state === 'boot';
  const on = ignition.state === 'on';
  const brakeHeld = !!interlock.brake_held;
  const driveReady = !!link.drive_ready;

  let rpm = (vehicle.rpm || 0) / 1000;
  let speed = vehicle.speed_kph || 0;
  let steer = Math.round((vehicle.steering || 0) * 35);
  let throttle = vehicle.throttle || 0;
  let brake = input.brake || 0;
  let motor = Math.abs(vehicle.motor_output || 0);

  if (boot) {
    const t = clamp(ignition.elapsed_s / Math.max(.1, ignition.boot_duration_s), 0, 1);
    const sweep = t < .48 ? t / .48 : clamp(1 - ((t - .48) / .52), 0, 1);
    rpm = 6.5 * sweep;
    speed = 200 * sweep;
    steer = 0;
    throttle = 0;
    motor = 0;
    $('bootProgress').style.width = `${Math.round(t * 100)}%`;
  } else {
    $('bootProgress').style.width = '0%';
  }

  if (off) {
    rpm = 0; speed = 0; steer = 0; throttle = 0; motor = 0;
  }

  $('rpmValue').textContent = rpm.toFixed(1);
  $('speedValue').textContent = Math.round(speed);
  $('steerValue').textContent = `${steer}°`;
  $('gearValue').textContent = on ? (vehicle.display_gear ?? vehicle.gear) : 'P';
  $('selectorValue').textContent = selectorName(on ? vehicle.selector : 'P');

  setGauge('rpmNeedle', 'rpmArc', rpm * 1000, 0, 6500);
  setGauge('speedNeedle', 'speedArc', speed, 0, 200);

  const throttlePct = Math.round(throttle * 100);
  const brakePct = Math.round(brake * 100);
  const motorPct = Math.round(motor * 100);
  $('throttleBar').style.width = `${throttlePct}%`;
  $('brakeBar').style.width = `${brakePct}%`;
  $('motorBar').style.width = `${motorPct}%`;
  $('throttleValue').textContent = `${throttlePct}%`;
  $('brakeValue').textContent = `${brakePct}%`;
  $('motorValue').textContent = `${motorPct}%`;

  const wheelAngle = steer * .82;
  $('frontLeftWheel').setAttribute('transform', `rotate(${wheelAngle} 78 60)`);
  $('frontRightWheel').setAttribute('transform', `rotate(${wheelAngle} 182 60)`);

  const currentSelector = on ? vehicle.selector : 'P';
  document.querySelectorAll('.gear-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.gear === currentSelector);
    btn.classList.toggle('locked', !on || !brakeHeld);
  });

  $('gearLockText').textContent = brakeHeld && on ? 'SHIFT UNLOCKED' : 'BRAKE REQUIRED';
  $('brakeLock').classList.toggle('unlocked', brakeHeld && on);
  $('brakeLock').querySelector('strong').textContent = brakeHeld && on ? 'UNLOCKED' : 'LOCKED';

  $('shiftBanner').textContent = boot
    ? 'SYSTEM CHECK'
    : (vehicle.shifting ? `${vehicle.shift_from}  →  ${vehicle.shift_to}` : '');

  const inputName = input.mode === 'wheel' ? (input.device || 'DRIVING FORCE GT') : 'WASD';
  $('inputMode').textContent = inputName;
  $('inputStatus').querySelector('b').textContent = input.mode === 'wheel' ? 'WHEEL' : 'WASD';
  setTopChip($('inputStatus'), 'ok');

  $('linkStatus').querySelector('b').textContent = link.pi_connected ? 'CONTROL' : 'LINK LOST';
  setTopChip($('linkStatus'), link.pi_connected ? 'ok' : 'bad');

  $('videoStatus').querySelector('b').textContent = videoLoaded ? 'VIDEO' : 'VIDEO';
  setTopChip($('videoStatus'), videoLoaded ? 'ok' : 'warn');

  $('engineLamp').querySelector('b').textContent = off ? 'IGN OFF' : (boot ? 'SYSTEM CHECK' : 'ENGINE ON');
  setTopChip($('engineLamp'), off ? 'off' : (boot ? 'warn' : 'ok'));

  const rtt = link.rtt_ms == null ? '-- ms' : `${Number(link.rtt_ms).toFixed(1)} ms`;
  $('latency').textContent = rtt;
  $('rttValue').textContent = rtt;
  $('ignitionState').textContent = off ? 'OFF' : (boot ? 'CHECK' : 'ON');

  if (off) $('driveState').textContent = 'POWER OFF';
  else if (boot) $('driveState').textContent = 'SYSTEM CHECK';
  else if (!link.pi_connected) $('driveState').textContent = 'CONTROL OFFLINE';
  else if (!driveReady) $('driveState').textContent = 'ARMING';
  else $('driveState').textContent = 'DRIVE READY';

  const raw = input.raw_axes || {};
  $('axisDebug').textContent = 'INPUT DEBUG · ' + input.mode + ' · ' + Object.entries(raw).map(([k, v]) => `A${k}:${v}`).join('  ');
  $('noticeBox').textContent = packet.notice || '';

  if (boot) {
    ['warnControl','warnVideo','warnUndervolt','warnArmed','warnFailsafe','warnTemp'].forEach(id => setTile($(id), 'warn'));
  } else {
    setTile($('warnControl'), link.pi_connected ? 'on' : 'bad');
    setTile($('warnVideo'), videoLoaded ? 'on' : 'warn');
    setTile($('warnUndervolt'), pi.undervoltage ? 'bad' : 'on');
    setTile($('warnArmed'), driveReady ? 'on' : (on ? 'warn' : null));
    setTile($('warnFailsafe'), pi.failsafe ? 'bad' : 'on');
    setTile($('warnTemp'), pi.cpu_temp_c != null && pi.cpu_temp_c >= 75 ? 'bad' : 'on');
  }

  $('warnTemp').querySelector('b').textContent = pi.cpu_temp_c == null ? 'PI TEMP' : `${Number(pi.cpu_temp_c).toFixed(0)}°C`;

  document.body.classList.toggle('ignition-off', off);
  document.body.classList.toggle('ignition-boot', boot);
  document.body.classList.toggle('ignition-on', on);
  $('offOverlay').classList.toggle('show', off);
  $('bootOverlay').classList.toggle('show', boot);

  const start = $('startBtn');
  start.classList.toggle('ready', off && !!interlock.start_brake_held);
  start.classList.toggle('boot', boot);
  start.classList.toggle('on', on);
  $('startMain').textContent = boot ? 'CHECK' : (on ? 'STOP' : 'START');
  $('startSub').textContent = boot ? 'SYSTEM' : 'ENGINE';
  $('startHint').textContent = off ? (interlock.start_brake_held ? 'READY TO START' : 'HOLD BRAKE') : (boot ? 'PLEASE WAIT' : 'SHIFT TO P TO STOP');
}

initGauges();
initVideo();
connect();
