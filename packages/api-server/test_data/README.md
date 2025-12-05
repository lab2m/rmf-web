# RMF API Server 테스트 데이터 도구

이 디렉토리에는 RMF API Server를 테스트하기 위한 샘플 데이터와 도구들이 포함되어 있습니다.

## 파일 구조

```
test_data/
├── README.md                 # 이 파일
├── sample_data.json          # 미리 정의된 샘플 테스트 데이터
├── inject_test_data.py       # 샘플 데이터를 DB에 주입하는 스크립트
├── capture_live_data.py      # 실제 RMF에서 데이터를 캡처하는 스크립트
├── mock_rmf_server.py        # ROS 없이 API 서버에 데이터를 전송하는 Mock 서버
└── test_api_with_data.py     # API 테스트 스크립트
```

## 샘플 데이터 구조 (sample_data.json)

샘플 데이터에는 다음 엔티티들이 포함되어 있습니다:

| 엔티티 | 설명 | 예시 |
|--------|------|------|
| `building_map` | 빌딩 맵 (레벨, 장소, 문, 리프트) | test_building (L1, L2) |
| `fleets` | 로봇 Fleet 및 로봇 상태 | fleet_1 (robot_1, robot_2, robot_3), cleaning_fleet |
| `tasks` | 작업 상태 및 요청 | delivery, patrol 등 |
| `doors` | 문 상태 | main_entrance, office_door_1 |
| `lifts` | 리프트 상태 | main_elevator |
| `dispensers` | 디스펜서 상태 | dispenser_1, coke_dispenser |
| `ingestors` | 인제스터 상태 | ingestor_1, coke_ingestor |
| `alerts` | 알림 | 배터리 경고, 작업 완료 알림 |
| `beacons` | 비콘 상태 | beacon_L1_01, beacon_L2_01 |
| `users` | 사용자 | admin, test_user, viewer |
| `roles` | 역할 및 권한 | operator, viewer, supervisor |

## 사용법

### 1. 사전 요구사항

```bash
# 필요한 패키지 설치
pip install httpx websockets python-socketio[asyncio_client] aiohttp
```

### 2. 테스트 데이터 주입

#### 기본 사용 (인메모리 SQLite)
```bash
cd packages/api-server
python test_data/inject_test_data.py
```

#### SQLite 파일로 저장
```bash
python test_data/inject_test_data.py --db-url sqlite://./test_rmf.db
```

#### PostgreSQL에 주입
```bash
python test_data/inject_test_data.py --db-url postgres://user:password@localhost:5432/rmf_db
```

#### 커스텀 데이터 파일 사용
```bash
python test_data/inject_test_data.py --data-file my_custom_data.json
```

### 3. API 서버 내장 데이터 캡처 (권장)

API 서버 코드에 내장된 캡처 기능을 사용하여 실제 ROS 2에서 들어오는 모든 데이터를 캡처합니다.

```bash
# 캡처 모드로 API 서버 시작
RMF_CAPTURE_DATA=1 RMF_API_SERVER_CONFIG=sqlite_local_config.py python -m api_server

# 출력 디렉토리 지정 (기본값: ./captured_data)
RMF_CAPTURE_DATA=1 RMF_CAPTURE_OUTPUT_DIR=/path/to/output python -m api_server
```

**캡처되는 데이터:**
- **gateway.py (ROS 2)**: door_state, lift_state, dispenser_state, ingestor_state, building_map, beacon_state, alert, fire_alarm_trigger
- **internal.py (WebSocket)**: task_state, task_log, fleet_state, fleet_log

서버 종료 시 자동으로 `captured_data_{timestamp}.json` 파일로 저장됩니다.

### 4. 외부 캡처 스크립트 (capture_live_data.py)

API 서버 외부에서 Socket.IO 클라이언트로 데이터를 캡처합니다.

#### Socket.IO 실시간 캡처
```bash
python test_data/capture_live_data.py --duration 60 --token "YOUR_JWT_TOKEN"
```

#### REST API 스냅샷만 캡처
```bash
python test_data/capture_live_data.py --snapshot-only --token "YOUR_JWT_TOKEN"
```

캡처된 데이터는 다음 세 가지 형식으로 저장됩니다:
- `history`: 시간순 전체 이력
- `latest_states`: 각 엔티티의 최종 상태
- `sample_format`: `sample_data.json`과 호환되는 형식 (mock_rmf_server.py에서 사용 가능)

### 5. Mock RMF 서버 (mock_rmf_server.py)

ROS 2 없이 API 서버에 테스트 데이터를 전송합니다. API 서버의 `/_internal` WebSocket 엔드포인트로 데이터를 전송합니다.

#### 한 번만 데이터 전송
```bash
python test_data/mock_rmf_server.py
```

#### 시뮬레이션 모드 (주기적 업데이트)
```bash
# 5초마다 상태 업데이트 전송
python test_data/mock_rmf_server.py --simulate --interval 5
```

#### 대화형 모드
```bash
python test_data/mock_rmf_server.py -i
# 명령어: fleet, task, all, robot <fleet> <robot> <status>, quit
```

#### 캡처된 데이터 재생
```bash
# capture_live_data.py로 캡처한 데이터 사용
python test_data/mock_rmf_server.py --data-file captured_data.json
```

### 6. API 테스트 (test_api_with_data.py)

API 서버가 실행 중일 때 테스트합니다.

```bash
# 기본 테스트
python test_data/test_api_with_data.py

# 다른 URL 지정
python test_data/test_api_with_data.py --api-url http://192.168.1.100:8000

# 기대 데이터와 비교
python test_data/test_api_with_data.py --expected-data captured_data.json
```

## 데이터 흐름 이해

### API 서버 데이터 흐름 (테스트 도구 포함)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RMF 시스템                                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│  ROS 2 토픽   │  │  WebSocket   │  │   REST API       │
│  (gateway.py) │  │ (_internal)  │  │                  │
└──────┬───────┘  └──────┬───────┘  └────────┬─────────┘
       │                  ▲                   │
       │                  │                   │
       │         ┌────────┴────────┐          │
       │         │ mock_rmf_server │          │
       │         │    .py          │          │
       │         └────────┬────────┘          │
       │                  │                   │
       │ door_states      │ task_state_update │
       │ lift_states      │ task_log_update   │ POST /tasks/dispatch_task
       │ dispenser_states │ fleet_state_update│ POST /alerts/request
       │ ingestor_states  │ fleet_log_update  │
       │ map              │                   │
       │ beacon_state     │                   │
       │                  │                   │
       ▼                  ▼                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Tortoise ORM (Database)                         │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐ │
│  │TaskState │ │FleetState│ │ DoorState │ │ LiftState │ │BuildingM│ │
│  └──────────┘ └──────────┘ └───────────┘ └───────────┘ │   ap    │ │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐ └─────────┘ │
│  │AlertReq  │ │BeaconStat│ │Dispenser  │ │ Ingestor  │             │
│  └──────────┘ └──────────┘ └───────────┘ └───────────┘             │
└─────────────────────────────────────────────────────────────────────┘
       │                                                        ▲
       │                                               inject_test_data.py
       ▼                                                        │
┌─────────────────────────────────────────────────────────────────────┐
│                      RxPY Event Stream                              │
│                      (실시간 업데이트)                               │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                Socket.IO (/socket.io) + REST API                     │
│                      (프론트엔드로 전달)                             │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ capture_live_data.py   │
              │ (Socket.IO 클라이언트)  │
              └────────────────────────┘
```

### 테스트 워크플로우

```
1. 초기 데이터 설정:
   sample_data.json → inject_test_data.py → Database

2. 실시간 데이터 전송 (ROS 2 대체):
   sample_data.json → mock_rmf_server.py → /_internal WebSocket → API Server

3. 데이터 캡처:
   API Server → Socket.IO → capture_live_data.py → captured_data.json

4. 캡처 데이터 재생:
   captured_data.json → mock_rmf_server.py → API Server
```

### ROS 2 토픽 목록

| 토픽 | 메시지 타입 | 설명 |
|------|-------------|------|
| `door_states` | `rmf_door_msgs/DoorState` | 문 상태 |
| `lift_states` | `rmf_lift_msgs/LiftState` | 리프트 상태 |
| `dispenser_states` | `rmf_dispenser_msgs/DispenserState` | 디스펜서 상태 |
| `ingestor_states` | `rmf_ingestor_msgs/IngestorState` | 인제스터 상태 |
| `map` | `rmf_building_map_msgs/BuildingMap` | 빌딩 맵 |
| `beacon_state` | `rmf_fleet_msgs/BeaconState` | 비콘 상태 |
| `alert` | `rmf_task_msgs/Alert` | 알림 |
| `fire_alarm_trigger` | `std_msgs/Bool` | 화재 경보 |

### WebSocket 메시지 타입 (/_internal 입력)

mock_rmf_server.py가 API 서버로 전송하는 메시지 타입입니다.

| type | 설명 | 주요 필드 |
|------|------|----------|
| `task_state_update` | 작업 상태 업데이트 | booking.id, status, assigned_to |
| `task_log_update` | 작업 로그 업데이트 | task_id, phases, events |
| `fleet_state_update` | Fleet 상태 업데이트 | name, robots |
| `fleet_log_update` | Fleet 로그 업데이트 | name, log |

### Socket.IO 구독 Room (/socket.io 출력)

capture_live_data.py가 구독하는 Socket.IO room 목록입니다.

| Room | 설명 |
|------|------|
| `/building_map` | 빌딩 맵 업데이트 |
| `/fleets/{name}/state` | 특정 Fleet 상태 |
| `/fleets/{name}/log` | 특정 Fleet 로그 |
| `/tasks/{task_id}/state` | 특정 Task 상태 |
| `/tasks/{task_id}/log` | 특정 Task 로그 |
| `/doors/{door_name}/state` | 특정 Door 상태 |
| `/lifts/{lift_name}/state` | 특정 Lift 상태 |
| `/dispensers/{guid}/state` | 특정 Dispenser 상태 |
| `/ingestors/{guid}/state` | 특정 Ingestor 상태 |
| `/alerts/requests` | Alert 요청 |
| `/alerts/responses` | Alert 응답 |
| `/beacons` | Beacon 상태 |
| `/delivery_alerts` | 배송 알림 |

## 상태 코드 참조

### Task 상태 (task_state.status)
| 값 | 설명 |
|----|------|
| `uninitialized` | 초기화되지 않음 |
| `blocked` | 차단됨 |
| `error` | 오류 |
| `failed` | 실패 |
| `queued` | 대기열 |
| `standby` | 대기 |
| `underway` | 진행 중 |
| `delayed` | 지연 |
| `skipped` | 건너뜀 |
| `canceled` | 취소됨 |
| `killed` | 강제 종료 |
| `completed` | 완료 |

### Robot 상태 (robot_state.status)
| 값 | 설명 |
|----|------|
| `uninitialized` | 초기화되지 않음 |
| `offline` | 오프라인 |
| `shutdown` | 종료 중 |
| `idle` | 유휴 |
| `charging` | 충전 중 |
| `working` | 작업 중 |
| `error` | 오류 |

### Door 모드 (current_mode.value)
| 값 | 설명 |
|----|------|
| 0 | 닫힘 (MODE_CLOSED) |
| 1 | 이동 중 (MODE_MOVING) |
| 2 | 열림 (MODE_OPEN) |

### Alert Tier
| 값 | 설명 |
|----|------|
| `info` | 정보 |
| `warning` | 경고 |
| `error` | 오류 |

## 커스텀 샘플 데이터 작성

`sample_data.json`을 참고하여 커스텀 테스트 데이터를 작성할 수 있습니다.

```json
{
  "building_map": {
    "name": "my_building",
    "levels": [
      {
        "name": "L1",
        "elevation": 0.0,
        "images": [],
        "places": [
          {"name": "station_A", "x": 10.0, "y": 20.0, "yaw": 0.0, "position_tolerance": 0.3, "yaw_tolerance": 0.1}
        ],
        "doors": [],
        "nav_graphs": [],
        "wall_graph": {"name": "walls", "vertices": [], "edges": [], "params": []}
      }
    ],
    "lifts": []
  },
  "fleets": [
    {
      "name": "my_fleet",
      "robots": {
        "my_robot": {
          "name": "my_robot",
          "status": "idle",
          "task_id": "",
          "location": {"map": "L1", "x": 10.0, "y": 20.0, "yaw": 0.0},
          "battery": 0.8
        }
      }
    }
  ]
}
```

## 문제 해결

### "인증 필요" 오류
API 서버가 인증을 요구하는 경우입니다. `--api-url`에 인증 토큰을 포함하거나, 서버 설정에서 인증을 비활성화하세요.

### ROS 2 관련 import 오류
ROS 2 환경이 활성화되지 않았습니다:
```bash
source /opt/ros/humble/setup.bash
```

### 데이터베이스 연결 오류
데이터베이스 URL이 올바른지 확인하세요:
- SQLite: `sqlite://./test.db` 또는 `sqlite://:memory:`
- PostgreSQL: `postgres://user:pass@host:5432/dbname`

## 라이선스

이 도구들은 RMF Web 프로젝트의 일부입니다.
