# RMF 데이터 캡처 및 재생 시스템

이 문서는 RMF API Server의 데이터 캡처 및 재생 기능에 대해 설명합니다.

## 개요

RMF 시스템에서 실시간으로 수신되는 데이터를 캡처하고, 나중에 ROS 2 없이도 재생할 수 있는 시스템입니다.

### 주요 기능
- **캡처 모드**: API Server 실행 중 모든 RMF 데이터를 JSON 파일로 저장
- **재생 모드**: 캡처된 데이터를 API Server에 주입하여 Dashboard에 표시
- **Trajectory 지원**: 로봇 경로(녹색 선) 데이터도 캡처/재생 가능

---

## 1. 데이터 캡처

### 1.1 캡처 모드 실행

```bash
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server

# 캡처 모드로 API Server 실행
RMF_CAPTURE_DATA=1 \
RMF_CAPTURE_DURATION=0 \
RMF_CAPTURE_OUTPUT_DIR=./captured_data \
RMF_API_SERVER_CONFIG=sqlite_local_config.py \
python -m api_server
```

### 1.2 환경 변수

| 환경 변수 | 설명 | 기본값 |
|-----------|------|--------|
| `RMF_CAPTURE_DATA` | 캡처 활성화 (`1` 또는 `true`) | 비활성화 |
| `RMF_CAPTURE_DURATION` | 캡처 시간(초), `0`=무제한 | `300` (5분) |
| `RMF_CAPTURE_OUTPUT_DIR` | 캡처 파일 저장 디렉토리 | `./captured_data` |

### 1.3 캡처 종료

- `Ctrl+C`로 서버 종료 시 자동으로 캡처 파일 저장
- 또는 지정된 `RMF_CAPTURE_DURATION` 시간 후 자동 저장

### 1.4 캡처 파일 위치

```
captured_data/
├── captured_data_20251204_222853.json      # 메인 데이터 파일
└── captured_data_20251204_222853_images/   # 맵 이미지 파일
    └── L1-office.z2jxgivpq22767zmmumdrchqyjx2s6ly.png
```

---

## 2. 데이터 재생

### 2.1 기본 재생 (최신 상태만 주입)

```bash
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server/test_data

# API Server 실행 (별도 터미널)
RMF_API_SERVER_CONFIG=sqlite_local_config.py python -m api_server

# 데이터 주입
python inject_captured_data.py ../captured_data/captured_data_20251204_222853.json
```

### 2.2 시간순 재생 (히스토리 재생)

```bash
# 10배속 재생
python inject_captured_data.py ../captured_data/captured_data_20251204_222853.json --replay --speed 10

# 100배속 재생 (빠른 테스트용)
python inject_captured_data.py ../captured_data/captured_data_20251204_222853.json --replay --speed 100

# 실시간 재생 (1배속)
python inject_captured_data.py ../captured_data/captured_data_20251204_222853.json --replay --speed 1
```

### 2.3 inject_captured_data.py 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `captured_file` | 캡처된 JSON 파일 경로 (필수) | - |
| `--api-url` | API Server URL | `http://localhost:8000` |
| `--replay` | 히스토리 시간순 재생 모드 | 비활성화 |
| `--speed` | 재생 속도 배수 | `1.0` |
| `--info-only` | 정보만 출력, 주입 안 함 | 비활성화 |
| `--cache-dir` | API 서버 캐시 디렉토리 | `../run/cache` |

### 2.4 정보 확인만 하기

```bash
python inject_captured_data.py ../captured_data/captured_data_20251204_222853.json --info-only
```

출력 예시:
```
============================================================
  캡처 데이터 정보
============================================================
  캡처 시작: 2025-12-04T22:28:53.533347
  캡처 종료: 2025-12-04T22:29:41.670303
  총 메시지: 448
  데이터 유형: fleet_state_ros2, building_map, fleet_state, door_state, ...
------------------------------------------------------------
  [최신 상태]
    fleet_state_ros2: 1개
    building_map: 1개
    fleet_state: 1개
    door_state: 3개
    ...
  [히스토리]
    fleet_state_ros2: 276개 메시지
    building_map: 1개 메시지
    fleet_state: 27개 메시지
    ...
  [Trajectory]
    L1: 1개 경로
============================================================
```

---

## 3. 캡처 데이터 구조

### 3.1 JSON 파일 최상위 구조

```json
{
  "_metadata": {
    "capture_start": "2025-12-04T22:28:53.533347",
    "capture_end": "2025-12-04T22:29:41.670303",
    "total_messages": 448,
    "data_types": ["fleet_state_ros2", "building_map", "fleet_state", ...],
    "images_dir": "captured_data_20251204_222853_images",
    "captured_images": ["L1-office.z2jxgivpq22767zmmumdrchqyjx2s6ly.png"]
  },
  "latest_states": { ... },
  "history": { ... },
  "sample_format": { ... }
}
```

### 3.2 캡처되는 데이터 유형

| 데이터 유형 | 소스 | 설명 |
|-------------|------|------|
| `fleet_state` | WebSocket `/_internal` | Fleet Adapter에서 전송하는 로봇 상태 (API Server 형식) |
| `fleet_state_ros2` | ROS 2 `/fleet_states` | ROS 2 토픽에서 직접 캡처한 로봇 상태 (path 포함) |
| `building_map` | WebSocket `/_internal` | 빌딩 맵 데이터 (레벨, 벽, 문, 리프트 정보) |
| `door_state` | ROS 2 `/door_states` | 문 상태 (열림/닫힘) |
| `lift_state` | ROS 2 `/lift_states` | 리프트 상태 |
| `dispenser_state` | ROS 2 `/dispenser_states` | 디스펜서 상태 |
| `ingestor_state` | ROS 2 `/ingestor_states` | 인제스터 상태 |
| `beacon_state` | WebSocket | 비콘 상태 |
| `task_state` | WebSocket `/_internal` | 작업 상태 |
| `task_log` | WebSocket `/_internal` | 작업 로그 |
| `fleet_log` | WebSocket `/_internal` | Fleet 로그 |
| `trajectory` | WebSocket `/trajectory` | 로봇 경로 데이터 (녹색 선) |

---

## 4. 데이터 형식 상세

### 4.1 fleet_state (API Server 형식)

```json
{
  "name": "tinyRobot",
  "robots": {
    "tinyRobot1": {
      "name": "tinyRobot1",
      "status": "idle",
      "task_id": "",
      "battery": 1.0,
      "location": {
        "map": "L1",
        "x": 10.43,
        "y": -5.57,
        "yaw": 1.32
      },
      "commission": {
        "direct_tasks": true,
        "dispatch_tasks": true,
        "idle_behavior": true
      },
      "mutex_groups": {
        "locked": [],
        "requesting": []
      },
      "issues": [],
      "unix_millis_time": 620
    }
  }
}
```

### 4.2 fleet_state_ros2 (ROS 2 형식)

```json
{
  "name": "tinyRobot",
  "robots": [
    {
      "name": "tinyRobot1",
      "model": "tinyRobot",
      "task_id": "",
      "seq": 0,
      "mode": {
        "mode": 0,
        "mode_request_id": 0,
        "performing_action": ""
      },
      "battery_percent": 100.0,
      "location": {
        "t": {"sec": 0, "nanosec": 600000000},
        "x": 10.43,
        "y": -5.57,
        "yaw": 1.32,
        "level_name": "L1",
        "index": 0
      },
      "path": [
        {"t": {...}, "x": 10.0, "y": -5.0, "yaw": 0.0, "level_name": "L1", "index": 1},
        {"t": {...}, "x": 15.0, "y": -5.0, "yaw": 0.0, "level_name": "L1", "index": 2}
      ]
    }
  ]
}
```

### 4.3 ROS 2 → API Server 형식 변환

`inject_captured_data.py`에서 자동으로 변환됩니다:

| ROS 2 형식 | API Server 형식 |
|------------|-----------------|
| `robots` (리스트) | `robots` (딕셔너리, 키=로봇이름) |
| `location.level_name` | `location.map` |
| `battery_percent` (0~100) | `battery` (0~1) |
| `mode.mode` (int) | `status` (string) |
| `location.t` (timestamp) | `unix_millis_time` |

**mode.mode 값:**
- `0` → `"idle"`
- `1` → `"charging"`
- `2` → `"moving"`
- `3` → `"paused"`
- `4` → `"waiting"`
- `5` → `"emergency"`

### 4.4 building_map

```json
{
  "name": "building",
  "levels": [
    {
      "name": "L1",
      "elevation": 0.0,
      "images": [
        {
          "name": "L1-office.z2jxgivpq22767zmmumdrchqyjx2s6ly.png",
          "x_offset": -12.52,
          "y_offset": -10.49,
          "yaw": 0.0,
          "scale": 0.05,
          "encoding": "png",
          "data": ""
        }
      ],
      "places": [...],
      "doors": [...],
      "nav_graphs": [...],
      "wall_graph": {...}
    }
  ],
  "lifts": [...],
  "default_graph_idx": 0
}
```

### 4.5 door_state

```json
{
  "door_time": {"sec": 1733318933, "nanosec": 533617000},
  "door_name": "hardware_door",
  "current_mode": {"value": 0}
}
```

**current_mode.value:**
- `0` → CLOSED
- `1` → MOVING
- `2` → OPEN

### 4.6 trajectory (로봇 경로)

```json
{
  "response": "trajectory",
  "values": [
    {
      "id": 0,
      "shape": "circle",
      "dimensions": 0.3,
      "segments": [
        {
          "t": 1733318934000000000,
          "v": [0.5, 0.0, 0.0],
          "x": [10.43, -5.57, 1.32]
        },
        {
          "t": 1733318936000000000,
          "v": [0.5, 0.0, 0.0],
          "x": [12.0, -5.57, 1.32]
        }
      ]
    }
  ],
  "conflicts": []
}
```

**segments 필드:**
- `t`: 타임스탬프 (나노초)
- `v`: 속도 벡터 `[vx, vy, vyaw]`
- `x`: 위치 `[x, y, yaw]`

---

## 5. Trajectory 시스템

### 5.1 아키텍처

```
Dashboard  ──WebSocket──>  API Server (/trajectory)  ──WebSocket──>  rmf_visualization_schedule (8006)
                                  │
                                  ├── 프록시 모드: 실제 서버로 전달
                                  ├── 캡처: 응답을 저장
                                  └── 재생 모드: 저장된 데이터 반환
```

### 5.2 Dashboard 설정

`packages/rmf-dashboard-framework/examples/demo/main.tsx`:
```tsx
<RmfDashboard
  apiServerUrl="http://localhost:8000"
  trajectoryServerUrl="ws://localhost:8000/trajectory"  // API Server 경유
  ...
/>
```

### 5.3 Trajectory 재생

`inject_captured_data.py`가 자동으로 trajectory 데이터를 주입합니다:

```bash
python inject_captured_data.py captured_data.json
# 출력:
# === Trajectory 데이터 주입 ===
#   WebSocket 연결 중: ws://localhost:8000/trajectory
#   ✓ WebSocket 연결됨
#   [trajectory] 'L1': 1개 경로 로드됨
```

---

## 6. 파일 구조

```
packages/api-server/
├── api_server/
│   ├── data_capture.py          # 캡처 로직
│   └── routes/
│       ├── internal.py          # /_internal WebSocket (데이터 주입 포인트)
│       └── trajectory.py        # /trajectory WebSocket 프록시
├── captured_data/               # 캡처된 데이터 저장 위치
│   └── captured_data_*.json
├── test_data/
│   ├── inject_captured_data.py  # 재생 스크립트
│   └── DATA_CAPTURE_REPLAY.md   # 이 문서
└── run/
    └── cache/
        └── building/            # 맵 이미지 캐시
```

---

## 7. 문제 해결

### 7.1 로봇이 표시되지 않음

1. API Server가 실행 중인지 확인:
   ```bash
   curl http://localhost:8000/time
   ```

2. 데이터가 주입되었는지 확인:
   ```bash
   curl -H "Authorization: Bearer <token>" http://localhost:8000/fleets
   ```

### 7.2 맵이 표시되지 않음

1. 이미지 파일이 캐시에 복원되었는지 확인:
   ```bash
   ls ../run/cache/building/
   ```

2. building_map이 주입되었는지 확인:
   ```bash
   curl -H "Authorization: Bearer <token>" http://localhost:8000/building_map
   ```

### 7.3 Trajectory(녹색 경로)가 표시되지 않음

1. Dashboard의 `trajectoryServerUrl`이 `ws://localhost:8000/trajectory`인지 확인

2. trajectory 데이터가 있는지 확인:
   ```bash
   python inject_captured_data.py captured_data.json --info-only
   # [Trajectory] 섹션 확인
   ```

### 7.4 ROS 2 형식 오류

`inject_captured_data.py`가 자동으로 ROS 2 형식을 API Server 형식으로 변환합니다.
변환이 실패하면 서버 로그에서 ValidationError를 확인하세요.

---

## 8. 관련 파일

- `api_server/data_capture.py`: 캡처 로직
- `api_server/routes/trajectory.py`: Trajectory 프록시/캡처/재생
- `api_server/routes/internal.py`: 데이터 주입 WebSocket
- `test_data/inject_captured_data.py`: 재생 스크립트

---

## 9. 빠른 시작 예제

### 전체 워크플로우

```bash
# 1. 캡처 (ROS 2 + Fleet Adapter 실행 중)
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server
RMF_CAPTURE_DATA=1 RMF_CAPTURE_DURATION=0 RMF_CAPTURE_OUTPUT_DIR=./captured_data \
  RMF_API_SERVER_CONFIG=sqlite_local_config.py python -m api_server

# (시뮬레이션 실행 후 Ctrl+C로 종료)

# 2. 재생 (ROS 2 없이)
# 터미널 1: API Server
RMF_API_SERVER_CONFIG=sqlite_local_config.py python -m api_server

# 터미널 2: 데이터 주입
cd test_data
python inject_captured_data.py ../captured_data/captured_data_*.json --replay --speed 10

# 3. Dashboard 접속
# http://localhost:3000
```
