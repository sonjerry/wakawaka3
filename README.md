# RC Sim-Racing Car

Logitech Driving Force GT 또는 WASD로 Raspberry Pi 3 기반 RC카를 운전하는 프로젝트입니다.

## 구조

```text
Driving Force GT / WASD
          │
          ▼
Laptop Input Manager
          │
          ▼
Virtual Vehicle @ 100Hz
  ├─ virtual speed / inertia
  ├─ virtual engine RPM
  ├─ 6-speed automatic transmission
  ├─ shift torque cut / kickdown
  └─ virtual braking
          │
          ├────────────── Dashboard @ 30Hz
          │
          ▼
WebSocket control @ 50Hz
          │
          ▼
Raspberry Pi 3
  ├─ watchdog / failsafe
  ├─ PCA9685 @ 50Hz
  │    ├─ CH0 steering servo
  │    └─ CH1 RCXAZ brushed ESC
  └─ MediaMTX + CSI camera -> WebRTC
```

## 안전 전제

ESC 3핀은 다음과 같이 사용합니다.

```text
ESC SIGNAL -> PCA9685 CH1 signal
ESC +5V    -> 연결하지 않음
ESC GND    -> common GND
```

전원:

```text
2S LiPo 7.4V
 ├─ ESC -> DC motor
 └─ UBEC 5V
      ├─ Raspberry Pi
      └─ PCA9685 V+ -> steering servo

Pi 3.3V -> PCA9685 VCC
Pi GND -> PCA9685 GND -> ESC GND
```

PCA9685의 모든 채널은 주파수를 공유하므로 기본값은 50Hz입니다.

## 1. Pi 설치

```bash
git clone <YOUR_REPOSITORY_URL>
cd rc-simracing
chmod +x scripts/*.sh video/*.sh
./scripts/install_pi.sh
```

PCA9685 확인:

```bash
i2cdetect -y 1
```

기본 주소 `0x40`이 보여야 합니다.

## 2. ESC/서보 보정

`config/pi.yaml`을 수정합니다.

```yaml
steering:
  center_us: 1786
  left_us: 1100
  right_us: 1900

esc:
  neutral_us: 1500
  forward_min_us: 1540
  forward_max_us: 2000
  reverse_min_us: 1460
  reverse_max_us: 1000
```

이 값들은 시작값일 뿐입니다. 실제 RCXAZ ESC와 서보에 맞게 반드시 보정하십시오.

첫 테스트는 바퀴를 지면에서 띄운 상태로 진행하십시오.

## 3. Pi 제어 서버

```bash
./scripts/run_pi.sh
```

최신 `main`을 받은 뒤 바로 실행하려면 Pi의 프로젝트 폴더에서:

```bash
bash scripts/update_and_run_pi.sh
```

갱신에 실패하면 서버를 실행하지 않습니다. 이미 서버가 실행 중이라면 기존
터미널에서 `Ctrl+C`로 종료한 뒤 위 명령을 실행하세요.

상태 확인:

```text
http://<PI_IP>:8765/health
```

failsafe 기본값:

```text
300ms 동안 제어 명령 없음
→ ESC neutral
→ steering center
→ DISARM
```

ARM 버튼을 누른 뒤에도 1.5초 동안 neutral을 유지한 후 실제 armed 상태가 됩니다.

## 4. WebRTC 카메라

MediaMTX는 Raspberry Pi OS Bookworm/Trixie의 Raspberry Pi Camera native source를 사용하도록 구성했습니다.

```bash
./video/install_mediamtx.sh
./video/start_mediamtx.sh
```

브라우저에서:

```text
http://<PI_IP>:8889/cam
```

이 주소에 영상이 먼저 나오는지 확인합니다.

UI는 이 WebRTC 페이지를 iframe으로 삽입합니다.

## 5. 노트북 설치

PowerShell:

```powershell
.\scripts\install_laptop.ps1
```

`config/laptop.yaml`에서 Pi IP 수정:

```yaml
pi:
  host: "192.168.137.20"
```

실행:

```powershell
.\scripts\run_laptop.ps1
```

대시보드:

```text
http://127.0.0.1:8080
```

## 6. Driving Force GT

입력은 pygame joystick API를 사용합니다.

`config/input.yaml`:

```yaml
axes:
  steering: 0
  throttle: 2
  brake: 3
```

실제 Windows/드라이버 조합에서 축 번호가 다를 수 있습니다.

UI의 `INPUT DEBUG`에 raw axis 값이 표시됩니다. 핸들/악셀/브레이크를 각각 움직여 값이 변하는 축 번호를 확인한 후 설정만 수정하면 됩니다.

Driving Force GT가 감지되지 않으면 자동으로 WASD 모드가 됩니다.

WASD는 디지털 ON/OFF가 아니라 누르고 있는 시간에 따라 값이 증가합니다.

- W: throttle 증가
- S: brake 증가
- A/D: 조향 증가
- A/D를 놓으면 정차·후진 중에는 현재 조향각을 유지하고, 전진 중에만 차속에 비례해 서서히 중립으로 복귀

이전 화면에서 `STEER ANGLE +25°`일 때 바퀴가 정렬됐다는 관찰을 Pi 조향 중립값 1786µs로 반영했습니다. 이 값은 당시 저장된 조향 보정값 0µs와 화면 범위 ±35°를 기준으로 계산한 시작값이며, 실차 확인 전에는 확정된 서보 중립값이 아닙니다. 작동하지 않던 대시보드 보정 UI는 제거했습니다.

기어 단축키:

- 1 = P
- 2 = R
- 3 = N
- 4 = D

## 7. 차량 감성

`config/vehicle.yaml`에서 조정합니다.

핵심은 `악셀 -> PWM` 직접 매핑이 아닙니다.

```text
Throttle
  ↓
Virtual torque
  ↓
Gear ratio
  ↓
Acceleration
  ↓
Virtual speed
  ↓
ESC output
```

악셀을 놓으면 추진력만 사라지고 가상 차량 속도는 구름저항/공기저항/엔진브레이크에 따라 감소합니다. 따라서 실제 ESC 출력도 가상 속도가 내려가는 만큼 서서히 감소합니다.

브레이크도 속도를 순간적으로 0으로 만들지 않고 `max_brake_force_n`에 따라 감속시킵니다.

실물 ESC에는 브레이크 입력 시 역방향 신호를 보내지 않고 1500µs 중립을 보냅니다. 따라서 가상 차속은 브레이크에 따라 감속하지만 실차에는 별도 기계식 브레이크가 없어 실제 감속은 구름저항 등에 의존합니다. 크리핑은 화면상 모터 출력 7%로 표시하지만, Pi가 이를 기존 45% ESC 출력과 같은 전진 약 1747µs 펄스로 변환합니다. 화면 백분율과 ESC 신호 백분율은 서로 다릅니다.

## 8. 자동변속기

기본 6단:

```yaml
ratios: [3.60, 2.19, 1.52, 1.18, 0.95, 0.78]
```

지원:

- upshift RPM
- downshift RPM
- shift duration
- torque cut
- kickdown
- shift 시 실제 motor output 감소

기어가 바뀌면 새 기어비로 계산된 RPM으로 내려가므로 계기판 RPM도 실제 자동변속차처럼 단계적으로 떨어집니다.

## 9. P / R / N / D

- P: 실제 기계식 파킹락은 없음. motor neutral.
- R: reverse output.
- N: motor neutral. 가상 속도 관성은 유지.
- D: 1~6단 자동변속.

D↔R 변경은 가상 속도가 거의 0일 때만 허용합니다.

Pi ESC 드라이버도 전진↔후진 출력 사이에 neutral hold를 강제합니다.

## 10. UI 경고

가짜 엔진경고등 대신 프로젝트에 필요한 것만 표시합니다.

- CONTROL LINK
- INPUT
- 5V POWER / Pi undervoltage
- ESC ARMED
- FAILSAFE
- PI TEMP
- RTT latency

## 11. GitHub 디버깅

노트북:

```bash
git add .
git commit -m "adjust vehicle model"
git push
```

Pi:

```bash
git pull
./scripts/run_pi.sh
```

Pi에서 하드웨어 보정값을 수정했다면 반대로 commit/push하고 노트북에서 pull하면 됩니다.

## 가장 먼저 수정할 파일

1. `config/pi.yaml` — ESC/서보 pulse 보정
2. `config/input.yaml` — Driving Force GT 축 번호
3. `config/laptop.yaml` — Pi hotspot IP
4. `config/vehicle.yaml` — 주행 감성

## 첫 실차 테스트 순서

1. 구동 바퀴를 지면에서 띄움
2. Pi 제어 서버 실행
3. MediaMTX 실행
4. 노트북 대시보드 실행
5. 조향 방향/중립 확인
6. ESC neutral 확인
7. ARM
8. 낮은 throttle 테스트
9. brake 테스트
10. reverse 테스트
11. 바닥 주행
12. `vehicle.yaml` 감성 조정

## 시동 / 브레이크 인터록

대시보드는 OFF → SYSTEM CHECK → ENGINE ON 상태를 가집니다.

- 시동 OFF에서는 계기판과 카메라 클러스터가 어둡게 비활성화되고 Pi에는 강제 DISARM/neutral 명령이 전송됩니다.
- P 또는 N 상태에서 브레이크를 일정 이상 밟아야 START 버튼이 동작합니다.
- START 후 약 2.35초 동안 계기판 sweep 및 경고등 self-check가 실행됩니다.
- ENGINE ON 이후 Pi가 ESC armed 상태를 확인한 뒤 DRIVE READY가 됩니다.
- **P/R/N/D 사이의 모든 기어 변경은 브레이크를 밟고 있을 때만 허용됩니다.**
- 주행 중 D↔R 전환 및 주행 중 P 진입은 기존 속도 인터록으로 추가 차단됩니다.
- 시동 종료는 정지 상태 + P에서만 허용됩니다.
- EMERGENCY STOP은 즉시 ignition OFF + motor 0 + P + Pi DISARM 상태로 전환합니다.

기본 임계값은 `laptop/main.py` 상단에서 조정합니다.

```python
START_BRAKE_THRESHOLD = 0.20
GEAR_BRAKE_THRESHOLD = 0.18
```

## PCA9685 Python driver

Pi 제어부는 더 이상 Adafruit Blinka / lgpio를 사용하지 않습니다.
PCA9685는 `smbus2`로 I2C 레지스터를 직접 제어합니다.

따라서 Raspberry Pi Python 환경에는 다음 패키지가 필요하지 않습니다.

- `adafruit-blinka`
- `adafruit-lgpio`
- `lgpio`
- `RPi.GPIO`

Pi 의존성은 `aiohttp`, `PyYAML`, `smbus2`만 사용합니다.

## 1.3 Turbo / 9AT 가상 파워트레인 v3

가상 파워트레인은 Trailblazer 1.3 Turbo AWD의 9단 자동 구성을 기준으로 다시 작성했습니다.

- 9단 기어비: 4.689 / 3.306 / 3.012 / 2.446 / 1.923 / 1.446 / 1.000 / 0.747 / 0.617
- final drive: 3.17
- idle: 750 rpm
- 155 hp급 / 236 Nm(174 lb-ft)급 토크 곡선
- 토크컨버터 저속 slip + 속도/부하에 따른 lock-up
- 스로틀별 upshift/downshift map
- 변속 후 dwell + hysteresis로 gear hunting 방지
- 급가속 시 한 번에 여러 단을 내리는 kickdown
- 변속 중 ESC PWM 강제 drop 제거: 가속력만 부드럽게 줄고 차량 속도/모터 명령은 연속
- D/R creep
- 비선형 브레이크 페달과 저속 brake hold
- 감속 중 1단 launch gear 사전 선택
- 가상 0–60 mph 약 9초 수준
- ESC PWM은 가상 차속을 연속적으로 추종

`config/vehicle.yaml`에서 토크 곡선, 변속 맵, 토크컨버터, 브레이크, ESC 추종 특성을 조절할 수 있습니다.

### 계기판 바늘

RPM/속도 눈금, 숫자, 바늘은 모두 동일한 270도 수학적 스케일로 SVG에서 생성됩니다.
눈금 위치와 바늘 위치가 같은 `value → angle` 함수를 공유하므로 기존처럼 바늘이 눈금과 어긋나지 않습니다.


## v4 hardware-control changes

- ESC startup neutral handshake: 1500us for 3 seconds
- ESC forward range widened to 1540–2000us
- physical brake request now cuts ESC drive to neutral; reverse PWM is never used as a brake
- full-brake virtual deceleration increased
- steering straight-ahead reference is 1786µs, derived from the observed +25° old display position
- requested header / RTT / shift-lock / drive-ready text UI removed
- `/health` now exposes the actual ESC pulse and ESC mode for diagnosis

See `ESC_SETUP.md` for calibration details.
