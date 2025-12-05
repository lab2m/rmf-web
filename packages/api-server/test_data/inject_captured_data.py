#!/usr/bin/env python3
"""
캡처된 데이터를 API Server에 주입하는 스크립트

사용법:
    python inject_captured_data.py <captured_data.json> [options]

예시:
    python inject_captured_data.py ../captured_data/captured_data_20251204_022754.json
    python inject_captured_data.py ../captured_data/captured_data_20251204_022754.json --replay
    python inject_captured_data.py ../captured_data/captured_data_20251204_022754.json --api-url http://localhost:8000

Trajectory 데이터:
    캡처 파일에 trajectories가 포함된 경우, API Server의 /trajectory 엔드포인트
    내부 저장소에 로드됩니다. Dashboard가 ws://localhost:8000/trajectory로 연결하면
    이 데이터가 반환됩니다.
"""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import websockets


def restore_images(data: dict, captured_file: Path, cache_dir: Path) -> None:
    """캡처된 이미지 파일을 캐시 디렉토리로 복원"""
    metadata = data.get("_metadata", {})
    images_dir_path = metadata.get("images_dir")
    captured_images = metadata.get("captured_images", [])

    if not captured_images:
        return

    # images_dir가 상대 경로인 경우 처리
    if images_dir_path:
        images_dir = Path(images_dir_path)
        if not images_dir.is_absolute():
            images_dir = captured_file.parent / images_dir.name
    else:
        # 기본값: captured_data_{timestamp}_images
        images_dir = captured_file.parent / f"{captured_file.stem}_images"

    if not images_dir.exists():
        print(f"  경고: 이미지 디렉토리 없음: {images_dir}")
        return

    # 캐시 디렉토리 생성
    building_cache = cache_dir / "building"
    building_cache.mkdir(parents=True, exist_ok=True)

    print(f"\n=== 이미지 파일 복원 ===")
    print(f"  소스: {images_dir}")
    print(f"  대상: {building_cache}")

    restored = 0
    for img_file in captured_images:
        src = images_dir / img_file
        dst = building_cache / img_file
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ {img_file}")
            restored += 1
        else:
            print(f"  ✗ {img_file} (파일 없음)")

    print(f"  총 {restored}개 이미지 복원됨")


def _convert_ros2_robot_state(robot: dict) -> dict:
    """ROS 2 robot_state를 API Server 형식으로 변환

    ROS 2 robot_state:
    - location.level_name, location.t (timestamp)
    - battery_percent (0~100)
    - mode.mode (int)

    API Server robot_state:
    - location.map
    - battery (0~1)
    - status (string)
    """
    converted = {}

    # 기본 필드 복사
    converted["name"] = robot.get("name", "")
    converted["task_id"] = robot.get("task_id", "")

    # battery 변환 (0~100 → 0~1)
    battery_percent = robot.get("battery_percent", 100.0)
    converted["battery"] = battery_percent / 100.0

    # location 변환
    location = robot.get("location", {})
    converted["location"] = {
        "map": location.get("level_name", location.get("map", "")),
        "x": location.get("x", 0.0),
        "y": location.get("y", 0.0),
        "yaw": location.get("yaw", 0.0),
    }

    # mode → status 변환
    mode = robot.get("mode", {})
    mode_val = mode.get("mode", 0) if isinstance(mode, dict) else 0
    mode_map = {
        0: "idle",
        1: "charging",
        2: "moving",
        3: "paused",
        4: "waiting",
        5: "emergency",
    }
    converted["status"] = mode_map.get(mode_val, "idle")

    # path 유지 (ROS 2에서 가져온 중요한 데이터)
    if "path" in robot:
        converted["path"] = robot["path"]

    # 기타 기본 필드
    converted["commission"] = robot.get("commission", {
        "direct_tasks": True,
        "dispatch_tasks": True,
        "idle_behavior": True,
    })
    converted["mutex_groups"] = robot.get("mutex_groups", {
        "locked": [],
        "requesting": [],
    })
    converted["issues"] = robot.get("issues", [])

    # 시간 정보 (t.sec + t.nanosec → unix_millis_time)
    if "location" in robot and "t" in robot["location"]:
        t = robot["location"]["t"]
        sec = t.get("sec", 0)
        nanosec = t.get("nanosec", 0)
        converted["unix_millis_time"] = sec * 1000 + nanosec // 1000000

    return converted


def _convert_ros2_fleet_state(data: dict) -> dict:
    """ROS 2 fleet_state 형식을 API Server 형식으로 변환

    ROS 2 형식: robots가 리스트 [{"name": "robot1", ...}, {"name": "robot2", ...}]
    API Server 형식: robots가 딕셔너리 {"robot1": {...}, "robot2": {...}}
    """
    robots_data = data.get("robots", [])

    # 이미 dict 형식이고 location.map이 있으면 그대로 반환
    if isinstance(robots_data, dict):
        # API Server 형식인지 확인 (location.map 존재 여부)
        for robot in robots_data.values():
            if isinstance(robot, dict):
                loc = robot.get("location", {})
                if "map" in loc:
                    return data  # 이미 API Server 형식
                break
        # dict지만 ROS2 형식인 경우 변환 필요
        robots_dict = {}
        for name, robot in robots_data.items():
            if isinstance(robot, dict):
                robots_dict[name] = _convert_ros2_robot_state(robot)
        converted = data.copy()
        converted["robots"] = robots_dict
        return converted

    # 리스트 형식이면 dict로 변환
    if isinstance(robots_data, list):
        robots_dict = {}
        for robot in robots_data:
            if isinstance(robot, dict) and "name" in robot:
                robots_dict[robot["name"]] = _convert_ros2_robot_state(robot)

        # 변환된 데이터 반환
        converted = data.copy()
        converted["robots"] = robots_dict
        return converted

    return data


def _get_data_identifier(msg_type: str, data: dict) -> str:
    """메시지 타입에 따른 식별자 추출"""
    if msg_type == "fleet_state_update":
        name = data.get("name", "unknown")
        robots_data = data.get("robots", {})
        # robots가 dict인 경우 (API Server 형식)
        if isinstance(robots_data, dict):
            robots = list(robots_data.keys())
        # robots가 list인 경우 (ROS 2 형식)
        elif isinstance(robots_data, list):
            robots = [r.get("name", "unknown") for r in robots_data if isinstance(r, dict)]
        else:
            robots = []
        return f"{name} (로봇: {', '.join(robots[:3])}{'...' if len(robots) > 3 else ''})"
    elif msg_type == "task_state_update":
        booking = data.get("booking", {})
        task_id = booking.get("id", "unknown")
        status = data.get("status", "unknown")
        return f"{task_id} ({status})"
    elif msg_type == "door_state_update":
        return data.get("door_name", "unknown")
    elif msg_type == "lift_state_update":
        return data.get("lift_name", "unknown")
    elif msg_type == "dispenser_state_update":
        return data.get("guid", "unknown")
    elif msg_type == "ingestor_state_update":
        return data.get("guid", "unknown")
    elif msg_type == "beacon_state_update":
        return data.get("id", "unknown")
    elif msg_type == "task_log_update":
        return data.get("task_id", "unknown")
    elif msg_type == "fleet_log_update":
        return data.get("name", "unknown")
    elif msg_type == "building_map_update":
        name = data.get("name", "unknown")
        levels = [l.get("name") for l in data.get("levels", [])]
        return f"{name} (levels: {', '.join(levels)})"
    else:
        return str(list(data.keys())[:3])


def _extract_trajectory_map_name(traj_data: dict) -> str:
    """Trajectory 데이터에서 map_name 추출"""
    values = traj_data.get("values") or []
    if values and len(values) > 0:
        return values[0].get("map_name", "unknown")
    return "unknown"


async def inject_trajectory_data(data: dict, trajectory_url: str) -> None:
    """trajectory 데이터를 API Server에 주입

    trajectory 데이터는 sample_format.trajectories 또는 latest_states.trajectory에서 가져옵니다.
    WebSocket /trajectory 엔드포인트에 연결하여 데이터를 로드합니다.
    """
    # trajectory 데이터 찾기
    trajectories = None

    # 1. sample_format.trajectories
    sample_format = data.get("sample_format", {})
    if "trajectories" in sample_format:
        trajectories = sample_format["trajectories"]

    # 2. latest_states.trajectory
    if not trajectories:
        latest = data.get("latest_states", {})
        if "trajectory" in latest:
            trajectories = latest["trajectory"]

    if not trajectories:
        print("  [trajectory] 데이터 없음, 건너뜀")
        return

    print(f"\n=== Trajectory 데이터 주입 ===")
    print(f"  WebSocket 연결 중: {trajectory_url}")

    try:
        async with websockets.connect(trajectory_url) as ws:
            print(f"  ✓ WebSocket 연결됨")

            # 각 맵별 trajectory 데이터 주입
            for map_name, traj_data in trajectories.items():
                # trajectory 요청을 보내서 저장소에 캐시되게 함
                # 실제로는 서버 측에서 _trajectory_store에 저장해야 함
                # 여기서는 서버에 trajectory_load 메시지를 보냄

                values = []
                if isinstance(traj_data, dict):
                    if "values" in traj_data:
                        values = traj_data.get("values", [])
                    elif "response" in traj_data:
                        response = traj_data.get("response", {})
                        if isinstance(response, dict):
                            values = response.get("values", [])

                # trajectory_load 메시지 전송
                msg = {
                    "request": "trajectory_load",
                    "param": {
                        "map_name": map_name,
                        "data": traj_data
                    }
                }
                await ws.send(json.dumps(msg))

                # 응답 대기
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                resp_data = json.loads(response)

                if resp_data.get("response") == "trajectory_load":
                    print(f"  [trajectory] '{map_name}': {len(values)}개 경로 로드됨")
                else:
                    print(f"  [trajectory] '{map_name}': 응답 - {resp_data}")

    except asyncio.TimeoutError:
        print(f"  ✗ trajectory 서버 응답 타임아웃")
    except Exception as e:
        print(f"  ✗ trajectory 주입 실패: {e}")


async def inject_latest_states(data: dict, internal_url: str) -> None:
    """latest_states를 API Server에 주입"""
    latest = data.get("latest_states", {})

    print("\n=== 최신 상태 주입 ===")
    print(f"  WebSocket 연결 중: {internal_url}")

    async with websockets.connect(internal_url) as ws:
        print(f"  ✓ WebSocket 연결됨")

        # Building Map (먼저 주입 - 다른 데이터의 기반이 됨)
        if "building_map" in latest:
            for map_name, map_data in latest["building_map"].items():
                msg = {
                    "type": "building_map_update",
                    "data": map_data
                }
                await ws.send(json.dumps(msg))
                levels = [l.get("name") for l in map_data.get("levels", [])]
                print(f"  [building_map] {map_name}: levels={levels}")

        # Fleet State (ROS2 형식을 API Server 형식으로 변환)
        if "fleet_state" in latest:
            for fleet_name, fleet_data in latest["fleet_state"].items():
                converted_data = _convert_ros2_fleet_state(fleet_data)
                msg = {
                    "type": "fleet_state_update",
                    "data": converted_data
                }
                await ws.send(json.dumps(msg))
                robots_count = len(converted_data.get('robots', {}))
                print(f"  [fleet_state] {fleet_name}: 로봇 {robots_count}대")

        # Fleet State ROS2 (별도 저장된 경우)
        if "fleet_state_ros2" in latest:
            for fleet_name, fleet_data in latest["fleet_state_ros2"].items():
                converted_data = _convert_ros2_fleet_state(fleet_data)
                msg = {
                    "type": "fleet_state_update",
                    "data": converted_data
                }
                await ws.send(json.dumps(msg))
                robots_count = len(converted_data.get('robots', {}))
                print(f"  [fleet_state_ros2] {fleet_name}: 로봇 {robots_count}대")

        # Task State
        if "task_state" in latest:
            for task_id, task_data in latest["task_state"].items():
                msg = {
                    "type": "task_state_update",
                    "data": task_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [task_state] {task_id}: {task_data.get('status', 'unknown')}")

        # Task Log
        if "task_log" in latest:
            for task_id, log_data in latest["task_log"].items():
                msg = {
                    "type": "task_log_update",
                    "data": log_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [task_log] {task_id}")

        # Fleet Log
        if "fleet_log" in latest:
            for fleet_name, log_data in latest["fleet_log"].items():
                msg = {
                    "type": "fleet_log_update",
                    "data": log_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [fleet_log] {fleet_name}")

        # Door State (ROS 2 데이터)
        if "door_state" in latest:
            for door_name, door_data in latest["door_state"].items():
                msg = {
                    "type": "door_state_update",
                    "data": door_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [door_state] {door_name}")

        # Lift State (ROS 2 데이터)
        if "lift_state" in latest:
            for lift_name, lift_data in latest["lift_state"].items():
                msg = {
                    "type": "lift_state_update",
                    "data": lift_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [lift_state] {lift_name}")

        # Dispenser State (ROS 2 데이터)
        if "dispenser_state" in latest:
            for guid, disp_data in latest["dispenser_state"].items():
                msg = {
                    "type": "dispenser_state_update",
                    "data": disp_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [dispenser_state] {guid}")

        # Ingestor State (ROS 2 데이터)
        if "ingestor_state" in latest:
            for guid, ing_data in latest["ingestor_state"].items():
                msg = {
                    "type": "ingestor_state_update",
                    "data": ing_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [ingestor_state] {guid}")

        # Beacon State (ROS 2 데이터)
        if "beacon_state" in latest:
            for beacon_id, beacon_data in latest["beacon_state"].items():
                msg = {
                    "type": "beacon_state_update",
                    "data": beacon_data
                }
                await ws.send(json.dumps(msg))
                print(f"  [beacon_state] {beacon_id}")


async def replay_history(data: dict, internal_url: str, trajectory_url: str, speed: float = 1.0) -> None:
    """history를 시간 순서대로 재생 (trajectory 포함)"""
    history = data.get("history", {})

    # 모든 히스토리 엔트리를 시간순으로 정렬
    all_entries = []

    type_mapping = {
        "fleet_state": "fleet_state_update",
        "fleet_state_ros2": "fleet_state_update",  # ROS 2 토픽에서 캡처된 데이터 (path 포함)
        "task_state": "task_state_update",
        "task_log": "task_log_update",
        "fleet_log": "fleet_log_update",
        # ROS 2 데이터 타입 추가
        "door_state": "door_state_update",
        "lift_state": "lift_state_update",
        "dispenser_state": "dispenser_state_update",
        "ingestor_state": "ingestor_state_update",
        "beacon_state": "beacon_state_update",
        "building_map": "building_map_update",
        "trajectory": "trajectory",  # 특별 처리 - /trajectory WebSocket으로 전송
    }

    for data_type, entries in history.items():
        if data_type in type_mapping:
            for entry in entries:
                all_entries.append({
                    "timestamp": entry["timestamp"],
                    "type": type_mapping[data_type],
                    "data": entry["data"]
                })

    if not all_entries:
        print("재생할 데이터가 없습니다.")
        return

    # 시간순 정렬
    all_entries.sort(key=lambda x: x["timestamp"])

    print(f"\n=== 히스토리 재생 ({len(all_entries)}개 메시지, 속도 {speed}x) ===")

    print(f"  WebSocket 연결 중: {internal_url}, {trajectory_url}")
    async with websockets.connect(internal_url) as internal_ws, \
               websockets.connect(trajectory_url) as trajectory_ws:
        print(f"  ✓ WebSocket 연결됨 (internal + trajectory)")
        prev_time = None
        sent_count = 0

        for i, entry in enumerate(all_entries):
            # 타임스탬프 파싱
            curr_time = datetime.fromisoformat(entry["timestamp"])

            # 이전 메시지와의 시간 차이만큼 대기
            if prev_time:
                delay = (curr_time - prev_time).total_seconds() / speed
                if delay > 0:
                    await asyncio.sleep(min(delay, 5.0))  # 최대 5초 대기

            # 메시지 전송
            msg_data = entry["data"]

            if entry["type"] == "trajectory":
                # Trajectory는 별도 WebSocket으로 전송
                map_name = _extract_trajectory_map_name(msg_data)
                msg = {
                    "request": "trajectory_load",
                    "param": {
                        "map_name": map_name,
                        "data": msg_data
                    }
                }
                await trajectory_ws.send(json.dumps(msg))
                # 응답 대기 (non-blocking)
                try:
                    await asyncio.wait_for(trajectory_ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
            else:
                # 일반 메시지는 internal WebSocket으로 전송
                if entry["type"] == "fleet_state_update":
                    msg_data = _convert_ros2_fleet_state(msg_data)

                msg = {
                    "type": entry["type"],
                    "data": msg_data
                }
                await internal_ws.send(json.dumps(msg))

            sent_count += 1

            # 각 메시지 전송 로그 (처음 10개는 상세히, 이후는 10개마다)
            if i < 10:
                # 데이터 식별자 추출
                data_id = _get_data_identifier(entry["type"], entry["data"])
                print(f"  [{i+1}] 전송: {entry['type']} - {data_id}")
            elif (i + 1) % 100 == 0 or i == len(all_entries) - 1:
                print(f"  진행: {i + 1}/{len(all_entries)} ({(i + 1) * 100 // len(all_entries)}%) - 전송됨: {sent_count}개")

            prev_time = curr_time

    print(f"  ✓ 재생 완료! 총 {sent_count}개 메시지 전송됨")


def print_captured_info(data: dict) -> None:
    """캡처 데이터 정보 출력"""
    metadata = data.get("_metadata", {})

    print("\n" + "=" * 60)
    print("  캡처 데이터 정보")
    print("=" * 60)
    print(f"  캡처 시작: {metadata.get('capture_start', 'N/A')}")
    print(f"  캡처 종료: {metadata.get('capture_end', 'N/A')}")
    print(f"  총 메시지: {metadata.get('total_messages', 0)}")
    print(f"  데이터 유형: {', '.join(metadata.get('data_types', []))}")
    print("-" * 60)

    # Latest states 정보
    latest = data.get("latest_states", {})
    print("  [최신 상태]")
    for data_type, items in latest.items():
        print(f"    {data_type}: {len(items)}개")

    # History 정보
    history = data.get("history", {})
    print("  [히스토리]")
    for data_type, entries in history.items():
        print(f"    {data_type}: {len(entries)}개 메시지")

    # Trajectory 정보
    sample_format = data.get("sample_format", {})
    trajectories = sample_format.get("trajectories", {})
    if trajectories:
        print("  [Trajectory]")
        for map_name, traj_data in trajectories.items():
            if isinstance(traj_data, dict):
                values = traj_data.get("values") or []
                if not values and "response" in traj_data:
                    resp = traj_data.get("response", {})
                    if isinstance(resp, dict):
                        values = resp.get("values") or []
                print(f"    {map_name}: {len(values)}개 경로")

    print("=" * 60)


async def main():
    parser = argparse.ArgumentParser(
        description="캡처된 데이터를 API Server에 주입",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 최신 상태만 주입 (기본)
  python inject_captured_data.py ../captured_data/captured_data_20251204_022754.json

  # 히스토리 재생 (시간순)
  python inject_captured_data.py ../captured_data/captured_data_20251204_022754.json --replay

  # 2배속 재생
  python inject_captured_data.py ../captured_data/captured_data_20251204_022754.json --replay --speed 2.0

  # 다른 서버에 주입
  python inject_captured_data.py data.json --api-url http://192.168.1.100:8000
        """
    )
    parser.add_argument("captured_file", help="캡처된 JSON 파일 경로")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API Server URL")
    parser.add_argument("--replay", action="store_true", help="히스토리를 시간순으로 재생")
    parser.add_argument("--speed", type=float, default=1.0, help="재생 속도 (기본: 1.0)")
    parser.add_argument("--info-only", action="store_true", help="정보만 출력하고 주입하지 않음")
    parser.add_argument("--cache-dir", default="../run/cache", help="API 서버 캐시 디렉토리 (기본: ../run/cache)")

    args = parser.parse_args()

    # 파일 로드
    captured_file = Path(args.captured_file)
    if not captured_file.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {captured_file}")
        sys.exit(1)

    print(f"캡처 파일 로드 중: {captured_file}")
    with open(captured_file) as f:
        data = json.load(f)

    # 정보 출력
    print_captured_info(data)

    if args.info_only:
        return

    # 캐시 디렉토리 경로 (test_data 기준 상대 경로)
    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_absolute():
        # test_data 디렉토리 기준으로 상대 경로 계산
        script_dir = Path(__file__).parent
        cache_dir = (script_dir / cache_dir).resolve()

    # 이미지 파일 복원
    restore_images(data, captured_file, cache_dir)

    # WebSocket URL 생성
    ws_url = args.api_url.replace("http://", "ws://").replace("https://", "wss://")
    internal_url = f"{ws_url}/_internal"
    trajectory_url = f"{ws_url}/trajectory"

    print(f"\nAPI Server: {args.api_url}")
    print(f"WebSocket (_internal): {internal_url}")
    print(f"WebSocket (trajectory): {trajectory_url}")

    try:
        if args.replay:
            # replay 모드: trajectory도 시간 순서대로 함께 재생
            await replay_history(data, internal_url, trajectory_url, args.speed)
        else:
            # 최신 상태 주입
            await inject_latest_states(data, internal_url)
            # Trajectory 데이터 주입 (별도 WebSocket 엔드포인트)
            await inject_trajectory_data(data, trajectory_url)

        print("\n주입 완료!")

    except ConnectionRefusedError:
        print(f"\n오류: API Server에 연결할 수 없습니다: {args.api_url}")
        print("API Server가 실행 중인지 확인하세요.")
        sys.exit(1)
    except Exception as e:
        print(f"\n오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
