"""
RMF API Server 데이터 캡처 모듈

이 모듈은 API 서버로 들어오는 모든 데이터를 캡처하여 JSON 파일로 저장합니다.
캡처된 데이터는 test_data/mock_rmf_server.py로 재생할 수 있습니다.

활성화 방법:
    환경 변수 RMF_CAPTURE_DATA=1 로 설정하면 캡처가 활성화됩니다.

    RMF_CAPTURE_DATA=1 python -m api_server

    또는 설정 파일에서:
    capture_data = True
    capture_output_dir = "./captured_data"

환경 변수:
    RMF_CAPTURE_DATA=1          캡처 활성화
    RMF_CAPTURE_OUTPUT_DIR=...  출력 디렉토리 (기본: ./captured_data)
    RMF_CAPTURE_DURATION=300    캡처 시간(초) (기본: 300초 = 5분, 0=무제한)

캡처되는 데이터:
    - ROS 2 토픽 (gateway.py):
        - door_states, lift_states, dispenser_states, ingestor_states
        - map (building_map), beacon_state, alert, fire_alarm_trigger
    - WebSocket /_internal (internal.py):
        - task_state_update, task_log_update
        - fleet_state_update, fleet_log_update

출력 형식:
    captured_data_{timestamp}.json:
    {
        "_metadata": {...},
        "history": {...},      # 시간순 전체 이력
        "latest_states": {...}, # 각 엔티티의 최종 상태
        "sample_format": {...}  # mock_rmf_server.py와 호환되는 형식
    }
"""

import atexit
import base64
import json
import logging
import os
import re
import shutil
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class DataCaptureManager:
    """API 서버 데이터 캡처 관리자"""

    _instance: "DataCaptureManager | None" = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._enabled = os.environ.get("RMF_CAPTURE_DATA", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self._output_dir = os.environ.get("RMF_CAPTURE_OUTPUT_DIR", "./captured_data")
        self._duration = int(os.environ.get("RMF_CAPTURE_DURATION", "300"))  # 기본 5분

        self._captured_data: dict[str, list[dict]] = defaultdict(list)
        self._unique_data: dict[str, dict[str, Any]] = defaultdict(dict)
        self._start_time = datetime.now()
        self._message_count = 0
        self._data_lock = threading.Lock()
        self._stopped = False
        self._saved = False
        self._timer: threading.Timer | None = None

        # 캡처된 이미지 파일 목록 (building_map 이미지)
        self._captured_images: dict[str, str] = {}  # {filename: source_path}

        if self._enabled:
            Path(self._output_dir).mkdir(parents=True, exist_ok=True)
            duration_str = f"{self._duration}초" if self._duration > 0 else "무제한"
            logger.info(f"데이터 캡처 활성화됨. 출력 디렉토리: {self._output_dir}")
            logger.info(f"캡처 시간: {duration_str}")
            atexit.register(self._on_exit)

            # 시간 제한 타이머 설정
            if self._duration > 0:
                self._timer = threading.Timer(self._duration, self._on_duration_timeout)
                self._timer.daemon = True
                self._timer.start()
                logger.info(f"{self._duration}초 후 자동 저장됩니다.")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _on_duration_timeout(self) -> None:
        """캡처 시간 초과 시 호출"""
        logger.info(f"캡처 시간 {self._duration}초 도달. 자동 저장 중...")
        self._stopped = True
        self.save()
        logger.info("캡처가 중지되었습니다. 서버는 계속 실행됩니다.")

    def _on_exit(self) -> None:
        """서버 종료 시 호출"""
        if self._timer:
            self._timer.cancel()
        self.save()

    def capture(
        self,
        data_type: str,
        data: dict | Any,
        unique_key: str | None = None,
        source: str = "unknown",
    ) -> None:
        """데이터 캡처

        Args:
            data_type: 데이터 유형 (예: "fleet_state", "task_state", "door_state")
            data: 캡처할 데이터 (dict 또는 Pydantic 모델)
            unique_key: 고유 키 (예: fleet 이름, task ID). 지정하면 latest_states에 저장
            source: 데이터 소스 (예: "gateway", "internal")
        """
        if not self._enabled or self._stopped:
            return

        # Pydantic 모델이면 dict로 변환
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        elif hasattr(data, "dict"):
            data = data.dict()

        # building_map인 경우 이미지 파일도 캡처
        if data_type == "building_map":
            data = self._capture_building_map_images(data)

        timestamp = datetime.now().isoformat()
        entry = {"timestamp": timestamp, "source": source, "data": data}

        with self._data_lock:
            self._captured_data[data_type].append(entry)

            if unique_key:
                self._unique_data[data_type][unique_key] = data

            self._message_count += 1

        logger.debug(
            f"[캡처 #{self._message_count}] {data_type} "
            f"(key={unique_key}, source={source})"
        )

    def _capture_building_map_images(self, data: dict) -> dict:
        """building_map 이미지 파일을 캡처하고 참조 경로를 기록"""
        import copy
        data = copy.deepcopy(data)

        levels = data.get("levels", [])
        for level in levels:
            images = level.get("images", [])
            for img in images:
                img_url = img.get("data", "")
                if not img_url or not img_url.startswith("http"):
                    continue

                # URL에서 파일명 추출
                parsed = urlparse(img_url)
                path_parts = parsed.path.split("/")

                # /cache/building/filename.png 형식에서 파일명 추출
                if "cache" in path_parts and len(path_parts) >= 3:
                    # 캐시 디렉토리 경로 찾기
                    cache_idx = path_parts.index("cache")
                    rel_path = "/".join(path_parts[cache_idx + 1:])
                    filename = path_parts[-1]

                    # 실제 캐시 파일 경로 (run/cache/building/...)
                    cache_file = Path("run/cache") / rel_path
                    if cache_file.exists():
                        self._captured_images[filename] = str(cache_file)
                        # 이미지 URL을 상대 경로 참조로 변경
                        img["_captured_file"] = filename
                        logger.info(f"이미지 캡처됨: {filename}")
                    else:
                        logger.warning(f"캐시 파일 없음: {cache_file}")

        return data

    def save(self, output_file: str | None = None) -> str | None:
        """캡처된 데이터를 JSON 파일로 저장

        Args:
            output_file: 출력 파일 경로. None이면 자동 생성

        Returns:
            저장된 파일 경로
        """
        if not self._enabled:
            return None

        # 이미 저장된 경우 중복 저장 방지
        if self._saved:
            return None

        if self._message_count == 0:
            logger.info("캡처된 데이터가 없습니다.")
            self._print_summary(None)
            self._saved = True
            return None

        if output_file is None:
            timestamp = self._start_time.strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(
                self._output_dir, f"captured_data_{timestamp}.json"
            )

        # 이미지 파일 복사
        images_dir = None
        if self._captured_images:
            base_name = Path(output_file).stem
            images_dir = Path(self._output_dir) / f"{base_name}_images"
            images_dir.mkdir(parents=True, exist_ok=True)

            for filename, source_path in self._captured_images.items():
                dest_path = images_dir / filename
                try:
                    shutil.copy2(source_path, dest_path)
                    logger.info(f"이미지 저장됨: {dest_path}")
                except Exception as e:
                    logger.error(f"이미지 복사 실패 {source_path}: {e}")

        with self._data_lock:
            output = {
                "_metadata": {
                    "description": "RMF API Server에서 캡처된 실시간 데이터",
                    "capture_start": self._start_time.isoformat(),
                    "capture_end": datetime.now().isoformat(),
                    "total_messages": self._message_count,
                    "data_types": list(self._captured_data.keys()),
                    "images_dir": str(images_dir) if images_dir else None,
                    "captured_images": list(self._captured_images.keys()),
                },
                "history": dict(self._captured_data),
                "latest_states": {k: dict(v) for k, v in self._unique_data.items()},
                "sample_format": self._convert_to_sample_format(),
            }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        self._saved = True
        self._print_summary(output_file)

        return output_file

    def _print_summary(self, output_file: str | None) -> None:
        """캡처 데이터 요약 출력 (서버 종료 시 콘솔에 표시)"""
        end_time = datetime.now()
        duration = (end_time - self._start_time).total_seconds()

        print("\n" + "=" * 60)
        print("  RMF 데이터 캡처 요약")
        print("=" * 60)
        print(f"  캡처 시작: {self._start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  캡처 종료: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  총 캡처 시간: {duration:.1f}초 ({duration/60:.1f}분)")
        print("-" * 60)

        if self._message_count == 0:
            print("  캡처된 데이터가 없습니다.")
            print("=" * 60 + "\n")
            return

        print(f"  총 메시지 수: {self._message_count}")
        print("-" * 60)

        # 데이터 유형별 통계
        print("  [데이터 유형별 메시지 수]")
        with self._data_lock:
            for data_type, entries in sorted(self._captured_data.items()):
                unique_count = len(self._unique_data.get(data_type, {}))
                print(f"    {data_type}: {len(entries)}개 (고유: {unique_count}개)")

        print("-" * 60)

        # 고유 엔티티 목록
        print("  [캡처된 엔티티 목록]")
        with self._data_lock:
            # Fleet & Robots
            if "fleet_state" in self._unique_data:
                fleets = self._unique_data["fleet_state"]
                for fleet_name, fleet_data in fleets.items():
                    robots = fleet_data.get("robots", {})
                    robot_names = list(robots.keys())[:5]
                    robot_str = ", ".join(robot_names)
                    if len(robots) > 5:
                        robot_str += f" 외 {len(robots)-5}개"
                    print(f"    Fleet '{fleet_name}': 로봇 {len(robots)}대 ({robot_str})")

            # Tasks
            if "task_state" in self._unique_data:
                tasks = self._unique_data["task_state"]
                task_ids = list(tasks.keys())[:3]
                print(f"    Task: {len(tasks)}개 ({', '.join(task_ids)}...)")

            # Doors
            if "door_state" in self._unique_data:
                doors = list(self._unique_data["door_state"].keys())
                print(f"    Door: {len(doors)}개 ({', '.join(doors[:5])})")

            # Lifts
            if "lift_state" in self._unique_data:
                lifts = list(self._unique_data["lift_state"].keys())
                print(f"    Lift: {len(lifts)}개 ({', '.join(lifts[:5])})")

            # Building Map
            if "building_map" in self._unique_data:
                maps = list(self._unique_data["building_map"].keys())
                print(f"    Building Map: {', '.join(maps)}")

            # Dispensers
            if "dispenser_state" in self._unique_data:
                dispensers = list(self._unique_data["dispenser_state"].keys())
                print(f"    Dispenser: {len(dispensers)}개 ({', '.join(dispensers[:5])})")

            # Ingestors
            if "ingestor_state" in self._unique_data:
                ingestors = list(self._unique_data["ingestor_state"].keys())
                print(f"    Ingestor: {len(ingestors)}개 ({', '.join(ingestors[:5])})")

            # Beacons
            if "beacon_state" in self._unique_data:
                beacons = list(self._unique_data["beacon_state"].keys())
                print(f"    Beacon: {len(beacons)}개 ({', '.join(beacons[:5])})")

            # Alerts
            if "alert_request" in self._unique_data:
                alerts = list(self._unique_data["alert_request"].keys())
                print(f"    Alert: {len(alerts)}개")

            # Trajectory
            if "trajectory" in self._unique_data:
                trajectories = self._unique_data["trajectory"]
                for map_name, traj_data in trajectories.items():
                    if isinstance(traj_data, dict) and "values" in traj_data:
                        count = len(traj_data.get("values", []))
                        print(f"    Trajectory '{map_name}': {count}개 경로")

        print("-" * 60)
        if output_file:
            print(f"  저장 파일: {output_file}")
        print("=" * 60 + "\n")

    def _convert_to_sample_format(self) -> dict:
        """sample_data.json 형식으로 변환 (mock_rmf_server.py와 호환)"""
        sample: dict[str, Any] = {}

        # Building Map
        if "building_map" in self._unique_data:
            maps = list(self._unique_data["building_map"].values())
            if maps:
                sample["building_map"] = maps[0]

        # Fleets
        if "fleet_state" in self._unique_data:
            sample["fleets"] = list(self._unique_data["fleet_state"].values())

        # Tasks
        if "task_state" in self._unique_data:
            tasks = []
            for task_id, state in self._unique_data["task_state"].items():
                task_entry: dict[str, Any] = {"state": state}
                # task_log가 있으면 추가
                if (
                    "task_log" in self._unique_data
                    and task_id in self._unique_data["task_log"]
                ):
                    task_entry["log"] = self._unique_data["task_log"][task_id]
                tasks.append(task_entry)
            sample["tasks"] = tasks

        # Doors
        if "door_state" in self._unique_data:
            sample["doors"] = list(self._unique_data["door_state"].values())

        # Lifts
        if "lift_state" in self._unique_data:
            sample["lifts"] = list(self._unique_data["lift_state"].values())

        # Dispensers
        if "dispenser_state" in self._unique_data:
            sample["dispensers"] = list(self._unique_data["dispenser_state"].values())

        # Ingestors
        if "ingestor_state" in self._unique_data:
            sample["ingestors"] = list(self._unique_data["ingestor_state"].values())

        # Alerts
        if "alert_request" in self._unique_data:
            sample["alerts"] = list(self._unique_data["alert_request"].values())

        # Beacons
        if "beacon_state" in self._unique_data:
            sample["beacons"] = list(self._unique_data["beacon_state"].values())

        # Trajectories (로봇 경로)
        if "trajectory" in self._unique_data:
            sample["trajectories"] = dict(self._unique_data["trajectory"])

        return sample

    def get_stats(self) -> dict:
        """캡처 통계 반환"""
        with self._data_lock:
            return {
                "enabled": self._enabled,
                "start_time": self._start_time.isoformat(),
                "message_count": self._message_count,
                "data_types": {
                    k: len(v) for k, v in self._captured_data.items()
                },
                "unique_counts": {
                    k: len(v) for k, v in self._unique_data.items()
                },
            }

    def clear(self) -> None:
        """캡처 데이터 초기화"""
        with self._data_lock:
            self._captured_data.clear()
            self._unique_data.clear()
            self._message_count = 0
            self._start_time = datetime.now()
        logger.info("캡처 데이터 초기화됨")


# 전역 인스턴스
_capture_manager: DataCaptureManager | None = None


def get_capture_manager() -> DataCaptureManager:
    """캡처 관리자 싱글톤 인스턴스 반환"""
    global _capture_manager
    if _capture_manager is None:
        _capture_manager = DataCaptureManager()
    return _capture_manager


def capture_data(
    data_type: str,
    data: dict | Any,
    unique_key: str | None = None,
    source: str = "unknown",
) -> None:
    """편의 함수: 데이터 캡처

    사용 예:
        from api_server.data_capture import capture_data

        # Fleet 상태 캡처
        capture_data("fleet_state", fleet_state, fleet_state.name, source="internal")

        # Door 상태 캡처
        capture_data("door_state", door_state, door_state.door_name, source="gateway")
    """
    get_capture_manager().capture(data_type, data, unique_key, source)
