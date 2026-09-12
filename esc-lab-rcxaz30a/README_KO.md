# RCXAZ 30A ESC Lab

정상 RC 프로젝트와 분리해서 **PCA9685 CH1 → ESC PWM만 실험**하는 환경입니다.

## 넣는 위치
ZIP 내용물을 `~/repos/wakawaka3` 루트에 복사합니다.

```bash
cd ~/repos/wakawaka3
chmod +x run_esc_lab.sh
```

## 실행
먼저 `scripts/run_pi.sh`를 Ctrl+C로 종료한 뒤:

```bash
cd ~/repos/wakawaka3
bash run_esc_lab.sh
```

브라우저:
```text
http://<PI_IP>:8770
```

## 기능
- 900~2100 µs 수동 출력
- 1000 / 1500 / 2000 µs 즉시 선택
- ESC 전원을 넣기 전에 MIN/CENTER/MAX를 미리 출력
- 사용자가 기억한 `1000(1초) → 2000(2초) → 1500(3초)` 실험
- 흔한 `2000(2초) → 1000(1초) → 1500(3초)` 후보 실험
- 양방향 3점 `1500 → 2000 → 1000 → 1500`
- 1400~1600 µs 중립점 미세 탐색
- PWM signal OFF
- 관찰 메모와 출력 이력 JSONL 저장

## 배선 전제
현재 프로젝트에서 쓰던 그대로:
- PCA9685 CH1 = ESC signal
- GND 공통
- ESC 수신기 케이블의 가운데 빨간 BEC +5V는 PCA9685에 연결하지 않음
- PCA9685 VCC = Pi 3.3V
- PCA9685 V+ = 별도 5V 서보 전원
- ESC 본체 = 2S 배터리

## 중요한 테스트법
ESC를 OFF한 상태에서 웹 UI의 `MIN 선출력`, `CENTER 선출력`, `MAX 선출력` 중 하나를 누른 다음 ESC를 켜십시오.
어느 시작점에서 예전의 초기화음/LED 패턴이 돌아오는지 확인하면 됩니다.

바퀴는 반드시 공중에 띄우십시오.
