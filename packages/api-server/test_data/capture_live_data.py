#!/usr/bin/env python3
"""
RMF API Server 데이터 캡처 스크립트

이 스크립트는 RMF API 서버에서 데이터를 캡처하여 JSON 파일로 저장합니다.
캡처된 데이터는 mock_rmf_server.py로 재생하여 테스트할 수 있습니다.

데이터 흐름:
  [RMF System] → [API Server /_internal] → [Database + RxPY Events]
                                                     ↓
  [This Script] ← [Socket.IO /socket.io] ← [Broadcast to clients]

캡처 방법:
  1. Socket.IO: 실시간 이벤트 스트림 캡처 (fleet, task, door, lift 등)
  2. REST API: 현재 상태 스냅샷 캡처

사용법:
    # Socket.IO로 실시간 캡처 (60초)
    python capture_live_data.py --duration 60

    # REST API 현재 상태만 캡처
    python capture_live_data.py --snapshot-only

    # 둘 다 캡처
    python capture_live_data.py --duration 60 --with-snapshot

    # JWT 토큰 사용 (인증 필요시)
    python capture_live_data.py --token "your_jwt_token"

출력 형식:
    - history: 시간순 전체 이력
    - latest_states: 각 엔티티의 최종 상태
    - sample_format: sample_data.json과 호환되는 형식 (mock_rmf_server.py에서 사용)
"""

import argparse
import asyncio
import json
import signal
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import socketio
except ImportError:
    print("❌ python-socketio 패키지가 필요합니다: pip install python-socketio[asyncio_client]")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("❌ httpx 패키지가 필요합니다: pip install httpx")
    sys.exit(1)


class DataCapture:
    """데이터 캡처 관리자"""

    def __init__(self, output_file: str):
        self.output_file = output_file
        self.captured_data: dict[str, list[dict]] = defaultdict(list)
        self.unique_data: dict[str, dict[str, dict]] = defaultdict(dict)
        self.start_time = datetime.now()
        self.message_count = 0

    def add_data(self, data_type: str, data: dict, unique_key: str | None = None):
        """데이터 추가"""
        timestamp = datetime.now().isoformat()
        entry = {
            "timestamp": timestamp,
            "data": data
        }
        self.captured_data[data_type].append(entry)

        if unique_key:
            self.unique_data[data_type][unique_key] = data

        self.message_count += 1
        key_info = f" [{unique_key}]" if unique_key else ""
        print(f"  [{self.message_count}] {data_type}{key_info}")

    def save(self):
        """캡처된 데이터를 JSON 파일로 저장"""
        output = {
            "_metadata": {
                "description": "RMF API Server에서 캡처된 데이터",
                "capture_start": self.start_time.isoformat(),
                "capture_end": datetime.now().isoformat(),
                "total_messages": self.message_count,
                "data_types": list(self.captured_data.keys())
            },
            "history": dict(self.captured_data),
            "latest_states": dict(self.unique_data),
            "sample_format": self._convert_to_sample_format()
        }

        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n✓ 데이터 저장 완료: {self.output_file}")
        print(f"  - 총 메시지 수: {self.message_count}")
        print(f"  - 데이터 유형: {', '.join(self.captured_data.keys()) or '없음'}")

    def _convert_to_sample_format(self) -> dict:
        """sample_data.json 형식으로 변환 (mock_rmf_server.py와 호환)"""
        sample = {}

        # Building Map
        if "building_map" in self.unique_data:
            maps = list(self.unique_data["building_map"].values())
            if maps:
                sample["building_map"] = maps[0]

        # Fleets
        if "fleet_state" in self.unique_data:
            sample["fleets"] = list(self.unique_data["fleet_state"].values())

        # Tasks
        if "task_state" in self.unique_data:
            tasks = []
            for task_id, state in self.unique_data["task_state"].items():
                tasks.append({"state": state})
            sample["tasks"] = tasks

        # Doors
        if "door_state" in self.unique_data:
            sample["doors"] = list(self.unique_data["door_state"].values())

        # Lifts
        if "lift_state" in self.unique_data:
            sample["lifts"] = list(self.unique_data["lift_state"].values())

        # Dispensers
        if "dispenser_state" in self.unique_data:
            sample["dispensers"] = list(self.unique_data["dispenser_state"].values())

        # Ingestors
        if "ingestor_state" in self.unique_data:
            sample["ingestors"] = list(self.unique_data["ingestor_state"].values())

        # Alerts
        if "alert_request" in self.unique_data:
            sample["alerts"] = list(self.unique_data["alert_request"].values())

        # Beacons
        if "beacon_state" in self.unique_data:
            sample["beacons"] = list(self.unique_data["beacon_state"].values())

        return sample


class SocketIOCapture:
    """Socket.IO를 통한 실시간 데이터 캡처"""

    def __init__(self, capture: DataCapture, api_url: str, token: str | None = None):
        self.capture = capture
        self.api_url = api_url
        self.token = token
        self.sio = socketio.AsyncClient()
        self.subscribed_rooms: list[str] = []
        self.running = False

        # Socket.IO 이벤트 핸들러 등록
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("subscribe", self._on_subscribe_response)

    async def _on_connect(self):
        print(f"✓ Socket.IO 연결됨: {self.api_url}")

    async def _on_disconnect(self):
        print("Socket.IO 연결 해제됨")

    async def _on_subscribe_response(self, data):
        if data.get("success"):
            print(f"  ✓ 구독 성공")
        else:
            print(f"  ✗ 구독 실패: {data.get('error', 'unknown')}")

    def _create_handler(self, data_type: str, key_extractor):
        """데이터 타입별 핸들러 생성"""
        async def handler(data):
            unique_key = key_extractor(data) if key_extractor else None
            self.capture.add_data(data_type, data, unique_key)
        return handler

    async def subscribe_to_rooms(self, rooms: list[dict]):
        """여러 room에 구독"""
        for room_info in rooms:
            room = room_info["room"]
            data_type = room_info["data_type"]
            key_extractor = room_info.get("key_extractor")

            # 해당 room의 이벤트 핸들러 등록
            handler = self._create_handler(data_type, key_extractor)
            self.sio.on(room, handler)

            # 구독 요청
            print(f"  구독 중: {room}")
            await self.sio.emit("subscribe", {"room": room})
            self.subscribed_rooms.append(room)
            await asyncio.sleep(0.1)  # 구독 요청 간 짧은 대기

    async def connect_and_capture(self, duration: float):
        """연결하고 캡처 시작"""
        self.running = True

        # 인증 정보
        auth = {"token": self.token} if self.token else None

        try:
            print(f"\nSocket.IO 연결 중: {self.api_url}")
            await self.sio.connect(
                self.api_url,
                auth=auth,
                transports=["websocket", "polling"]
            )

            # 구독할 room 목록
            # 특정 ID가 필요한 room은 REST API에서 먼저 목록을 가져와야 함
            rooms = [
                # Building Map
                {"room": "/building_map", "data_type": "building_map",
                 "key_extractor": lambda d: d.get("name")},
                # Alerts
                {"room": "/alerts/requests", "data_type": "alert_request",
                 "key_extractor": lambda d: d.get("id")},
                {"room": "/alerts/responses", "data_type": "alert_response",
                 "key_extractor": lambda d: d.get("id")},
                # Beacons
                {"room": "/beacons", "data_type": "beacon_state",
                 "key_extractor": lambda d: d.get("id")},
                # Delivery Alerts
                {"room": "/delivery_alerts", "data_type": "delivery_alert",
                 "key_extractor": lambda d: d.get("task_id")},
            ]

            await self.subscribe_to_rooms(rooms)

            # 동적으로 fleet, task 등 구독 (REST API에서 목록 가져오기)
            await self._subscribe_dynamic_rooms()

            print(f"\n캡처 중... ({duration}초)")
            print("(Ctrl+C로 조기 종료 가능)\n")

            # 지정된 시간 동안 대기
            await asyncio.sleep(duration)

        except Exception as e:
            print(f"오류: {e}")
        finally:
            self.running = False
            if self.sio.connected:
                await self.sio.disconnect()

    async def _subscribe_dynamic_rooms(self):
        """REST API에서 목록을 가져와 동적으로 구독"""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        async with httpx.AsyncClient() as client:
            # Fleets 구독
            try:
                resp = await client.get(f"{self.api_url}/fleets", headers=headers, timeout=10)
                if resp.status_code == 200:
                    fleets = resp.json()
                    for fleet in fleets:
                        fleet_name = fleet.get("name")
                        if fleet_name:
                            room = f"/fleets/{fleet_name}/state"
                            self.sio.on(room, self._create_handler(
                                "fleet_state",
                                lambda d: d.get("name")
                            ))
                            await self.sio.emit("subscribe", {"room": room})
                            print(f"  구독 중: {room}")
                            await asyncio.sleep(0.1)
            except Exception as e:
                print(f"  Fleet 목록 조회 실패: {e}")

            # Tasks 구독 (최근 작업)
            try:
                resp = await client.get(
                    f"{self.api_url}/tasks",
                    headers=headers,
                    params={"limit": 10},
                    timeout=10
                )
                if resp.status_code == 200:
                    tasks = resp.json()
                    for task in tasks:
                        task_id = task.get("booking", {}).get("id")
                        if task_id:
                            room = f"/tasks/{task_id}/state"
                            self.sio.on(room, self._create_handler(
                                "task_state",
                                lambda d: d.get("booking", {}).get("id")
                            ))
                            await self.sio.emit("subscribe", {"room": room})
                            print(f"  구독 중: {room}")
                            await asyncio.sleep(0.1)
            except Exception as e:
                print(f"  Task 목록 조회 실패: {e}")

            # Doors 구독
            try:
                resp = await client.get(f"{self.api_url}/doors", headers=headers, timeout=10)
                if resp.status_code == 200:
                    doors = resp.json()
                    for door in doors:
                        door_name = door.get("door_name")
                        if door_name:
                            room = f"/doors/{door_name}/state"
                            self.sio.on(room, self._create_handler(
                                "door_state",
                                lambda d: d.get("door_name")
                            ))
                            await self.sio.emit("subscribe", {"room": room})
                            print(f"  구독 중: {room}")
                            await asyncio.sleep(0.1)
            except Exception as e:
                print(f"  Door 목록 조회 실패: {e}")

            # Lifts 구독
            try:
                resp = await client.get(f"{self.api_url}/lifts", headers=headers, timeout=10)
                if resp.status_code == 200:
                    lifts = resp.json()
                    for lift in lifts:
                        lift_name = lift.get("lift_name")
                        if lift_name:
                            room = f"/lifts/{lift_name}/state"
                            self.sio.on(room, self._create_handler(
                                "lift_state",
                                lambda d: d.get("lift_name")
                            ))
                            await self.sio.emit("subscribe", {"room": room})
                            print(f"  구독 중: {room}")
                            await asyncio.sleep(0.1)
            except Exception as e:
                print(f"  Lift 목록 조회 실패: {e}")


async def capture_rest_snapshot(capture: DataCapture, api_url: str, token: str | None = None):
    """REST API에서 현재 상태 스냅샷 캡처"""
    print("\nREST API 스냅샷 캡처 중...")

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    endpoints = [
        ("/building_map", "building_map", lambda d: d.get("name") if d else None),
        ("/fleets", "fleet_state", lambda d: d.get("name")),
        ("/tasks", "task_state", lambda d: d.get("booking", {}).get("id")),
        ("/doors", "door_state", lambda d: d.get("door_name")),
        ("/lifts", "lift_state", lambda d: d.get("lift_name")),
        ("/dispensers", "dispenser_state", lambda d: d.get("guid")),
        ("/ingestors", "ingestor_state", lambda d: d.get("guid")),
        ("/beacons", "beacon_state", lambda d: d.get("id")),
        ("/alerts/requests", "alert_request", lambda d: d.get("id")),
    ]

    async with httpx.AsyncClient() as client:
        for endpoint, data_type, key_extractor in endpoints:
            try:
                resp = await client.get(f"{api_url}{endpoint}", headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        for item in data:
                            key = key_extractor(item) if key_extractor else None
                            capture.add_data(data_type, item, key)
                    elif data:
                        key = key_extractor(data) if key_extractor else None
                        capture.add_data(data_type, data, key)
                    print(f"  ✓ {endpoint}: 성공")
                elif resp.status_code == 401:
                    print(f"  ✗ {endpoint}: 인증 필요 (--token 옵션 사용)")
                else:
                    print(f"  ✗ {endpoint}: HTTP {resp.status_code}")
            except Exception as e:
                print(f"  ✗ {endpoint}: {e}")


async def main():
    parser = argparse.ArgumentParser(
        description="RMF API Server 데이터 캡처 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 60초 동안 Socket.IO 실시간 캡처
  python capture_live_data.py --duration 60

  # REST API 스냅샷만 캡처
  python capture_live_data.py --snapshot-only

  # JWT 토큰과 함께 캡처
  python capture_live_data.py --token "eyJhbG..." --duration 30

  # 출력 파일 지정
  python capture_live_data.py --output my_capture.json
"""
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="API 서버 URL (기본값: http://localhost:8000)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="캡처 기간 (초, 기본값: 60)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="출력 파일 경로"
    )
    parser.add_argument(
        "--token",
        default=None,
        help="JWT 인증 토큰"
    )
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="REST API 스냅샷만 캡처 (Socket.IO 없이)"
    )
    parser.add_argument(
        "--with-snapshot",
        action="store_true",
        help="Socket.IO 캡처와 함께 REST API 스냅샷도 캡처"
    )

    args = parser.parse_args()

    # 출력 파일 이름 생성
    if args.output:
        output_file = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = str(Path(__file__).parent / f"captured_data_{timestamp}.json")

    capture = DataCapture(output_file)

    # 시그널 핸들러
    stop_event = asyncio.Event()

    def signal_handler(sig, frame):
        print("\n\n캡처 중지 중...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("RMF API Server 데이터 캡처")
    print("=" * 60)
    print(f"API URL: {args.api_url}")
    print(f"출력 파일: {output_file}")
    print("=" * 60)

    try:
        if args.snapshot_only:
            # REST API 스냅샷만
            await capture_rest_snapshot(capture, args.api_url, args.token)
        else:
            # REST API 스냅샷 먼저 (옵션)
            if args.with_snapshot:
                await capture_rest_snapshot(capture, args.api_url, args.token)

            # Socket.IO 실시간 캡처
            sio_capture = SocketIOCapture(capture, args.api_url, args.token)

            # 캡처 태스크와 중지 이벤트 동시 실행
            capture_task = asyncio.create_task(
                sio_capture.connect_and_capture(args.duration)
            )

            # 중지 이벤트 또는 캡처 완료 대기
            done, pending = await asyncio.wait(
                [capture_task, asyncio.create_task(stop_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )

            # 나머지 태스크 취소
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except Exception as e:
        print(f"\n오류: {e}")

    # 데이터 저장
    capture.save()


if __name__ == "__main__":
    asyncio.run(main())
