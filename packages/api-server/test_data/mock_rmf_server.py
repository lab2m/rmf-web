#!/usr/bin/env python3
"""
RMF Mock Server - API 서버에 테스트 데이터를 전송하는 서버

이 서버는 실제 ROS 2 / RMF 시스템 없이 API 서버를 테스트할 수 있게 해줍니다.
API 서버의 /_internal WebSocket 엔드포인트로 데이터를 전송합니다.

데이터 흐름:
  [sample_data.json] → [mock_rmf_server.py] → WebSocket → [API Server /_internal]

사용법:
    # 기본 실행 (sample_data.json 사용)
    python mock_rmf_server.py

    # 커스텀 데이터 파일 사용
    python mock_rmf_server.py --data-file captured_data.json

    # API 서버 URL 지정
    python mock_rmf_server.py --api-url ws://localhost:8000/_internal

    # 주기적으로 데이터 전송 (시뮬레이션 모드)
    python mock_rmf_server.py --simulate --interval 5

WebSocket 메시지 형식 (/_internal):
    {
        "type": "task_state_update" | "task_log_update" | "fleet_state_update" | "fleet_log_update",
        "data": { ... }
    }
"""

import argparse
import asyncio
import json
import random
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import websockets
except ImportError:
    print("websockets 패키지가 필요합니다: pip install websockets")
    sys.exit(1)


class MockRmfServer:
    """RMF Mock 서버 - API 서버에 테스트 데이터 전송"""

    def __init__(self, api_url: str, data_file: str):
        self.api_url = api_url
        self.data_file = data_file
        self.data: dict = {}
        self.ws: Any = None
        self.running = False
        self.message_count = 0

    def load_data(self):
        """데이터 파일 로드"""
        with open(self.data_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        print(f"✓ 데이터 로드됨: {self.data_file}")

    async def connect(self):
        """WebSocket 연결"""
        print(f"연결 중: {self.api_url}")
        self.ws = await websockets.connect(self.api_url)
        print(f"✓ 연결됨: {self.api_url}")

    async def disconnect(self):
        """WebSocket 연결 해제"""
        if self.ws:
            await self.ws.close()
            print("연결 해제됨")

    async def send_message(self, msg_type: str, data: dict):
        """WebSocket 메시지 전송"""
        message = {
            "type": msg_type,
            "data": data
        }
        await self.ws.send(json.dumps(message))
        self.message_count += 1
        print(f"  [{self.message_count}] 전송: {msg_type}")

    async def send_fleet_states(self):
        """Fleet 상태 전송"""
        fleets = self.data.get("fleets", [])
        for fleet in fleets:
            await self.send_message("fleet_state_update", fleet)

    async def send_task_states(self):
        """Task 상태 전송"""
        tasks = self.data.get("tasks", [])
        for task in tasks:
            state = task.get("state", {})
            if state:
                await self.send_message("task_state_update", state)

    async def send_all_data_once(self):
        """모든 데이터 한 번 전송"""
        print("\n모든 데이터 전송 중...")

        # Fleet 상태
        print("\n[Fleet 상태]")
        await self.send_fleet_states()

        # Task 상태
        print("\n[Task 상태]")
        await self.send_task_states()

        print(f"\n✓ 총 {self.message_count}개 메시지 전송 완료")

    async def simulate(self, interval: float = 5.0):
        """시뮬레이션 모드 - 주기적으로 상태 업데이트 전송"""
        print(f"\n시뮬레이션 시작 (간격: {interval}초)")
        print("Ctrl+C로 중지")

        iteration = 0
        while self.running:
            iteration += 1
            print(f"\n--- 시뮬레이션 #{iteration} ---")

            # Fleet 상태 업데이트 (로봇 위치, 배터리 등 변경)
            await self.send_simulated_fleet_update()

            # Task 상태 업데이트
            await self.send_simulated_task_update()

            await asyncio.sleep(interval)

    async def send_simulated_fleet_update(self):
        """시뮬레이션된 Fleet 업데이트 전송"""
        fleets = self.data.get("fleets", [])
        for fleet in fleets:
            # 로봇 상태 약간 변경
            fleet_copy = json.loads(json.dumps(fleet))  # deep copy
            for robot_name, robot in fleet_copy.get("robots", {}).items():
                # 배터리 약간 변화
                if robot.get("battery"):
                    change = random.uniform(-0.01, 0.005)
                    robot["battery"] = max(0.0, min(1.0, robot["battery"] + change))

                # 위치 약간 변화 (working 상태인 경우)
                if robot.get("status") == "working" and robot.get("location"):
                    robot["location"]["x"] += random.uniform(-0.5, 0.5)
                    robot["location"]["y"] += random.uniform(-0.5, 0.5)

                # 시간 업데이트
                robot["unix_millis_time"] = int(time.time() * 1000)

            await self.send_message("fleet_state_update", fleet_copy)

    async def send_simulated_task_update(self):
        """시뮬레이션된 Task 업데이트 전송"""
        tasks = self.data.get("tasks", [])
        for task in tasks:
            state = task.get("state", {})
            if not state:
                continue

            # underway 상태인 task만 업데이트
            if state.get("status") == "underway":
                state_copy = json.loads(json.dumps(state))

                # estimate_millis 감소
                if state_copy.get("estimate_millis"):
                    state_copy["estimate_millis"] = max(
                        0, state_copy["estimate_millis"] - 5000
                    )

                await self.send_message("task_state_update", state_copy)

    async def run_once(self):
        """한 번만 데이터 전송"""
        self.load_data()
        await self.connect()
        try:
            await self.send_all_data_once()
        finally:
            await self.disconnect()

    async def run_simulate(self, interval: float):
        """시뮬레이션 모드 실행"""
        self.load_data()
        await self.connect()
        self.running = True
        try:
            await self.simulate(interval)
        finally:
            self.running = False
            await self.disconnect()

    def stop(self):
        """서버 중지"""
        self.running = False


class InteractiveMode:
    """대화형 모드 - 수동으로 데이터 전송"""

    def __init__(self, mock_server: MockRmfServer):
        self.server = mock_server

    async def run(self):
        """대화형 모드 실행"""
        self.server.load_data()
        await self.server.connect()

        print("\n" + "=" * 50)
        print("대화형 모드")
        print("=" * 50)
        print("명령어:")
        print("  fleet  - Fleet 상태 전송")
        print("  task   - Task 상태 전송")
        print("  all    - 모든 데이터 전송")
        print("  robot <fleet> <robot> <status> - 로봇 상태 변경")
        print("  quit   - 종료")
        print("=" * 50)

        try:
            while True:
                try:
                    cmd = input("\n명령> ").strip().lower()
                except EOFError:
                    break

                if cmd == "quit" or cmd == "q":
                    break
                elif cmd == "fleet":
                    await self.server.send_fleet_states()
                elif cmd == "task":
                    await self.server.send_task_states()
                elif cmd == "all":
                    await self.server.send_all_data_once()
                elif cmd.startswith("robot "):
                    parts = cmd.split()
                    if len(parts) >= 4:
                        await self.change_robot_status(parts[1], parts[2], parts[3])
                    else:
                        print("사용법: robot <fleet_name> <robot_name> <status>")
                        print("status: idle, working, charging, error, offline")
                else:
                    print("알 수 없는 명령어")
        finally:
            await self.server.disconnect()

    async def change_robot_status(self, fleet_name: str, robot_name: str, status: str):
        """로봇 상태 변경 및 전송"""
        fleets = self.server.data.get("fleets", [])
        for fleet in fleets:
            if fleet.get("name") == fleet_name:
                robots = fleet.get("robots", {})
                if robot_name in robots:
                    robots[robot_name]["status"] = status
                    robots[robot_name]["unix_millis_time"] = int(time.time() * 1000)
                    await self.server.send_message("fleet_state_update", fleet)
                    print(f"✓ {fleet_name}/{robot_name} 상태 변경: {status}")
                    return
        print(f"로봇을 찾을 수 없음: {fleet_name}/{robot_name}")


def create_sample_captured_data():
    """캡처된 데이터 형식의 샘플 생성"""
    return {
        "_metadata": {
            "description": "Mock RMF Server용 캡처 데이터",
            "captured_at": datetime.now().isoformat()
        },
        "fleets": [
            {
                "name": "fleet_1",
                "robots": {
                    "robot_1": {
                        "name": "robot_1",
                        "status": "idle",
                        "task_id": "",
                        "unix_millis_time": int(time.time() * 1000),
                        "location": {"map": "L1", "x": 5.0, "y": 5.0, "yaw": 0.0},
                        "battery": 0.95,
                        "issues": [],
                        "commission": {
                            "dispatch_tasks": True,
                            "direct_tasks": True,
                            "idle_behavior": True
                        },
                        "mutex_groups": {"locked": [], "requesting": []}
                    },
                    "robot_2": {
                        "name": "robot_2",
                        "status": "working",
                        "task_id": "task_001",
                        "unix_millis_time": int(time.time() * 1000),
                        "location": {"map": "L1", "x": 10.0, "y": 15.0, "yaw": 1.57},
                        "battery": 0.72,
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
        ],
        "tasks": [
            {
                "state": {
                    "booking": {
                        "id": "task_001",
                        "unix_millis_earliest_start_time": int(time.time() * 1000) - 60000,
                        "unix_millis_request_time": int(time.time() * 1000) - 120000,
                        "priority": {"value": 1},
                        "labels": ["app=mock_server"],
                        "requester": "mock_user"
                    },
                    "category": "delivery",
                    "detail": {"from": "station_A", "to": "station_B"},
                    "unix_millis_start_time": int(time.time() * 1000) - 60000,
                    "unix_millis_finish_time": None,
                    "original_estimate_millis": 300000,
                    "estimate_millis": 240000,
                    "assigned_to": {"group": "fleet_1", "name": "robot_2"},
                    "status": "underway",
                    "dispatch": {
                        "status": "dispatched",
                        "assignment": {
                            "fleet_name": "fleet_1",
                            "expected_robot_name": "robot_2"
                        },
                        "errors": None
                    },
                    "phases": {
                        "1": {
                            "id": 1,
                            "category": "Navigate",
                            "detail": {"destination": "station_B"},
                            "unix_millis_start_time": int(time.time() * 1000) - 60000,
                            "unix_millis_finish_time": None,
                            "original_estimate_millis": 300000,
                            "estimate_millis": 240000,
                            "final_event_id": 1,
                            "events": {
                                "1": {
                                    "id": 1,
                                    "status": "underway",
                                    "name": "Go to station_B",
                                    "detail": {},
                                    "deps": []
                                }
                            },
                            "skip_requests": None
                        }
                    },
                    "completed": [],
                    "active": 1,
                    "pending": [],
                    "interruptions": None,
                    "cancellation": None,
                    "killed": None
                }
            }
        ]
    }


async def main():
    parser = argparse.ArgumentParser(
        description="RMF Mock Server - API 서버에 테스트 데이터 전송"
    )
    parser.add_argument(
        "--api-url",
        default="ws://localhost:8000/_internal",
        help="API 서버 WebSocket URL (기본값: ws://localhost:8000/_internal)"
    )
    parser.add_argument(
        "--data-file",
        default=None,
        help="데이터 파일 경로 (기본값: sample_data.json)"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="시뮬레이션 모드 - 주기적으로 데이터 전송"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="시뮬레이션 간격 (초, 기본값: 5)"
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="대화형 모드"
    )
    parser.add_argument(
        "--create-sample",
        action="store_true",
        help="샘플 데이터 파일 생성"
    )

    args = parser.parse_args()

    # 샘플 데이터 생성
    if args.create_sample:
        sample_file = Path(__file__).parent / "mock_sample_data.json"
        with open(sample_file, "w", encoding="utf-8") as f:
            json.dump(create_sample_captured_data(), f, indent=2, ensure_ascii=False)
        print(f"샘플 데이터 생성됨: {sample_file}")
        return

    # 데이터 파일 경로 결정
    if args.data_file:
        data_file = args.data_file
    else:
        # 기본 경로들 시도
        possible_paths = [
            Path(__file__).parent / "sample_data.json",
            Path(__file__).parent / "mock_sample_data.json",
            Path(__file__).parent / "captured_data.json",
        ]
        data_file = None
        for p in possible_paths:
            if p.exists():
                data_file = str(p)
                break

        if not data_file:
            print("데이터 파일을 찾을 수 없습니다.")
            print("--data-file 옵션으로 지정하거나 --create-sample로 샘플을 생성하세요.")
            sys.exit(1)

    mock_server = MockRmfServer(args.api_url, data_file)

    # 시그널 핸들러
    def signal_handler(sig, frame):
        print("\n중지 중...")
        mock_server.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("RMF Mock Server")
    print("=" * 60)
    print(f"API URL: {args.api_url}")
    print(f"데이터 파일: {data_file}")
    print("=" * 60)

    try:
        if args.interactive:
            interactive = InteractiveMode(mock_server)
            await interactive.run()
        elif args.simulate:
            await mock_server.run_simulate(args.interval)
        else:
            await mock_server.run_once()
    except websockets.exceptions.ConnectionRefused:
        print(f"\n❌ 연결 실패: {args.api_url}")
        print("API 서버가 실행 중인지 확인하세요.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
