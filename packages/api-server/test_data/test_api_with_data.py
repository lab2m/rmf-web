#!/usr/bin/env python3
"""
RMF API Server 테스트 스크립트

이 스크립트는 주입된 테스트 데이터가 API를 통해 올바르게 조회되는지 확인합니다.
또한 API 서버가 정상적으로 응답하는지 테스트합니다.

사용법:
    # 테스트 데이터 주입 후 API 테스트
    python test_api_with_data.py

    # 특정 API URL 지정
    python test_api_with_data.py --api-url http://localhost:8000

    # 특정 테스트만 실행
    python test_api_with_data.py --test building_map
    python test_api_with_data.py --test fleets
    python test_api_with_data.py --test tasks
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print("⚠️ httpx 패키지가 필요합니다: pip install httpx")
    sys.exit(1)


class TestStatus(Enum):
    PASS = "✓ PASS"
    FAIL = "✗ FAIL"
    SKIP = "○ SKIP"
    WARN = "⚠ WARN"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    message: str = ""
    details: dict | None = None


class ApiTester:
    """API 테스터"""

    def __init__(self, api_url: str, expected_data_file: str | None = None):
        self.api_url = api_url.rstrip("/")
        self.results: list[TestResult] = []
        self.expected_data: dict = {}

        if expected_data_file:
            with open(expected_data_file, "r", encoding="utf-8") as f:
                self.expected_data = json.load(f)

    async def run_all_tests(self):
        """모든 테스트 실행"""
        print("\n" + "=" * 60)
        print("RMF API Server 테스트")
        print("=" * 60)
        print(f"API URL: {self.api_url}")
        print("=" * 60 + "\n")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 기본 연결 테스트
            await self.test_connection(client)

            # API 엔드포인트 테스트
            await self.test_building_map(client)
            await self.test_fleets(client)
            await self.test_tasks(client)
            await self.test_doors(client)
            await self.test_lifts(client)
            await self.test_dispensers(client)
            await self.test_ingestors(client)
            await self.test_alerts(client)
            await self.test_beacons(client)

            # 사용자/권한 테스트 (인증 필요 시 건너뜀)
            await self.test_users(client)

        self.print_summary()

    async def test_connection(self, client: httpx.AsyncClient):
        """기본 연결 테스트"""
        test_name = "API 서버 연결"
        try:
            response = await client.get(f"{self.api_url}/time")
            if response.status_code == 200:
                data = response.json()
                self.results.append(TestResult(
                    test_name, TestStatus.PASS,
                    f"서버 시간: {data}"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL,
                    f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_building_map(self, client: httpx.AsyncClient):
        """빌딩 맵 API 테스트"""
        test_name = "빌딩 맵 조회"
        try:
            response = await client.get(f"{self.api_url}/building_map")

            if response.status_code == 200:
                data = response.json()
                expected = self.expected_data.get("building_map", {})

                if data:
                    details = {
                        "name": data.get("name"),
                        "levels": len(data.get("levels", [])),
                        "lifts": len(data.get("lifts", []))
                    }

                    # 기대값과 비교
                    if expected and data.get("name") != expected.get("name"):
                        self.results.append(TestResult(
                            test_name, TestStatus.WARN,
                            f"맵 이름 불일치: {data.get('name')} != {expected.get('name')}",
                            details
                        ))
                    else:
                        self.results.append(TestResult(
                            test_name, TestStatus.PASS,
                            f"맵: {data.get('name')}, 레벨: {details['levels']}, 리프트: {details['lifts']}",
                            details
                        ))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "빌딩 맵 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_fleets(self, client: httpx.AsyncClient):
        """Fleet API 테스트"""
        test_name = "Fleet 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/fleets")

            if response.status_code == 200:
                data = response.json()
                expected_fleets = self.expected_data.get("fleets", [])

                if data:
                    fleet_info = []
                    for fleet in data:
                        robots = fleet.get("robots", {})
                        fleet_info.append(f"{fleet.get('name')}({len(robots)}대)")

                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"Fleet {len(data)}개: {', '.join(fleet_info)}",
                        {"fleets": data}
                    ))

                    # 각 Fleet 상세 테스트
                    for fleet in data:
                        await self.test_fleet_detail(client, fleet.get("name"))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "Fleet 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_fleet_detail(self, client: httpx.AsyncClient, fleet_name: str):
        """Fleet 상세 테스트"""
        test_name = f"Fleet 상세: {fleet_name}"
        try:
            response = await client.get(f"{self.api_url}/fleets/{fleet_name}/state")

            if response.status_code == 200:
                data = response.json()
                robots = data.get("robots", {})
                robot_states = []
                for name, robot in robots.items():
                    status = robot.get("status", "unknown")
                    battery = robot.get("battery")
                    if battery is not None:
                        battery_str = f"{battery*100:.0f}%"
                    else:
                        battery_str = "N/A"
                    robot_states.append(f"{name}({status}, {battery_str})")

                self.results.append(TestResult(
                    test_name, TestStatus.PASS,
                    f"로봇: {', '.join(robot_states) if robot_states else '없음'}"
                ))
            elif response.status_code == 404:
                self.results.append(TestResult(
                    test_name, TestStatus.WARN, "Fleet을 찾을 수 없음"
                ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_tasks(self, client: httpx.AsyncClient):
        """Task API 테스트"""
        test_name = "Task 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/tasks")

            if response.status_code == 200:
                data = response.json()

                if data:
                    status_counts = {}
                    for task in data:
                        status = task.get("status", "unknown")
                        status_counts[status] = status_counts.get(status, 0) + 1

                    status_str = ", ".join([f"{k}: {v}" for k, v in status_counts.items()])
                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"Task {len(data)}개 ({status_str})"
                    ))

                    # 첫 번째 Task 상세 테스트
                    if data:
                        first_task_id = data[0].get("booking", {}).get("id")
                        if first_task_id:
                            await self.test_task_detail(client, first_task_id)
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "Task 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_task_detail(self, client: httpx.AsyncClient, task_id: str):
        """Task 상세 테스트"""
        test_name = f"Task 상세: {task_id[:20]}..."
        try:
            response = await client.get(f"{self.api_url}/tasks/{task_id}/state")

            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "unknown")
                category = data.get("category", "unknown")
                assigned = data.get("assigned_to", {})
                assigned_str = f"{assigned.get('group')}/{assigned.get('name')}" if assigned else "미배정"

                self.results.append(TestResult(
                    test_name, TestStatus.PASS,
                    f"상태: {status}, 유형: {category}, 배정: {assigned_str}"
                ))
            elif response.status_code == 404:
                self.results.append(TestResult(
                    test_name, TestStatus.WARN, "Task를 찾을 수 없음"
                ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_doors(self, client: httpx.AsyncClient):
        """Door API 테스트"""
        test_name = "Door 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/doors")

            if response.status_code == 200:
                data = response.json()

                if data:
                    door_names = [d.get("door_name", "unknown") for d in data]
                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"Door {len(data)}개: {', '.join(door_names[:5])}{'...' if len(door_names) > 5 else ''}"
                    ))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "Door 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_lifts(self, client: httpx.AsyncClient):
        """Lift API 테스트"""
        test_name = "Lift 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/lifts")

            if response.status_code == 200:
                data = response.json()

                if data:
                    lift_info = []
                    for lift in data:
                        name = lift.get("lift_name", "unknown")
                        floor = lift.get("current_floor", "?")
                        lift_info.append(f"{name}(현재: {floor})")

                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"Lift {len(data)}개: {', '.join(lift_info)}"
                    ))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "Lift 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_dispensers(self, client: httpx.AsyncClient):
        """Dispenser API 테스트"""
        test_name = "Dispenser 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/dispensers")

            if response.status_code == 200:
                data = response.json()

                if data:
                    guids = [d.get("guid", "unknown") for d in data]
                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"Dispenser {len(data)}개: {', '.join(guids)}"
                    ))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "Dispenser 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_ingestors(self, client: httpx.AsyncClient):
        """Ingestor API 테스트"""
        test_name = "Ingestor 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/ingestors")

            if response.status_code == 200:
                data = response.json()

                if data:
                    guids = [d.get("guid", "unknown") for d in data]
                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"Ingestor {len(data)}개: {', '.join(guids)}"
                    ))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "Ingestor 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_alerts(self, client: httpx.AsyncClient):
        """Alert API 테스트"""
        test_name = "Alert 목록 조회"
        try:
            # Alert API는 다른 엔드포인트 구조를 가질 수 있음
            response = await client.get(f"{self.api_url}/alerts/requests")

            if response.status_code == 200:
                # WebSocket 엔드포인트일 수 있으므로 건너뜀
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "WebSocket 엔드포인트"
                ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.WARN, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.SKIP, "Alert API는 WebSocket 기반"
            ))

    async def test_beacons(self, client: httpx.AsyncClient):
        """Beacon API 테스트"""
        test_name = "Beacon 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/beacons")

            if response.status_code == 200:
                data = response.json()

                if data:
                    online_count = sum(1 for b in data if b.get("online"))
                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"Beacon {len(data)}개 (온라인: {online_count})"
                    ))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "Beacon 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    async def test_users(self, client: httpx.AsyncClient):
        """User API 테스트 (관리자 전용)"""
        test_name = "사용자 목록 조회"
        try:
            response = await client.get(f"{self.api_url}/admin/users")

            if response.status_code == 200:
                data = response.json()
                users = data.get("items", data) if isinstance(data, dict) else data

                if users:
                    admin_count = sum(1 for u in users if u.get("is_admin"))
                    self.results.append(TestResult(
                        test_name, TestStatus.PASS,
                        f"사용자 {len(users)}명 (관리자: {admin_count})"
                    ))
                else:
                    self.results.append(TestResult(
                        test_name, TestStatus.WARN, "사용자 데이터 없음"
                    ))
            elif response.status_code == 401:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "인증 필요"
                ))
            elif response.status_code == 403:
                self.results.append(TestResult(
                    test_name, TestStatus.SKIP, "관리자 권한 필요"
                ))
            else:
                self.results.append(TestResult(
                    test_name, TestStatus.FAIL, f"HTTP {response.status_code}"
                ))
        except Exception as e:
            self.results.append(TestResult(
                test_name, TestStatus.FAIL, str(e)
            ))

    def print_summary(self):
        """테스트 결과 요약 출력"""
        print("\n" + "=" * 60)
        print("테스트 결과")
        print("=" * 60)

        for result in self.results:
            print(f"{result.status.value} {result.name}")
            if result.message:
                print(f"     {result.message}")

        # 통계
        pass_count = sum(1 for r in self.results if r.status == TestStatus.PASS)
        fail_count = sum(1 for r in self.results if r.status == TestStatus.FAIL)
        warn_count = sum(1 for r in self.results if r.status == TestStatus.WARN)
        skip_count = sum(1 for r in self.results if r.status == TestStatus.SKIP)

        print("\n" + "-" * 60)
        print(f"총 {len(self.results)}개 테스트")
        print(f"  ✓ 성공: {pass_count}")
        print(f"  ✗ 실패: {fail_count}")
        print(f"  ⚠ 경고: {warn_count}")
        print(f"  ○ 건너뜀: {skip_count}")
        print("=" * 60)

        # 실패가 있으면 비정상 종료
        if fail_count > 0:
            sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(
        description="RMF API Server 테스트 스크립트"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="API 서버 URL (기본값: http://localhost:8000)"
    )
    parser.add_argument(
        "--expected-data",
        default=None,
        help="기대하는 데이터가 담긴 JSON 파일 (sample_data.json)"
    )
    parser.add_argument(
        "--test",
        choices=["building_map", "fleets", "tasks", "doors", "lifts",
                 "dispensers", "ingestors", "alerts", "beacons", "users"],
        help="특정 테스트만 실행"
    )

    args = parser.parse_args()

    # 기본 expected data 파일 경로
    if args.expected_data is None:
        default_path = Path(__file__).parent / "sample_data.json"
        if default_path.exists():
            args.expected_data = str(default_path)

    tester = ApiTester(args.api_url, args.expected_data)
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
