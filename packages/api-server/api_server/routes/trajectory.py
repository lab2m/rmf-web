"""
Trajectory Server WebSocket 프록시 및 캡처/재생 라우트

이 모듈은 Dashboard의 trajectory 요청을 처리합니다:
1. 프록시 모드: 실제 rmf_visualization_schedule 노드(8006)로 요청 전달
2. 캡처 모드: trajectory 응답을 캡처 데이터에 저장
3. 재생 모드: 캡처된 trajectory 데이터로 응답

환경 변수:
- TRAJECTORY_SERVER_URL: 실제 trajectory 서버 URL (기본: ws://localhost:8006)
- RMF_TRAJECTORY_REPLAY: 재생 모드 활성화 (1 또는 true)
- RMF_TRAJECTORY_DATA: 재생할 trajectory 데이터 파일 경로
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import websockets
from websockets.exceptions import ConnectionClosed

from api_server.data_capture import capture_data

router = APIRouter(tags=["trajectory"])
logger = logging.getLogger(__name__)

# 설정
TRAJECTORY_SERVER_URL = os.environ.get("TRAJECTORY_SERVER_URL", "ws://localhost:8006")
REPLAY_MODE = os.environ.get("RMF_TRAJECTORY_REPLAY", "").lower() in ("1", "true", "yes")
TRAJECTORY_DATA_FILE = os.environ.get("RMF_TRAJECTORY_DATA", "")

# 캡처된 trajectory 데이터 저장소 (재생용)
_trajectory_store: dict[str, Any] = {}


def load_trajectory_data(file_path: str) -> bool:
    """재생용 trajectory 데이터 로드

    지원하는 형식:
    1. 캡처 파일 (captured_data_*.json): sample_format.trajectories 또는 latest_states.trajectory
    2. trajectory 전용 파일: {"map_name": {"response": ..., "values": [...]}}
    """
    global _trajectory_store
    try:
        with open(file_path, "r") as f:
            data = json.load(f)

            # 1. 캡처 파일 형식 (sample_format.trajectories)
            if "sample_format" in data:
                trajectories = data["sample_format"].get("trajectories", {})
                if trajectories:
                    _trajectory_store = trajectories
                    logger.info(f"Trajectory 데이터 로드됨 (sample_format): {len(_trajectory_store)} 맵")
                    return True

            # 2. 캡처 파일 형식 (latest_states.trajectory)
            if "latest_states" in data:
                trajectories = data["latest_states"].get("trajectory", {})
                if trajectories:
                    _trajectory_store = trajectories
                    logger.info(f"Trajectory 데이터 로드됨 (latest_states): {len(_trajectory_store)} 맵")
                    return True

            # 3. trajectory 전용 형식
            if "trajectories" in data:
                _trajectory_store = data["trajectories"]
                logger.info(f"Trajectory 데이터 로드됨: {len(_trajectory_store)} 맵")
                return True

            # 4. 직접 trajectory 데이터
            if any(isinstance(v, dict) and "values" in v for v in data.values()):
                _trajectory_store = data
                logger.info(f"Trajectory 데이터 로드됨 (직접): {len(_trajectory_store)} 맵")
                return True

            logger.warning(f"Trajectory 데이터 없음: {file_path}")
            return False
    except Exception as e:
        logger.error(f"Trajectory 데이터 로드 실패: {e}")
        return False


def store_trajectory_response(map_name: str, response: dict) -> None:
    """trajectory 응답을 저장소에 저장

    다양한 형식 지원:
    1. 직접 응답: {"response": "trajectory", "values": [...], "conflicts": [...]}
    2. 캡처 형식: {"timestamp": ..., "response": {...}}
    3. values만 있는 형식: {"values": [...]}
    """
    global _trajectory_store

    # 이미 response 형식이면 그대로 저장
    if "response" in response and response.get("response") == "trajectory":
        _trajectory_store[map_name] = {
            "timestamp": time.time(),
            "response": response,
        }
    # 캡처 형식 (timestamp + response)
    elif "response" in response and isinstance(response.get("response"), dict):
        _trajectory_store[map_name] = {
            "timestamp": response.get("timestamp", time.time()),
            "response": response["response"],
        }
    # values만 있는 형식
    elif "values" in response:
        _trajectory_store[map_name] = {
            "timestamp": time.time(),
            "response": {
                "response": "trajectory",
                "values": response.get("values", []),
                "conflicts": response.get("conflicts", []),
            },
        }
    # 기타 형식
    else:
        _trajectory_store[map_name] = {
            "timestamp": time.time(),
            "response": response,
        }


def get_stored_trajectory(map_name: str) -> Optional[dict]:
    """저장된 trajectory 응답 반환"""
    if map_name in _trajectory_store:
        return _trajectory_store[map_name].get("response")
    # map_name이 없으면 첫 번째 항목 반환
    if _trajectory_store:
        first_key = next(iter(_trajectory_store))
        return _trajectory_store[first_key].get("response")
    return None


@router.websocket("")
async def trajectory_proxy(websocket: WebSocket):
    """
    Trajectory Server WebSocket 프록시

    클라이언트로부터 trajectory 요청을 받아:
    1. 재생 모드: 캡처된 데이터로 응답
    2. 프록시 모드: 실제 trajectory 서버로 전달하고 응답 캡처
    """
    await websocket.accept()
    logger.info("[/trajectory] WebSocket 클라이언트 연결됨")

    upstream_ws = None

    try:
        # 재생 모드가 아니면 upstream 서버에 연결
        if not REPLAY_MODE:
            try:
                upstream_ws = await websockets.connect(TRAJECTORY_SERVER_URL)
                logger.info(f"[/trajectory] Upstream 연결됨: {TRAJECTORY_SERVER_URL}")
            except Exception as e:
                logger.warning(f"[/trajectory] Upstream 연결 실패: {e}")
                # upstream 연결 실패해도 캡처된 데이터로 응답 시도

        while True:
            # 클라이언트 요청 수신
            data = await websocket.receive_text()
            request = json.loads(data)
            logger.debug(f"[/trajectory] 요청 수신: {request.get('request')}")

            response = None

            if request.get("request") == "trajectory":
                map_name = request.get("param", {}).get("map_name", "")

                # 1. upstream 연결이 있으면 프록시
                if upstream_ws:
                    try:
                        await upstream_ws.send(data)
                        response_data = await asyncio.wait_for(
                            upstream_ws.recv(), timeout=5.0
                        )
                        response = json.loads(response_data)

                        # 캡처
                        capture_data(
                            "trajectory",
                            response,
                            map_name,
                            source="trajectory_proxy",
                        )
                        store_trajectory_response(map_name, response)
                        logger.info(
                            f"[/trajectory] trajectory 응답: {len(response.get('values', []))} trajectories"
                        )
                    except asyncio.TimeoutError:
                        logger.warning("[/trajectory] upstream 응답 타임아웃")
                    except Exception as e:
                        logger.warning(f"[/trajectory] upstream 오류: {e}")

                # 2. upstream 실패 또는 재생 모드면 저장된 데이터 사용
                if response is None:
                    stored = get_stored_trajectory(map_name)
                    if stored:
                        response = stored
                        logger.info(
                            f"[/trajectory] 저장된 데이터 사용: {len(response.get('values', []))} trajectories"
                        )
                    else:
                        # 빈 응답
                        response = {
                            "response": "trajectory",
                            "values": [],
                            "conflicts": [],
                        }
                        logger.info("[/trajectory] 데이터 없음, 빈 응답")

            elif request.get("request") == "time":
                # 시간 요청은 현재 시간 반환
                if upstream_ws:
                    try:
                        await upstream_ws.send(data)
                        response_data = await asyncio.wait_for(
                            upstream_ws.recv(), timeout=2.0
                        )
                        response = json.loads(response_data)
                    except Exception:
                        pass

                if response is None:
                    # 현재 시간 (나노초)
                    response = {
                        "response": "time",
                        "values": [int(time.time() * 1e9)],
                    }

            elif request.get("request") == "trajectory_load":
                # 외부에서 trajectory 데이터 로드 (inject_captured_data.py에서 사용)
                param = request.get("param", {})
                map_name = param.get("map_name", "")
                traj_data = param.get("data", {})

                if map_name and traj_data:
                    store_trajectory_response(map_name, traj_data)
                    logger.info(
                        f"[/trajectory] trajectory 데이터 로드됨: {map_name}"
                    )
                    response = {
                        "response": "trajectory_load",
                        "status": "ok",
                        "map_name": map_name,
                    }
                else:
                    response = {
                        "response": "trajectory_load",
                        "status": "error",
                        "message": "map_name 또는 data가 없습니다",
                    }

            else:
                # 알 수 없는 요청 타입
                response = {"error": f"Unknown request type: {request.get('request')}"}

            # 응답 전송
            await websocket.send_text(json.dumps(response))

    except WebSocketDisconnect:
        logger.info("[/trajectory] 클라이언트 연결 해제")
    except ConnectionClosed:
        logger.info("[/trajectory] 연결 종료")
    except Exception as e:
        logger.error(f"[/trajectory] 오류: {e}")
    finally:
        if upstream_ws:
            await upstream_ws.close()


def get_trajectory_store() -> dict:
    """현재 저장된 trajectory 데이터 반환 (캡처 저장용)"""
    return _trajectory_store


def set_trajectory_store(data: dict) -> None:
    """trajectory 저장소 설정 (재생 로드용)"""
    global _trajectory_store
    _trajectory_store = data


# 데이터 파일이 지정되어 있으면 로드
if TRAJECTORY_DATA_FILE:
    load_trajectory_data(TRAJECTORY_DATA_FILE)
