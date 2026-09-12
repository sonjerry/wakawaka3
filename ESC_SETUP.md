# RCXAZ / generic 30A brushed ESC setup

이 프로젝트는 2S LiPo, 약 30A brushed, 5.7V/1A BEC 계열의 소형 Forward/Reverse/Brake ESC를 기준으로 합니다.

## 적용한 시작 로직

1. Raspberry Pi 제어 서버가 시작되면 PCA9685 CH1에 **1500us 중립**을 즉시 출력합니다.
2. 3초 동안 중립을 계속 유지합니다.
3. 이 시간이 끝나기 전에는 어떤 구동 명령도 ESC로 보내지 않습니다.
4. 이후 START/STOP 시동이 ON일 때만 구동 출력을 허용합니다.
5. 통신이 300ms 이상 끊기면 즉시 1500us 중립으로 돌아갑니다.

이 ESC 계열은 송신기의 TH TRIM을 중앙(중립)으로 맞춰 쓰는 방식이 문서화되어 있어, 문서에 없는 풀스로틀 자동 캘리브레이션 시퀀스는 넣지 않았습니다.

## 기본 펄스

- neutral: 1500us
- forward start: 1540us
- forward max: 2000us
- reverse/brake start: 1460us
- reverse/brake max: 1000us

모터 방향이 반대면 모터 두 선을 서로 바꾸는 것이 가장 단순합니다. 또는 `config/pi.yaml`의 `invert_direction`을 변경할 수 있습니다.

## 브레이크

`active_brake: true`일 때 전진 중 브레이크를 밟으면 중립 반대쪽 펄스를 사용하여 ESC 브레이크를 요청합니다.
ESC에 물리적인 BRAKE ON/OFF 스위치가 있는 모델은 **BRAKE를 ON**으로 두십시오.

## 조향 센터

현재 좌측 쏠림 보정값:

```yaml
steering:
  center_us: 1500
  center_trim_us: 45
```

`center_trim_us`를 + 방향으로 올리면 현재 배선/방향 기준 우측으로 보정됩니다. 실제 기구차가 남으면 5~10us 단위로 조정하십시오.

## 상태 확인

서버 실행 후:

```text
http://<PI_IP>:8765/health
```

응답에서 다음 값을 확인할 수 있습니다.

- `esc_ready`
- `drive_enabled`
- `esc_pulse_us`
- `esc_mode`
- `steering_center_us`

풀악셀 때 `esc_pulse_us`가 2000us 부근까지 변하는지 확인할 수 있습니다.
