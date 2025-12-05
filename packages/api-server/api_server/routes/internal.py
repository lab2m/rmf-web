# NOTE: This will eventually replace `gateway.py``
from datetime import datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from api_server import models as mdl
from api_server.data_capture import capture_data
from api_server.exceptions import AlreadyExistsError
from api_server.logging import LoggerAdapter, get_logger
from api_server.models.user import User
from api_server.repositories import AlertRepository, FleetRepository, RmfRepository, TaskRepository
from api_server.rmf_io import AlertEvents, FleetEvents, TaskEvents
from api_server.rmf_io.events import RmfEvents, get_alert_events, get_fleet_events, get_rmf_events, get_task_events

router = APIRouter(tags=["_internal"])


async def process_msg(
    msg: dict[str, Any],
    fleet_repo: FleetRepository,
    task_repo: TaskRepository,
    alert_repo: AlertRepository,
    rmf_repo: RmfRepository,
    task_events: TaskEvents,
    alert_events: AlertEvents,
    fleet_events: FleetEvents,
    rmf_events: RmfEvents,
    logger: LoggerAdapter,
) -> None:
    if "type" not in msg:
        logger.warning(msg)
        logger.warning("Ignoring message, 'type' must include in msg field")
        return
    payload_type: str = msg["type"]
    if not isinstance(payload_type, str):
        logger.warning("error processing message, 'type' must be a string")
        return

    # 디버그: 수신된 메시지 로깅
    logger.info(f"[/_internal] 수신: {payload_type}")
    logger.debug(msg)

    if payload_type == "task_state_update":
        task_state = mdl.TaskState(**msg["data"])
        capture_data(
            "task_state",
            task_state,
            task_state.booking.id,
            source="internal",
        )
        await task_repo.save_task_state(task_state)
        task_events.task_states.on_next(task_state)

        if task_state.status == mdl.TaskStatus.completed:
            alert_request = mdl.AlertRequest(
                id=str(uuid4()),
                unix_millis_alert_time=round(datetime.now().timestamp() * 1000),
                title="Task completed",
                subtitle=f"ID: {task_state.booking.id}",
                message="",
                display=True,
                tier=mdl.AlertRequest.Tier.Info,
                responses_available=["Acknowledge"],
                alert_parameters=[],
                task_id=task_state.booking.id,
            )
            try:
                created_alert = await alert_repo.create_new_alert(alert_request)
            except AlreadyExistsError as e:
                logger.error(e)
                return
            alert_events.alert_requests.on_next(created_alert)
        elif task_state.status == mdl.TaskStatus.failed:
            errorMessage = ""
            if (
                task_state.dispatch is not None
                and task_state.dispatch.status == mdl.DispatchStatus.failed_to_assign
            ):
                errorMessage += "Failed to assign\n"
                if task_state.dispatch.errors is not None:
                    for error in task_state.dispatch.errors:
                        errorMessage += error.json() + "\n"

            alert_request = mdl.AlertRequest(
                id=str(uuid4()),
                unix_millis_alert_time=round(datetime.now().timestamp() * 1000),
                title="Task failed",
                subtitle=f"ID: {task_state.booking.id}",
                message=errorMessage,
                display=True,
                tier=mdl.AlertRequest.Tier.Error,
                responses_available=["Acknowledge"],
                alert_parameters=[],
                task_id=task_state.booking.id,
            )
            try:
                created_alert = await alert_repo.create_new_alert(alert_request)
            except AlreadyExistsError as e:
                logger.error(e)
                return
            alert_events.alert_requests.on_next(created_alert)

    elif payload_type == "task_log_update":
        task_log = mdl.TaskEventLog(**msg["data"])
        capture_data(
            "task_log",
            task_log,
            task_log.task_id,
            source="internal",
        )
        await task_repo.save_task_log(task_log)
        task_events.task_event_logs.on_next(task_log)

    elif payload_type == "fleet_state_update":
        # 원본 데이터를 먼저 캡처 (path 등 추가 필드 보존)
        raw_data = msg["data"]
        fleet_name = raw_data.get("name")

        # 디버그: path 필드 존재 여부 확인
        robots = raw_data.get("robots", {})
        for robot_name, robot_data in robots.items():
            if "path" in robot_data and robot_data["path"]:
                logger.info(f"[/_internal] {robot_name}: path={len(robot_data['path'])} waypoints")
            else:
                logger.debug(f"[/_internal] {robot_name}: path 없음 또는 비어있음")

        capture_data(
            "fleet_state",
            raw_data,  # Pydantic 모델 대신 원본 데이터 캡처
            fleet_name,
            source="internal",
        )
        fleet_state = mdl.FleetState(**raw_data)
        await fleet_repo.save_fleet_state(fleet_state)
        fleet_events.fleet_states.on_next(fleet_state)

    elif payload_type == "fleet_log_update":
        fleet_log = mdl.FleetLog(**msg["data"])
        capture_data(
            "fleet_log",
            fleet_log,
            fleet_log.name,
            source="internal",
        )
        await fleet_repo.save_fleet_log(fleet_log)
        fleet_events.fleet_logs.on_next(fleet_log)

    # ROS 2 데이터 주입 지원 (캡처 데이터 플레이백용)
    elif payload_type == "door_state_update":
        door_state = mdl.DoorState(**msg["data"])
        capture_data(
            "door_state",
            door_state,
            door_state.door_name,
            source="internal",
        )
        await rmf_repo.save_door_state(door_state)
        rmf_events.door_states.on_next(door_state)

    elif payload_type == "lift_state_update":
        lift_state = mdl.LiftState(**msg["data"])
        capture_data(
            "lift_state",
            lift_state,
            lift_state.lift_name,
            source="internal",
        )
        await rmf_repo.save_lift_state(lift_state)
        rmf_events.lift_states.on_next(lift_state)

    elif payload_type == "dispenser_state_update":
        dispenser_state = mdl.DispenserState(**msg["data"])
        capture_data(
            "dispenser_state",
            dispenser_state,
            dispenser_state.guid,
            source="internal",
        )
        await rmf_repo.save_dispenser_state(dispenser_state)
        rmf_events.dispenser_states.on_next(dispenser_state)

    elif payload_type == "ingestor_state_update":
        ingestor_state = mdl.IngestorState(**msg["data"])
        capture_data(
            "ingestor_state",
            ingestor_state,
            ingestor_state.guid,
            source="internal",
        )
        await rmf_repo.save_ingestor_state(ingestor_state)
        rmf_events.ingestor_states.on_next(ingestor_state)

    elif payload_type == "beacon_state_update":
        beacon_state = mdl.BeaconState(**msg["data"])
        capture_data(
            "beacon_state",
            beacon_state,
            beacon_state.id,
            source="internal",
        )
        await rmf_repo.save_beacon_state(beacon_state)
        rmf_events.beacons.on_next(beacon_state)

    elif payload_type == "building_map_update":
        building_map = mdl.BuildingMap(**msg["data"])
        capture_data(
            "building_map",
            building_map,
            building_map.name,
            source="internal",
        )
        await rmf_repo.save_building_map(building_map)
        rmf_events.building_map.on_next(building_map)
        logger.info(f"[/_internal] BuildingMap 저장됨: {building_map.name}")

    else:
        # 처리되지 않은 메시지 타입 로깅 및 캡처 (디버깅용)
        logger.warning(f"[/_internal] 처리되지 않은 메시지 타입: {payload_type}")
        logger.warning(f"[/_internal] 메시지 데이터: {msg}")
        # 알려지지 않은 타입도 캡처하여 분석 가능하게 함
        if "data" in msg:
            capture_data(
                payload_type,
                msg["data"],
                None,
                source="internal",
            )


@router.websocket("")
async def rmf_gateway(
    websocket: WebSocket,
    task_events: Annotated[TaskEvents, Depends(get_task_events)],
    alert_events: Annotated[AlertEvents, Depends(get_alert_events)],
    fleet_events: Annotated[FleetEvents, Depends(get_fleet_events)],
    rmf_events: Annotated[RmfEvents, Depends(get_rmf_events)],
    logger: Annotated[LoggerAdapter, Depends(get_logger)],
):
    # We must resolve some dependencies manually because:
    # 1. `user_dep` uses `OpenIdConnect` which does not work for websocket
    # 2. Even if it works, the _internal route has no authentication
    user = User.get_system_user()
    fleet_repo = FleetRepository(user, logger)
    task_repo = TaskRepository(user, logger)
    alert_repo = AlertRepository()
    rmf_repo = RmfRepository(user)

    await websocket.accept()
    logger.info("[/_internal] WebSocket 클라이언트 연결됨")
    try:
        while True:
            msg: dict[str, Any] = await websocket.receive_json()
            await process_msg(
                msg,
                fleet_repo,
                task_repo,
                alert_repo,
                rmf_repo,
                task_events,
                alert_events,
                fleet_events,
                rmf_events,
                logger,
            )
    except (WebSocketDisconnect, ConnectionClosed):
        logger.warning("[/_internal] WebSocket 클라이언트 연결 해제")
