# RMF API Server 데이터 캡처 시스템

## 개요

이 시스템은 RMF(Robot Middleware Framework) API Server로 들어오는 모든 실시간 데이터를 캡처하여 JSON 파일로 저장합니다. 캡처된 데이터는 테스트, 디버깅, 재생 목적으로 활용할 수 있습니다.

## 목차

1. [시스템 아키텍처](#시스템-아키텍처)
2. [캡처 방법](#캡처-방법)
3. [캡처되는 데이터 상세](#캡처되는-데이터-상세)
4. [출력 파일 형식](#출력-파일-형식)
5. [캡처 데이터 예시](#캡처-데이터-예시)
6. [데이터 주입/재생](#데이터-주입재생)
7. [관련 파일](#관련-파일)

---

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           RMF System                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ROS 2 Topics      ┌──────────────────────────┐   │
│  │   ROS 2      │ ──────────────────────▶│     gateway.py           │   │
│  │   Nodes      │   door_states          │                          │   │
│  │              │   lift_states          │   capture_data() 호출    │   │
│  │  - rmf_core  │   dispenser_states     │          │               │   │
│  │  - fleet_mgr │   ingestor_states      └──────────┼───────────────┘   │
│  │  - door_mgr  │   building_map                    │                   │
│  │  - lift_mgr  │   beacon_state                    ▼                   │
│  └──────────────┘   fire_alarm          ┌──────────────────────────┐   │
│                                          │    data_capture.py       │   │
│  ┌──────────────┐     WebSocket          │    DataCaptureManager    │   │
│  │   Fleet      │ ──────────────────────▶│                          │   │
│  │   Adapter    │   /_internal           │    - _captured_data      │   │
│  │              │                        │    - _unique_data        │   │
│  │  task_state  │   task_state_update    │    - save()              │   │
│  │  fleet_state │   fleet_state_update   │    - _print_summary()    │   │
│  │  logs        │   task_log_update      │          │               │   │
│  └──────────────┘   fleet_log_update     └──────────┼───────────────┘   │
│                                  │                  │                   │
│                                  │                  ▼                   │
│                      ┌───────────┼──────────────────────────────────┐   │
│                      │           │      internal.py                 │   │
│                      │           │                                  │   │
│                      │           │      capture_data() 호출         │   │
│                      └───────────┴──────────────────────────────────┘   │
│                                                     │                   │
│                                                     ▼                   │
│                                          ┌──────────────────────────┐   │
│                                          │   captured_data/         │   │
│                                          │   captured_data_*.json   │   │
│                                          └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 캡처 방법

### 기본 사용법

```bash
# 기본 설정 (5분 캡처, ./captured_data에 저장)
RMF_CAPTURE_DATA=1 python -m api_server
```

### 환경 변수 상세

| 변수 | 기본값 | 설명 | 예시 |
|------|--------|------|------|
| `RMF_CAPTURE_DATA` | (비활성) | 캡처 활성화 플래그 | `1`, `true`, `yes` |
| `RMF_CAPTURE_OUTPUT_DIR` | `./captured_data` | 출력 디렉토리 경로 | `/tmp/rmf_capture` |
| `RMF_CAPTURE_DURATION` | `300` | 캡처 시간(초), 0=무제한 | `600` (10분) |

### 사용 예시

```bash
# 10분간 캡처
RMF_CAPTURE_DATA=1 RMF_CAPTURE_DURATION=600 python -m api_server

# 무제한 캡처 (Ctrl+C로 종료)
RMF_CAPTURE_DATA=1 RMF_CAPTURE_DURATION=0 python -m api_server

# 커스텀 출력 디렉토리
RMF_CAPTURE_DATA=1 RMF_CAPTURE_OUTPUT_DIR=/tmp/rmf_data python -m api_server

# 전체 옵션 조합
RMF_CAPTURE_DATA=1 \
RMF_CAPTURE_DURATION=300 \
RMF_CAPTURE_OUTPUT_DIR=./my_capture \
RMF_API_SERVER_CONFIG=sqlite_local_config.py \
python -m api_server
```

### 캡처 시작 시 로그

```
msg="데이터 캡처 활성화됨. 출력 디렉토리: ./captured_data"
msg="캡처 시간: 300초"
msg="300초 후 자동 저장됩니다."
```

### 캡처 완료 시 콘솔 출력

```
============================================================
  RMF 데이터 캡처 요약
============================================================
  캡처 시작: 2025-12-04 02:27:54
  캡처 종료: 2025-12-04 02:28:04
  총 캡처 시간: 10.0초 (0.2분)
------------------------------------------------------------
  총 메시지 수: 54
------------------------------------------------------------
  [데이터 유형별 메시지 수]
    building_map: 1개 (고유: 1개)
    dispenser_state: 10개 (고유: 2개)
    door_state: 32개 (고유: 3개)
    ingestor_state: 11개 (고유: 2개)
------------------------------------------------------------
  [캡처된 엔티티 목록]
    Door: 3개 (main_door, coe_door, hardware_door)
    Building Map: building
    Dispenser: 2개 (coke_dispenser, coke_dispenser_2)
    Ingestor: 2개 (coke_ingestor, coke_ingestor_2)
------------------------------------------------------------
  저장 파일: ./captured_data/captured_data_20251204_022754.json
============================================================
```

---

## 캡처되는 데이터 상세

### 1. ROS 2 토픽 데이터 (gateway.py)

| 데이터 유형 | ROS 2 토픽 | 설명 | 고유 키 |
|------------|-----------|------|--------|
| `door_state` | `/door_states` | 자동문 상태 (열림/닫힘/이동중) | `door_name` |
| `lift_state` | `/lift_states` | 엘리베이터 상태 (층, 문상태, 모드) | `lift_name` |
| `dispenser_state` | `/dispenser_states` | 물품 배출기 상태 | `guid` |
| `ingestor_state` | `/ingestor_states` | 물품 수거기 상태 | `guid` |
| `building_map` | `/map` | 건물 맵 정보 (층, 도어, 리프트 위치) | `name` |
| `beacon_state` | `/beacons` | 비콘 상태 | `id` |
| `alert_request` | `/alerts` | 알림 요청 | `id` |
| `fire_alarm_trigger` | `/fire_alarm_trigger` | 화재 경보 | - |

### 2. WebSocket 데이터 (internal.py - /_internal)

| 데이터 유형 | 메시지 타입 | 설명 | 고유 키 |
|------------|-----------|------|--------|
| `task_state` | `task_state_update` | 태스크 실행 상태 | `booking.id` |
| `task_log` | `task_log_update` | 태스크 실행 로그 | `task_id` |
| `fleet_state` | `fleet_state_update` | Fleet 상태 (로봇 목록 포함) | `name` |
| `fleet_log` | `fleet_log_update` | Fleet 로그 | `name` |

### 데이터 필드 상세

#### DoorState
```json
{
  "door_time": {"sec": 967, "nanosec": 590000000},
  "door_name": "main_door",
  "current_mode": {"value": 2}
}
```
- `current_mode.value`: 0=CLOSED, 1=MOVING, 2=OPEN

#### LiftState
```json
{
  "lift_time": {"sec": 100, "nanosec": 0},
  "lift_name": "main_elevator",
  "available_floors": ["L1", "L2", "L3"],
  "current_floor": "L1",
  "destination_floor": "L1",
  "door_state": 2,
  "motion_state": 0,
  "available_modes": [0],
  "current_mode": 0,
  "session_id": ""
}
```
- `door_state`: 0=CLOSED, 1=MOVING, 2=OPEN
- `motion_state`: 0=STOPPED, 1=UP, 2=DOWN

#### DispenserState / IngestorState
```json
{
  "time": {"sec": 100, "nanosec": 0},
  "guid": "coke_dispenser",
  "mode": 0,
  "request_guid_queue": [],
  "seconds_remaining": 0.0
}
```
- `mode`: 0=IDLE, 1=BUSY, 2=OFFLINE

#### FleetState
```json
{
  "name": "tinyRobot",
  "robots": {
    "robot1": {
      "name": "robot1",
      "status": "idle",
      "task_id": "",
      "unix_millis_time": 1733000000000,
      "location": {"map": "L1", "x": 10.5, "y": 20.3, "yaw": 1.57},
      "battery": 0.85
    }
  }
}
```

#### TaskState
```json
{
  "booking": {
    "id": "patrol_abc123",
    "unix_millis_earliest_start_time": 1733000000000,
    "unix_millis_request_time": 1733000000000,
    "priority": {"type": "binary", "value": 0},
    "requester": "admin"
  },
  "category": "patrol",
  "detail": {...},
  "unix_millis_start_time": 1733000000000,
  "status": "underway",
  "assigned_to": {"group": "tinyRobot", "name": "robot1"}
}
```
- `status`: "queued", "selected", "dispatched", "underway", "completed", "failed", "canceled"

#### BuildingMap
```json
{
  "name": "building",
  "levels": [
    {
      "name": "L1",
      "elevation": 0.0,
      "images": [...],
      "places": [...],
      "doors": [...],
      "nav_graphs": [...],
      "wall_graph": {...}
    }
  ],
  "lifts": [...]
}
```

---

## 출력 파일 형식

### 파일명 규칙
```
captured_data_{YYYYMMDD}_{HHMMSS}.json
```
예: `captured_data_20251204_022754.json`

### JSON 구조

```json
{
  "_metadata": {
    "description": "RMF API Server에서 캡처된 실시간 데이터",
    "capture_start": "2025-12-04T02:27:54.316683",
    "capture_end": "2025-12-04T02:28:04.347975",
    "total_messages": 54,
    "data_types": ["door_state", "building_map", "dispenser_state", "ingestor_state"]
  },

  "history": {
    "door_state": [
      {
        "timestamp": "2025-12-04T02:27:54.368181",
        "source": "gateway",
        "data": { ... }
      },
      ...
    ],
    "building_map": [...],
    "dispenser_state": [...],
    "ingestor_state": [...]
  },

  "latest_states": {
    "door_state": {
      "main_door": { ... },
      "coe_door": { ... },
      "hardware_door": { ... }
    },
    "building_map": {
      "building": { ... }
    },
    "dispenser_state": {
      "coke_dispenser": { ... },
      "coke_dispenser_2": { ... }
    },
    "ingestor_state": {
      "coke_ingestor": { ... },
      "coke_ingestor_2": { ... }
    }
  },

  "sample_format": {
    "building_map": { ... },
    "doors": [...],
    "dispensers": [...],
    "ingestors": [...]
  }
}
```

### 각 섹션 설명

| 섹션 | 설명 | 용도 |
|------|------|------|
| `_metadata` | 캡처 메타정보 | 캡처 시간, 통계 확인 |
| `history` | 시간순 전체 메시지 이력 | 시계열 분석, 디버깅 |
| `latest_states` | 각 엔티티의 최종 상태 | 현재 상태 스냅샷 |
| `sample_format` | mock_rmf_server.py 호환 형식 | 테스트 데이터 재생 |

---

## 캡처 데이터 예시

### 2025-12-04 캡처 세션

**캡처 환경:**
- 캡처 시간: 10초
- 데이터 소스: ROS 2 시뮬레이션 환경

**통계:**
| 항목 | 값 |
|------|-----|
| 총 메시지 수 | 54 |
| 캡처 시간 | 10.0초 |
| 데이터 유형 | 4종류 |

**캡처된 엔티티 상세:**

| 유형 | 총 메시지 | 고유 엔티티 | 엔티티 목록 |
|------|----------|-----------|------------|
| Door | 32 | 3 | `main_door`, `coe_door`, `hardware_door` |
| Building Map | 1 | 1 | `building` |
| Dispenser | 10 | 2 | `coke_dispenser`, `coke_dispenser_2` |
| Ingestor | 11 | 2 | `coke_ingestor`, `coke_ingestor_2` |

**Door 상태:**
| 도어 이름 | 상태 코드 | 상태 |
|----------|----------|------|
| main_door | 2 | OPEN (열림) |
| coe_door | 0 | CLOSED (닫힘) |
| hardware_door | 2 | OPEN (열림) |

**Building Map 구조:**
- 이름: `building`
- 층: `L1`
- 리프트: 없음

**Dispenser/Ingestor 상태:**
| 이름 | 유형 | 상태 코드 | 상태 |
|------|------|----------|------|
| coke_dispenser | Dispenser | 0 | IDLE (대기) |
| coke_dispenser_2 | Dispenser | 0 | IDLE (대기) |
| coke_ingestor | Ingestor | 0 | IDLE (대기) |
| coke_ingestor_2 | Ingestor | 0 | IDLE (대기) |

---

## 데이터 주입/재생

### 방법 1: mock_rmf_server.py 사용

캡처된 데이터를 `sample_format`으로 추출하여 재생:

```bash
# 1. sample_format 추출
python3 -c "
import json
with open('captured_data/captured_data_20251204_022754.json') as f:
    data = json.load(f)
with open('test_data/sample_data.json', 'w') as f:
    json.dump(data['sample_format'], f, indent=2)
"

# 2. API Server 시작 (별도 터미널)
RMF_API_SERVER_CONFIG=sqlite_local_config.py python -m api_server

# 3. mock_rmf_server.py로 데이터 주입
cd test_data
python mock_rmf_server.py --data-file sample_data.json
```

### 방법 2: inject_captured_data.py 사용

캡처된 데이터를 직접 API Server에 주입:

```bash
# API Server 실행 중인 상태에서
python test_data/inject_captured_data.py captured_data/captured_data_20251204_022754.json
```

### 방법 3: Python 스크립트로 분석

```python
import json

# 캡처 파일 로드
with open('captured_data/captured_data_20251204_022754.json') as f:
    data = json.load(f)

# 메타데이터 확인
print("=== 캡처 정보 ===")
print(f"시작: {data['_metadata']['capture_start']}")
print(f"종료: {data['_metadata']['capture_end']}")
print(f"총 메시지: {data['_metadata']['total_messages']}")

# Door 상태 이력 분석
print("\n=== Door 상태 이력 ===")
for entry in data['history']['door_state'][:5]:
    door = entry['data']
    mode = "OPEN" if door['current_mode']['value'] == 2 else "CLOSED"
    print(f"{entry['timestamp']}: {door['door_name']} = {mode}")

# 최종 상태 확인
print("\n=== 최종 Door 상태 ===")
for door_name, state in data['latest_states']['door_state'].items():
    mode = "OPEN" if state['current_mode']['value'] == 2 else "CLOSED"
    print(f"{door_name}: {mode}")

# Building Map 정보
print("\n=== Building Map ===")
if 'building_map' in data['sample_format']:
    bm = data['sample_format']['building_map']
    print(f"이름: {bm['name']}")
    print(f"층: {[l['name'] for l in bm['levels']]}")
```

---

## 관련 파일

### 소스 코드

| 파일 | 경로 | 설명 |
|------|------|------|
| data_capture.py | `api_server/data_capture.py` | 캡처 모듈 (DataCaptureManager 클래스) |
| gateway.py | `api_server/gateway.py` | ROS 2 토픽 캡처 훅 |
| internal.py | `api_server/routes/internal.py` | WebSocket 캡처 훅 |

### 테스트 도구

| 파일 | 경로 | 설명 |
|------|------|------|
| mock_rmf_server.py | `test_data/mock_rmf_server.py` | 캡처 데이터 재생 서버 |
| inject_captured_data.py | `test_data/inject_captured_data.py` | 캡처 데이터 주입 스크립트 |
| sample_data.json | `test_data/sample_data.json` | 샘플 테스트 데이터 |

### 캡처 데이터

| 파일 | 경로 | 설명 |
|------|------|------|
| captured_data_*.json | `captured_data/` | 캡처된 JSON 파일 |

---

## 문제 해결

### 캡처가 시작되지 않는 경우

1. 환경 변수 확인:
```bash
echo $RMF_CAPTURE_DATA  # 1, true, yes 중 하나여야 함
```

2. 출력 디렉토리 권한 확인:
```bash
ls -la ./captured_data
```

### 데이터가 캡처되지 않는 경우

1. ROS 2 토픽 발행 확인:
```bash
ros2 topic list
ros2 topic echo /door_states
```

2. WebSocket 연결 확인:
```bash
# /_internal WebSocket이 연결되어 있는지 확인
curl http://localhost:8000/time
```

### 파일이 저장되지 않는 경우

1. 디스크 공간 확인:
```bash
df -h .
```

2. 캡처 로그 확인:
```bash
RMF_CAPTURE_DATA=1 python -m api_server 2>&1 | grep "캡처"
```
