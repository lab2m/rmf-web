#!/usr/bin/env python3
"""
캡처된 ROS 2 데이터를 재생하는 스크립트

이 스크립트는 캡처된 데이터를 ROS 2 토픽으로 발행하여
API Server가 실제 RMF 시스템처럼 데이터를 받을 수 있게 합니다.

사용법:
    python playback_ros2.py <captured_data.json> [options]

예시:
    python playback_ros2.py ../captured_data/captured_data_20251204_104726.json
    python playback_ros2.py ../captured_data/captured_data_20251204_104726.json --speed 2.0
    python playback_ros2.py ../captured_data/captured_data_20251204_104726.json --loop
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

# RMF 메시지 타입
from rmf_door_msgs.msg import DoorState
from rmf_lift_msgs.msg import LiftState
from rmf_dispenser_msgs.msg import DispenserState
from rmf_ingestor_msgs.msg import IngestorState
from rmf_building_map_msgs.msg import BuildingMap, Level, Graph, GraphNode, GraphEdge, Door, Lift, AffineImage
from builtin_interfaces.msg import Time


def dict_to_time(d: dict) -> Time:
    """dict를 builtin_interfaces/Time으로 변환"""
    t = Time()
    t.sec = d.get("sec", 0)
    t.nanosec = d.get("nanosec", 0)
    return t


def create_door_state(data: dict) -> DoorState:
    """dict에서 DoorState 메시지 생성"""
    msg = DoorState()
    msg.door_time = dict_to_time(data.get("door_time", {}))
    msg.door_name = data.get("door_name", "")
    msg.current_mode.value = data.get("current_mode", {}).get("value", 0)
    return msg


def create_lift_state(data: dict) -> LiftState:
    """dict에서 LiftState 메시지 생성"""
    msg = LiftState()
    msg.lift_time = dict_to_time(data.get("lift_time", {}))
    msg.lift_name = data.get("lift_name", "")
    msg.available_floors = data.get("available_floors", [])
    msg.current_floor = data.get("current_floor", "")
    msg.destination_floor = data.get("destination_floor", "")
    msg.door_state = data.get("door_state", 0)
    msg.motion_state = data.get("motion_state", 0)
    msg.available_modes = data.get("available_modes", [])
    msg.current_mode = data.get("current_mode", 0)
    msg.session_id = data.get("session_id", "")
    return msg


def create_dispenser_state(data: dict) -> DispenserState:
    """dict에서 DispenserState 메시지 생성"""
    msg = DispenserState()
    msg.time = dict_to_time(data.get("time", {}))
    msg.guid = data.get("guid", "")
    msg.mode = data.get("mode", 0)
    msg.request_guid_queue = data.get("request_guid_queue", [])
    msg.seconds_remaining = data.get("seconds_remaining", 0.0)
    return msg


def create_ingestor_state(data: dict) -> IngestorState:
    """dict에서 IngestorState 메시지 생성"""
    msg = IngestorState()
    msg.time = dict_to_time(data.get("time", {}))
    msg.guid = data.get("guid", "")
    msg.mode = data.get("mode", 0)
    msg.request_guid_queue = data.get("request_guid_queue", [])
    msg.seconds_remaining = data.get("seconds_remaining", 0.0)
    return msg


class ROS2Playback(Node):
    def __init__(self, data: dict, speed: float = 1.0, loop: bool = False):
        super().__init__("rmf_playback")

        self.data = data
        self.speed = speed
        self.loop = loop

        # QoS 설정 (RMF와 동일하게)
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            depth=100
        )

        # Publisher 생성
        self.door_pub = self.create_publisher(DoorState, "/door_states", qos)
        self.lift_pub = self.create_publisher(LiftState, "/lift_states", qos)
        self.dispenser_pub = self.create_publisher(DispenserState, "/dispenser_states", qos)
        self.ingestor_pub = self.create_publisher(IngestorState, "/ingestor_states", qos)
        self.map_pub = self.create_publisher(BuildingMap, "/map", qos)

        self.get_logger().info(f"ROS 2 Playback 시작 (속도: {speed}x, 반복: {loop})")

    def publish_latest_states(self):
        """최신 상태만 발행"""
        latest = self.data.get("latest_states", {})
        count = 0

        # Door states
        for door_name, door_data in latest.get("door_state", {}).items():
            msg = create_door_state(door_data)
            self.door_pub.publish(msg)
            count += 1
            self.get_logger().info(f"[door] {door_name}")

        # Lift states
        for lift_name, lift_data in latest.get("lift_state", {}).items():
            msg = create_lift_state(lift_data)
            self.lift_pub.publish(msg)
            count += 1
            self.get_logger().info(f"[lift] {lift_name}")

        # Dispenser states
        for guid, disp_data in latest.get("dispenser_state", {}).items():
            msg = create_dispenser_state(disp_data)
            self.dispenser_pub.publish(msg)
            count += 1
            self.get_logger().info(f"[dispenser] {guid}")

        # Ingestor states
        for guid, ing_data in latest.get("ingestor_state", {}).items():
            msg = create_ingestor_state(ing_data)
            self.ingestor_pub.publish(msg)
            count += 1
            self.get_logger().info(f"[ingestor] {guid}")

        self.get_logger().info(f"총 {count}개 메시지 발행 완료")

    def replay_history(self):
        """히스토리 시간순 재생"""
        history = self.data.get("history", {})

        # 모든 히스토리 엔트리를 시간순으로 정렬
        all_entries = []

        for data_type, entries in history.items():
            if data_type in ["door_state", "lift_state", "dispenser_state", "ingestor_state"]:
                for entry in entries:
                    all_entries.append({
                        "timestamp": entry["timestamp"],
                        "type": data_type,
                        "data": entry["data"]
                    })

        if not all_entries:
            self.get_logger().warn("재생할 데이터가 없습니다.")
            return

        # 시간순 정렬
        all_entries.sort(key=lambda x: x["timestamp"])

        total = len(all_entries)
        self.get_logger().info(f"재생 시작: {total}개 메시지 (속도: {self.speed}x)")

        prev_time = None

        for i, entry in enumerate(all_entries):
            # 타임스탬프 파싱
            curr_time = datetime.fromisoformat(entry["timestamp"])

            # 이전 메시지와의 시간 차이만큼 대기
            if prev_time:
                delay = (curr_time - prev_time).total_seconds() / self.speed
                if delay > 0:
                    time.sleep(min(delay, 2.0))  # 최대 2초 대기

            # 메시지 발행
            data_type = entry["type"]
            data = entry["data"]

            if data_type == "door_state":
                self.door_pub.publish(create_door_state(data))
            elif data_type == "lift_state":
                self.lift_pub.publish(create_lift_state(data))
            elif data_type == "dispenser_state":
                self.dispenser_pub.publish(create_dispenser_state(data))
            elif data_type == "ingestor_state":
                self.ingestor_pub.publish(create_ingestor_state(data))

            # 진행 상황 출력 (10% 단위)
            progress = (i + 1) * 100 // total
            if (i + 1) % (total // 10 + 1) == 0 or i == total - 1:
                self.get_logger().info(f"진행: {i + 1}/{total} ({progress}%)")

            prev_time = curr_time

        self.get_logger().info("재생 완료!")


def print_info(data: dict):
    """캡처 데이터 정보 출력"""
    metadata = data.get("_metadata", {})

    print("\n" + "=" * 60)
    print("  캡처 데이터 정보")
    print("=" * 60)
    print(f"  캡처 시작: {metadata.get('capture_start', 'N/A')}")
    print(f"  캡처 종료: {metadata.get('capture_end', 'N/A')}")
    print(f"  총 메시지: {metadata.get('total_messages', 0)}")
    print("-" * 60)

    history = data.get("history", {})
    print("  [ROS 2 데이터]")
    ros2_types = ["door_state", "lift_state", "dispenser_state", "ingestor_state", "building_map"]
    for data_type in ros2_types:
        if data_type in history:
            print(f"    {data_type}: {len(history[data_type])}개 메시지")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="캡처된 ROS 2 데이터를 재생",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 최신 상태만 발행
  python playback_ros2.py ../captured_data/captured_data_20251204_104726.json

  # 히스토리 시간순 재생
  python playback_ros2.py ../captured_data/captured_data_20251204_104726.json --replay

  # 5배속 재생
  python playback_ros2.py ../captured_data/captured_data_20251204_104726.json --replay --speed 5.0

  # 반복 재생
  python playback_ros2.py ../captured_data/captured_data_20251204_104726.json --replay --loop
        """
    )
    parser.add_argument("captured_file", help="캡처된 JSON 파일 경로")
    parser.add_argument("--replay", action="store_true", help="히스토리를 시간순으로 재생")
    parser.add_argument("--speed", type=float, default=1.0, help="재생 속도 (기본: 1.0)")
    parser.add_argument("--loop", action="store_true", help="반복 재생")
    parser.add_argument("--info-only", action="store_true", help="정보만 출력")

    args = parser.parse_args()

    # 파일 로드
    captured_file = Path(args.captured_file)
    if not captured_file.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {captured_file}")
        sys.exit(1)

    print(f"캡처 파일 로드 중: {captured_file}")
    with open(captured_file) as f:
        data = json.load(f)

    print_info(data)

    if args.info_only:
        return

    # ROS 2 초기화
    rclpy.init()

    try:
        node = ROS2Playback(data, args.speed, args.loop)

        if args.replay:
            while True:
                node.replay_history()
                if not args.loop:
                    break
                node.get_logger().info("반복 재생...")
                time.sleep(1)
        else:
            node.publish_latest_states()
            # 메시지가 전송될 시간 확보
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
