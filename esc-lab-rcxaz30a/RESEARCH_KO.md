# 조사 요약

확인된 RCXAZ 30A Mini Brushed ESC 판매 사양:
- 4~8V, 2S LiPo
- Forward 30A / peak 40A
- Reverse 20A
- Brake 40A
- UBEC 약 5.7V 1A
- 130/180/260/280/380 brushed motor
- power switch 외에 'with / without brake' 물리 스위치가 있는 버전이 존재

중요한 점:
- 이 25x23x5mm 계열 판매 문서는 '새 송신기에서는 throttle trim을 중립에 맞춘다'고 설명합니다.
- 정확한 RCXAZ 30A mini용 endpoint 저장 절차는 공개 자료에서 명확히 확인되지 않았습니다.
- 반면 다른 PWM ESC 계열에서는 'MAX 선출력 후 전원 ON → 약 2초 → MIN → 약 1초' 방식이 매우 흔합니다.
- 사용자가 기억한 'MIN 1초 → MAX 2초 → CENTER'와 유사한 타이밍도 여러 ESC 계열에 존재합니다.

그래서 이 테스트 환경은 특정 절차 하나를 강제하지 않고 시작 PWM과 순서를 직접 바꿔가며 소리/LED를 관찰하도록 설계했습니다.
