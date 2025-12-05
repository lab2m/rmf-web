#!/usr/bin/env python3
"""
RMF API Server 테스트 데이터 주입 스크립트

이 스크립트는 sample_data.json의 샘플 데이터를 API 서버의 데이터베이스에 직접 주입합니다.
SQLite, PostgreSQL 등 Tortoise ORM이 지원하는 모든 데이터베이스를 사용할 수 있습니다.

사용법:
    python inject_test_data.py [--db-url DB_URL] [--data-file DATA_FILE]

예시:
    # SQLite 인메모리 (기본값, 테스트용)
    python inject_test_data.py

    # SQLite 파일
    python inject_test_data.py --db-url sqlite://./test.db

    # PostgreSQL
    python inject_test_data.py --db-url postgres://user:pass@localhost:5432/rmf_db

    # 특정 데이터 파일 사용
    python inject_test_data.py --data-file custom_data.json
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 상위 디렉토리의 api_server 모듈을 사용할 수 있도록 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise


async def init_db(db_url: str):
    """데이터베이스 초기화"""
    await Tortoise.init(
        db_url=db_url,
        modules={"models": ["api_server.models.tortoise_models"]},
    )
    await Tortoise.generate_schemas()
    print(f"✓ 데이터베이스 연결됨: {db_url}")


async def close_db():
    """데이터베이스 연결 종료"""
    await Tortoise.close_connections()


def millis_to_datetime(unix_millis: int | None) -> datetime | None:
    """Unix 밀리초를 datetime 객체로 변환"""
    if unix_millis is None:
        return None
    return datetime.fromtimestamp(unix_millis / 1000, tz=timezone.utc)


async def inject_building_map(data: dict):
    """빌딩 맵 데이터 주입"""
    from api_server.models.tortoise_models import BuildingMap

    building_map = data.get("building_map")
    if not building_map:
        print("  - 빌딩 맵 데이터 없음")
        return

    await BuildingMap.update_or_create(
        defaults={"data": building_map},
        id_=building_map["name"]
    )
    print(f"  ✓ 빌딩 맵 주입됨: {building_map['name']}")


async def inject_fleets(data: dict):
    """Fleet 데이터 주입"""
    from api_server.models.tortoise_models import FleetState

    fleets = data.get("fleets", [])
    for fleet in fleets:
        await FleetState.update_or_create(
            defaults={"data": fleet},
            name=fleet["name"]
        )
        robot_count = len(fleet.get("robots", {}))
        print(f"  ✓ Fleet 주입됨: {fleet['name']} (로봇 {robot_count}대)")


async def inject_tasks(data: dict):
    """Task 데이터 주입"""
    from api_server.models.tortoise_models import TaskState, TaskRequest, TaskLabel

    tasks = data.get("tasks", [])
    for task_data in tasks:
        state = task_data.get("state", {})
        request = task_data.get("request", {})
        booking = state.get("booking", {})
        task_id = booking.get("id")

        if not task_id:
            continue

        # TaskState 저장
        await TaskState.update_or_create(
            defaults={
                "data": state,
                "category": state.get("category"),
                "assigned_to": state.get("assigned_to", {}).get("name") if state.get("assigned_to") else None,
                "unix_millis_start_time": millis_to_datetime(state.get("unix_millis_start_time")),
                "unix_millis_finish_time": millis_to_datetime(state.get("unix_millis_finish_time")),
                "unix_millis_request_time": millis_to_datetime(booking.get("unix_millis_request_time")),
                "status": state.get("status"),
                "requester": booking.get("requester"),
            },
            id_=task_id
        )

        # TaskRequest 저장
        await TaskRequest.update_or_create(
            defaults={"request": request},
            id_=task_id
        )

        # TaskLabel 저장
        task_state_obj = await TaskState.get(id_=task_id)
        labels = booking.get("labels", [])
        for label in labels:
            if "=" in label:
                name, value = label.split("=", 1)
            else:
                name, value = label, ""
            await TaskLabel.update_or_create(
                defaults={},
                state=task_state_obj,
                label_name=name,
                label_value=value
            )

        print(f"  ✓ Task 주입됨: {task_id} (상태: {state.get('status')})")


async def inject_doors(data: dict):
    """Door 상태 데이터 주입"""
    from api_server.models.tortoise_models import DoorState

    doors = data.get("doors", [])
    for door in doors:
        await DoorState.update_or_create(
            defaults={"data": door},
            id_=door["door_name"]
        )
        mode = door.get("current_mode", {}).get("value", "unknown")
        print(f"  ✓ Door 주입됨: {door['door_name']} (모드: {mode})")


async def inject_lifts(data: dict):
    """Lift 상태 데이터 주입"""
    from api_server.models.tortoise_models import LiftState

    lifts = data.get("lifts", [])
    for lift in lifts:
        await LiftState.update_or_create(
            defaults={"data": lift},
            id_=lift["lift_name"]
        )
        print(f"  ✓ Lift 주입됨: {lift['lift_name']} (현재층: {lift['current_floor']})")


async def inject_dispensers(data: dict):
    """Dispenser 상태 데이터 주입"""
    from api_server.models.tortoise_models import DispenserState

    dispensers = data.get("dispensers", [])
    for disp in dispensers:
        await DispenserState.update_or_create(
            defaults={"data": disp},
            id_=disp["guid"]
        )
        print(f"  ✓ Dispenser 주입됨: {disp['guid']}")


async def inject_ingestors(data: dict):
    """Ingestor 상태 데이터 주입"""
    from api_server.models.tortoise_models import IngestorState

    ingestors = data.get("ingestors", [])
    for ing in ingestors:
        await IngestorState.update_or_create(
            defaults={"data": ing},
            id_=ing["guid"]
        )
        print(f"  ✓ Ingestor 주입됨: {ing['guid']}")


async def inject_alerts(data: dict):
    """Alert 데이터 주입"""
    from api_server.models.tortoise_models import AlertRequest

    alerts = data.get("alerts", [])
    for alert in alerts:
        await AlertRequest.update_or_create(
            defaults={
                "request_time": millis_to_datetime(alert["unix_millis_alert_time"]),
                "response_expected": len(alert.get("responses_available", [])) > 0,
                "task_id": alert.get("task_id"),
                "data": alert
            },
            id=alert["id"]
        )
        print(f"  ✓ Alert 주입됨: {alert['id']} ({alert['tier']})")


async def inject_beacons(data: dict):
    """Beacon 데이터 주입"""
    from api_server.models.tortoise_models import BeaconState

    beacons = data.get("beacons", [])
    for beacon in beacons:
        await BeaconState.update_or_create(
            defaults={
                "online": beacon["online"],
                "category": beacon.get("category"),
                "activated": beacon["activated"],
                "level": beacon.get("level")
            },
            id=beacon["id"]
        )
        status = "온라인" if beacon["online"] else "오프라인"
        print(f"  ✓ Beacon 주입됨: {beacon['id']} ({status})")


async def inject_users(data: dict):
    """User 데이터 주입"""
    from api_server.models.tortoise_models import User, Role

    users = data.get("users", [])
    for user_data in users:
        user, _ = await User.update_or_create(
            defaults={"is_admin": user_data.get("is_admin", False)},
            username=user_data["username"]
        )

        # 역할 연결
        role_names = user_data.get("roles", [])
        if role_names:
            roles = await Role.filter(name__in=role_names)
            await user.roles.clear()
            for role in roles:
                await user.roles.add(role)

        role_str = ", ".join(role_names) if role_names else "없음"
        admin_str = "관리자" if user_data.get("is_admin") else "일반"
        print(f"  ✓ User 주입됨: {user_data['username']} ({admin_str}, 역할: {role_str})")


async def inject_roles(data: dict):
    """Role 및 권한 데이터 주입"""
    from api_server.models.tortoise_models import Role, ResourcePermission

    roles = data.get("roles", [])
    for role_data in roles:
        role, _ = await Role.update_or_create(
            defaults={},
            name=role_data["name"]
        )

        # 기존 권한 삭제 후 새로 추가
        await ResourcePermission.filter(role=role).delete()

        permissions = role_data.get("permissions", [])
        for perm in permissions:
            await ResourcePermission.create(
                role=role,
                authz_grp=perm["authz_grp"],
                action=perm["action"]
            )

        print(f"  ✓ Role 주입됨: {role_data['name']} (권한 {len(permissions)}개)")


async def inject_all_data(data: dict):
    """모든 테스트 데이터 주입"""
    print("\n" + "=" * 60)
    print("RMF API Server 테스트 데이터 주입")
    print("=" * 60)

    print("\n[1/10] 빌딩 맵 주입 중...")
    await inject_building_map(data)

    print("\n[2/10] Fleet 데이터 주입 중...")
    await inject_fleets(data)

    print("\n[3/10] Task 데이터 주입 중...")
    await inject_tasks(data)

    print("\n[4/10] Door 상태 주입 중...")
    await inject_doors(data)

    print("\n[5/10] Lift 상태 주입 중...")
    await inject_lifts(data)

    print("\n[6/10] Dispenser 상태 주입 중...")
    await inject_dispensers(data)

    print("\n[7/10] Ingestor 상태 주입 중...")
    await inject_ingestors(data)

    print("\n[8/10] Role 데이터 주입 중...")
    await inject_roles(data)

    print("\n[9/10] User 데이터 주입 중...")
    await inject_users(data)

    print("\n[10/10] Alert 및 Beacon 데이터 주입 중...")
    await inject_alerts(data)
    await inject_beacons(data)

    print("\n" + "=" * 60)
    print("✓ 모든 테스트 데이터 주입 완료!")
    print("=" * 60)


def load_sample_data(data_file: str) -> dict:
    """샘플 데이터 파일 로드"""
    with open(data_file, "r", encoding="utf-8") as f:
        return json.load(f)


async def main():
    parser = argparse.ArgumentParser(
        description="RMF API Server 테스트 데이터 주입 스크립트"
    )
    parser.add_argument(
        "--db-url",
        default="sqlite://:memory:",
        help="데이터베이스 URL (기본값: sqlite://:memory:)"
    )
    parser.add_argument(
        "--data-file",
        default=os.path.join(os.path.dirname(__file__), "sample_data.json"),
        help="샘플 데이터 JSON 파일 경로"
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="주입 후 데이터베이스 연결 유지 (디버깅용)"
    )

    args = parser.parse_args()

    # 샘플 데이터 로드
    print(f"샘플 데이터 파일 로드 중: {args.data_file}")
    data = load_sample_data(args.data_file)

    try:
        # 데이터베이스 초기화
        await init_db(args.db_url)

        # 데이터 주입
        await inject_all_data(data)

        if args.keep_running:
            print("\n[Enter]를 눌러 종료...")
            input()

    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
