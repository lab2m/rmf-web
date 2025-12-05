# RMF 캡처 데이터 플레이백 가이드

## 개요

캡처된 RMF 데이터를 API Server에 주입하여 재생하는 방법을 설명합니다.

## 사전 준비

1. API Server가 실행 중이어야 합니다
2. 캡처된 데이터 파일이 있어야 합니다 (`captured_data/*.json`)

---

## 방법 1: mock_rmf_server.py 사용 (권장)

### 1-1. 캡처 데이터에서 sample_format 추출

```bash
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server

# 캡처 파일에서 sample_format 추출
python3 -c "
import json
with open('captured_data/captured_data_20251204_022754.json') as f:
    data = json.load(f)
with open('test_data/playback_data.json', 'w') as f:
    json.dump(data['sample_format'], f, indent=2)
print('추출 완료: test_data/playback_data.json')
"
```

### 1-2. mock_rmf_server.py로 데이터 주입

```bash
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server/test_data

# 기본 실행 (1회 전송 후 종료)
python mock_rmf_server.py --data-file playback_data.json

# 또는 sample_data.json 사용 (Fleet/Task 데이터 포함)
python mock_rmf_server.py --data-file sample_data.json
```

### 출력 예시
```
============================================================
RMF Mock Server
============================================================
API URL: ws://localhost:8000/_internal
데이터 파일: sample_data.json
============================================================
✓ 데이터 로드됨: sample_data.json
연결 중: ws://localhost:8000/_internal
✓ 연결됨: ws://localhost:8000/_internal

모든 데이터 전송 중...

[Fleet 상태]
  [1] 전송: fleet_state_update
  [2] 전송: fleet_state_update

[Task 상태]
  [3] 전송: task_state_update
  [4] 전송: task_state_update
  [5] 전송: task_state_update

✓ 총 5개 메시지 전송 완료
```

---

## 방법 2: inject_captured_data.py 사용

캡처된 데이터를 직접 WebSocket으로 주입합니다.

### 2-1. 최신 상태만 주입 (기본)

```bash
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server

python test_data/inject_captured_data.py captured_data/captured_data_20251204_022754.json
```

### 2-2. 히스토리 시간순 재생

```bash
# 1배속 재생
python test_data/inject_captured_data.py captured_data/captured_data_20251204_022754.json --replay

# 2배속 재생
python test_data/inject_captured_data.py captured_data/captured_data_20251204_022754.json --replay --speed 2.0

# 5배속 재생
python test_data/inject_captured_data.py captured_data/captured_data_20251204_022754.json --replay --speed 5.0
```

### 2-3. 정보만 확인 (주입하지 않음)

```bash
python test_data/inject_captured_data.py captured_data/captured_data_20251204_022754.json --info-only
```

### 출력 예시
```
============================================================
  캡처 데이터 정보
============================================================
  캡처 시작: 2025-12-04T02:27:54.316683
  캡처 종료: 2025-12-04T02:28:04.347975
  총 메시지: 54
  데이터 유형: door_state, building_map, dispenser_state, ingestor_state
------------------------------------------------------------
  [최신 상태]
    door_state: 3개
    building_map: 1개
    dispenser_state: 2개
    ingestor_state: 2개
  [히스토리]
    door_state: 32개 메시지
    building_map: 1개 메시지
    dispenser_state: 10개 메시지
    ingestor_state: 11개 메시지
============================================================

API Server: http://localhost:8000
WebSocket: ws://localhost:8000/_internal

=== 최신 상태 주입 ===
  [fleet_state] fleet_1: 로봇 3대
  [task_state] task_delivery_001: underway

주입 완료!
```

---

## 방법 3: Python 스크립트로 직접 주입

### 3-1. 간단한 Fleet 상태 주입

```python
import asyncio
import json
import websockets

async def inject_fleet():
    uri = "ws://localhost:8000/_internal"

    fleet_data = {
        "type": "fleet_state_update",
        "data": {
            "name": "my_fleet",
            "robots": {
                "robot_1": {
                    "name": "robot_1",
                    "status": "idle",
                    "task_id": "",
                    "unix_millis_time": 1733300000000,
                    "location": {"map": "L1", "x": 5.0, "y": 5.0, "yaw": 0.0},
                    "battery": 0.95,
                    "issues": [],
                    "commission": {
                        "dispatch_tasks": True,
                        "direct_tasks": True,
                        "idle_behavior": True
                    },
                    "mutex_groups": {"locked": [], "requesting": []}
                }
            }
        }
    }

    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps(fleet_data))
        print("Fleet 상태 주입 완료!")

asyncio.run(inject_fleet())
```

### 3-2. 캡처 파일에서 데이터 주입

```python
import asyncio
import json
import websockets

async def inject_from_capture(capture_file: str):
    with open(capture_file) as f:
        data = json.load(f)

    uri = "ws://localhost:8000/_internal"
    latest = data.get("latest_states", {})

    async with websockets.connect(uri) as ws:
        # Fleet 상태 주입
        for fleet_name, fleet_data in latest.get("fleet_state", {}).items():
            msg = {"type": "fleet_state_update", "data": fleet_data}
            await ws.send(json.dumps(msg))
            print(f"Fleet 주입: {fleet_name}")

        # Task 상태 주입
        for task_id, task_data in latest.get("task_state", {}).items():
            msg = {"type": "task_state_update", "data": task_data}
            await ws.send(json.dumps(msg))
            print(f"Task 주입: {task_id}")

asyncio.run(inject_from_capture("captured_data/captured_data_20251204_022754.json"))
```

---

## 전체 워크플로우 예시

### 시나리오: 캡처 → 플레이백

```bash
# 1. API Server 시작 (캡처 활성화)
cd /home/lab2m-llm1/workspaces/rmf-web/packages/api-server
RMF_CAPTURE_DATA=1 RMF_CAPTURE_DURATION=300 python -m api_server

# 2. (별도 터미널) RMF 시뮬레이션 실행하여 데이터 생성
# ... 5분 후 캡처 자동 저장 ...

# 3. API Server 재시작 (캡처 없이)
RMF_API_SERVER_CONFIG=sqlite_local_config.py python -m api_server

# 4. (별도 터미널) 캡처된 데이터 플레이백
python test_data/inject_captured_data.py captured_data/captured_data_*.json --replay
```

---

## 데이터 유형별 주입 가능 여부

| 데이터 유형 | mock_rmf_server.py | inject_captured_data.py | playback_ros2.py | 비고 |
|------------|-------------------|------------------------|-----------------|------|
| fleet_state | ✓ | ✓ | ✗ | WebSocket /_internal |
| task_state | ✓ | ✓ | ✗ | WebSocket /_internal |
| task_log | ✓ | ✓ | ✗ | WebSocket /_internal |
| fleet_log | ✓ | ✓ | ✗ | WebSocket /_internal |
| door_state | ✓ | ✓ | ✓ | WebSocket 또는 ROS 2 |
| lift_state | ✓ | ✓ | ✓ | WebSocket 또는 ROS 2 |
| dispenser_state | ✓ | ✓ | ✓ | WebSocket 또는 ROS 2 |
| ingestor_state | ✓ | ✓ | ✓ | WebSocket 또는 ROS 2 |
| beacon_state | ✓ | ✓ | ✓ | WebSocket 또는 ROS 2 |
| building_map | ✗ | ✗ | ✓ | ROS 2 토픽 전용 |

> **참고**: 대부분의 데이터는 WebSocket `/_internal`을 통해 주입할 수 있습니다. ROS 2 환경이 있는 경우 `playback_ros2.py`를 사용할 수 있습니다.

---

## 주입된 데이터 확인

### API로 확인

```bash
# JWT 토큰 생성
TOKEN=$(python3 -c "
import jwt, time
print(jwt.encode({
    'preferred_username': 'admin',
    'aud': 'rmf_api_server',
    'iss': 'stub',
    'exp': int(time.time()) + 3600,
    'iat': int(time.time())
}, 'rmfisawesome', algorithm='HS256'))
")

# Fleet 확인
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/fleets | python3 -m json.tool

# Task 확인
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/tasks | python3 -m json.tool
```

---

## 문제 해결

### 연결 실패

```
오류: API Server에 연결할 수 없습니다: http://localhost:8000
```

**해결**: API Server가 실행 중인지 확인
```bash
curl http://localhost:8000/time
```

### 데이터가 주입되지 않음

1. WebSocket 경로 확인: `ws://localhost:8000/_internal`
2. 데이터 형식 확인: `type` 필드가 올바른지 확인
   - `fleet_state_update`
   - `task_state_update`
   - `task_log_update`
   - `fleet_log_update`
   - `door_state_update`
   - `lift_state_update`
   - `dispenser_state_update`
   - `ingestor_state_update`

### 캡처 데이터에 Fleet/Task가 없음

캡처 시점에 RMF Fleet Adapter가 연결되지 않았을 수 있습니다.
- ROS 2 데이터(door, lift 등)만 캡처됨
- Fleet/Task는 WebSocket /_internal로 들어와야 캡처됨

---

## 관련 파일

| 파일 | 경로 | 설명 |
|------|------|------|
| mock_rmf_server.py | `test_data/mock_rmf_server.py` | 샘플 데이터 주입 서버 |
| inject_captured_data.py | `test_data/inject_captured_data.py` | 캡처 데이터 주입 스크립트 |
| sample_data.json | `test_data/sample_data.json` | 샘플 테스트 데이터 |
| captured_data_*.json | `captured_data/` | 캡처된 데이터 파일 |
