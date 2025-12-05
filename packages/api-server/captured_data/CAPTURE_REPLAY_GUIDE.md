# RMF 데이터 캡처 및 재생 가이드

## 개요

이 시스템은 **ROS 2 시뮬레이션(ros2 launch) 없이도** API Server가 RMF 데이터를 보여줄 수 있도록 합니다.

### 목표
```
[실제 환경]
ros2 launch rmf_demos_gz office.launch.xml
        ↓
    ROS 2 토픽
        ↓
   API Server  →  Dashboard (실시간 데이터)

[재생 환경]
captured_data.json
        ↓
   replay.py (WebSocket 주입)
        ↓
   API Server  →  Dashboard (재생 데이터)
```

---

## 1. 데이터 흐름 이해

### 정상 환경에서의 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ros2 launch office.launch.xml                   │
│  (Gazebo 시뮬레이션 + RMF Fleet Adapter + RMF 스케줄러)             │
└─────────────────────────────────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
   ┌───────────┐            ┌───────────┐            ┌───────────────┐
   │ ROS 2     │            │ ROS 2     │            │ WebSocket     │
   │ Topics    │            │ Topics    │            │ /_internal    │
   └───────────┘            └───────────┘            └───────────────┘
   /door_states             /map                     Fleet Adapter에서
   /lift_states             (BuildingMap)            직접 전송
   /dispenser_states                                 - fleet_state
   /ingestor_states                                  - task_state
   /beacon_states
         │                         │                         │
         └─────────────────────────┼─────────────────────────┘
                                   ▼
                     ┌─────────────────────────────┐
                     │       API Server            │
                     │     (gateway.py)            │
                     │     (internal.py)           │
                     └─────────────────────────────┘
                                   │
                                   ▼
                     ┌─────────────────────────────┐
                     │       Dashboard             │
                     │  (맵, 로봇, 도어, 작업 표시) │
                     └─────────────────────────────┘
```

---

## 2. 캡처되는 데이터 유형

### ROS 2 토픽 (gateway.py에서 수신)

| 데이터 유형 | ROS 2 토픽 | 설명 | 예시 엔티티 |
|------------|-----------|------|------------|
| `building_map` | /map | 건물 맵 (층, 레인, 문, 엘리베이터 정의) | office 맵 |
| `door_state` | /door_states | 문 상태 (열림/닫힘) | main_door, coe_door |
| `lift_state` | /lift_states | 엘리베이터 상태 (층, 이동 상태) | Lift_01 |
| `dispenser_state` | /dispenser_states | 디스펜서 상태 | coke_dispenser |
| `ingestor_state` | /ingestor_states | 인제스터 상태 | coke_ingestor |
| `beacon_state` | /beacons | 비콘 상태 | beacon_01 |
| `delivery_alert` | /delivery_alerts | 배달 알림 | - |
| `fire_alarm_trigger` | /fire_alarm_trigger | 화재 알람 | - |

### WebSocket /_internal (Fleet Adapter에서 전송)

| 데이터 유형 | WebSocket 메시지 타입 | 설명 | 예시 |
|------------|---------------------|------|------|
| `fleet_state` | fleet_state_update | Fleet 및 로봇 상태 | deliveryRobot fleet (tinyRobot1, tinyRobot2) |
| `task_state` | task_state_update | 작업 상태 | delivery_001 (underway/completed) |
| `task_log` | task_log_update | 작업 로그 | 작업 이벤트 기록 |
| `fleet_log` | fleet_log_update | Fleet 로그 | Fleet 이벤트 기록 |

---

## 3. 캡처 방법

### 3-1. API Server 캡처 모드로 시작

```bash
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server

# 캡처 활성화 (5분간)
RMF_CAPTURE_DATA=1 \
RMF_CAPTURE_DURATION=300 \
RMF_CAPTURE_OUTPUT_DIR=./captured_data \
pnpm api-server
```

### 3-2. RMF 시뮬레이션 시작

```bash
# 다른 터미널에서
ros2 launch rmf_demos_gz office.launch.xml
```

### 3-3. 캡처 완료

5분 후 또는 Ctrl+C로 서버 종료 시 자동 저장됩니다.

```
============================================================
  RMF 데이터 캡처 요약
============================================================
  캡처 시작: 2025-12-04 10:47:26
  캡처 종료: 2025-12-04 10:52:26
  총 캡처 시간: 300.0초 (5.0분)
------------------------------------------------------------
  총 메시지 수: 38043
------------------------------------------------------------
  [데이터 유형별 메시지 수]
    building_map: 1개 (고유: 1개)
    door_state: 22824개 (고유: 3개)
    dispenser_state: 7609개 (고유: 2개)
    ingestor_state: 7609개 (고유: 2개)
    fleet_state: 500개 (고유: 1개)
    task_state: 100개 (고유: 5개)
------------------------------------------------------------
  [캡처된 엔티티 목록]
    Fleet 'deliveryRobot': 로봇 2대 (tinyRobot1, tinyRobot2)
    Task: 5개 (delivery_001, patrol_001, ...)
    Door: 3개 (main_door, coe_door, hardware_door)
    Building Map: office
    Dispenser: 2개 (coke_dispenser, coke_dispenser_2)
    Ingestor: 2개 (coke_ingestor, coke_ingestor_2)
------------------------------------------------------------
  저장 파일: ./captured_data/captured_data_20251204_104726.json
============================================================
```

---

## 4. 캡처 파일 구조

```json
{
  "_metadata": {
    "description": "RMF API Server에서 캡처된 실시간 데이터",
    "capture_start": "2025-12-04T10:47:26",
    "capture_end": "2025-12-04T10:52:26",
    "total_messages": 38043,
    "data_types": ["building_map", "door_state", "fleet_state", "task_state", ...]
  },

  "latest_states": {
    "building_map": {
      "office": { ... 전체 맵 데이터 ... }
    },
    "door_state": {
      "main_door": { "door_name": "main_door", "current_mode": {"value": 0} },
      "coe_door": { ... }
    },
    "fleet_state": {
      "deliveryRobot": {
        "name": "deliveryRobot",
        "robots": {
          "tinyRobot1": { "name": "tinyRobot1", "location": {...}, "battery": 0.95 },
          "tinyRobot2": { ... }
        }
      }
    },
    "task_state": {
      "delivery_001": { "booking": {...}, "status": "underway", ... }
    }
  },

  "history": {
    "door_state": [
      {"timestamp": "2025-12-04T10:47:26.510", "data": {...}},
      {"timestamp": "2025-12-04T10:47:26.610", "data": {...}},
      ...
    ],
    "fleet_state": [ ... ],
    "task_state": [ ... ]
  },

  "sample_format": {
    "building_map": { ... },
    "fleets": [ ... ],
    "tasks": [ ... ],
    "doors": [ ... ]
  }
}
```

---

## 5. 재생(Replay) 방법

### 5-1. API Server 일반 모드로 시작

```bash
# 캡처 없이 일반 모드로 시작
pnpm api-server
```

### 5-2. 캡처된 데이터 주입

```bash
# 최신 상태만 주입 (빠름)
python test_data/inject_captured_data.py captured_data/captured_data_20251204_104726.json

# 히스토리 시간순 재생 (느림, 실시간 시뮬레이션 효과)
python test_data/inject_captured_data.py captured_data/captured_data_20251204_104726.json --replay

# 5배속 재생
python test_data/inject_captured_data.py captured_data/captured_data_20251204_104726.json --replay --speed 5.0
```

### 5-3. Dashboard에서 확인

- http://localhost:3000 에서 맵, 로봇, 문, 작업 상태 확인

---

## 6. 재생 시 지원되는 메시지 타입

`inject_captured_data.py`가 API Server의 `/_internal` WebSocket으로 전송하는 메시지:

| 캡처된 데이터 | WebSocket 메시지 타입 | 설명 |
|-------------|---------------------|------|
| `fleet_state` | `fleet_state_update` | Fleet/로봇 상태 |
| `task_state` | `task_state_update` | 작업 상태 |
| `task_log` | `task_log_update` | 작업 로그 |
| `fleet_log` | `fleet_log_update` | Fleet 로그 |
| `door_state` | `door_state_update` | 문 상태 |
| `lift_state` | `lift_state_update` | 엘리베이터 상태 |
| `dispenser_state` | `dispenser_state_update` | 디스펜서 상태 |
| `ingestor_state` | `ingestor_state_update` | 인제스터 상태 |
| `beacon_state` | `beacon_state_update` | 비콘 상태 |

---

## 7. 주의사항

### 7-1. BuildingMap은 별도 처리 필요

BuildingMap은 WebSocket으로 주입할 수 없습니다. 대신:

1. **DB에 직접 저장** (권장)
   ```bash
   # API Server 시작 전에 맵 데이터를 DB에 미리 로드
   ```

2. **ROS 2 playback** (ROS 2 환경 필요)
   ```bash
   python test_data/playback_ros2.py captured_data/captured_data_*.json
   ```

### 7-2. Fleet/Task 데이터가 없는 경우

캡처 시점에 Fleet Adapter가 연결되어 있지 않으면 Fleet/Task 데이터가 캡처되지 않습니다.

- Fleet Adapter는 `ros2 launch` 시작 후 약 10-30초 후에 연결됩니다
- 캡처 시작 전에 시뮬레이션이 완전히 시작되었는지 확인하세요

### 7-3. 로봇 모션 재생

로봇의 실시간 이동을 재생하려면 `--replay` 옵션을 사용하세요:

```bash
# 실시간 속도로 재생 (로봇 이동이 자연스럽게 보임)
python test_data/inject_captured_data.py data.json --replay

# 5배속 재생 (빠른 확인용)
python test_data/inject_captured_data.py data.json --replay --speed 5.0
```

---

## 8. 파일 목록

| 파일 | 위치 | 설명 |
|------|------|------|
| `data_capture.py` | `api_server/` | 캡처 모듈 |
| `inject_captured_data.py` | `test_data/` | WebSocket 주입 스크립트 |
| `playback_ros2.py` | `test_data/` | ROS 2 토픽 재생 스크립트 |
| `captured_data_*.json` | `captured_data/` | 캡처된 데이터 파일 |

---

## 9. 전체 워크플로우 요약

```bash
# 1. 캡처
RMF_CAPTURE_DATA=1 pnpm api-server &
ros2 launch rmf_demos_gz office.launch.xml
# ... 5분 대기 ...
# Ctrl+C로 종료 → captured_data/*.json 생성됨

# 2. 재생
pnpm api-server &
python test_data/inject_captured_data.py captured_data/captured_data_*.json

# 3. Dashboard에서 확인
# http://localhost:3000
```

이제 ROS 2 시뮬레이션 없이도 캡처된 데이터로 Dashboard를 테스트할 수 있습니다!
