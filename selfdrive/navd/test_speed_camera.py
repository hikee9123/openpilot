from pathlib import Path

from openpilot.selfdrive.navd.speed_camera import (
  camera_type_code,
  create_database_from_csv,
  direction_bearing_deg,
  find_lead_camera,
)


def test_import_and_find_lead_camera(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  csv_path.write_text(
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,설치장소\n"
    "A1,37.001,127.0,속도위반,80,전방도로\n"
    "A2,36.999,127.0,속도위반,60,후방도로\n",
    encoding="utf-8-sig",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  front_camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  rear_camera = find_lead_camera(db_path, 37.0, 127.0, 180.0)

  assert front_camera is not None
  assert front_camera.id.startswith("A1-")
  assert front_camera.speed_limit == 80

  assert rear_camera is not None
  assert rear_camera.id.startswith("A2-")


def test_camera_type_code() -> None:
  assert camera_type_code("속도위반") == 1
  assert camera_type_code("신호위반") == 2
  assert camera_type_code("신호+속도위반") == 3
  assert camera_type_code("구간단속") == 4
  assert camera_type_code("01") == 1
  assert camera_type_code("02") == 2
  assert camera_type_code("1") == 1
  assert camera_type_code("2") == 2


def test_camera_direction_filter(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  csv_path.write_text(
    "무인교통단속카메라관리번호,위도,경도,단속구분,제한속도,도로노선방향\n"
    "A1,37.001,127.0,속도위반,80,남\n"
    "A2,37.002,127.0,속도위반,60,북\n",
    encoding="utf-8-sig",
  )

  assert create_database_from_csv(csv_path, db_path) == 2

  camera = find_lead_camera(db_path, 37.0, 127.0, 0.0)
  assert camera is not None
  assert camera.id.startswith("A2-")


def test_direction_bearing_deg() -> None:
  assert direction_bearing_deg("북") == 0.0
  assert direction_bearing_deg("동") == 90.0
  assert direction_bearing_deg("남") == 180.0
  assert direction_bearing_deg("서") == 270.0
  assert direction_bearing_deg("양방향") is None


def test_public_data_portal_column_codes(tmp_path: Path) -> None:
  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  csv_path.write_text(
    "MNLSS_REGLT_CAMERA_MANAGE_NO,LATITUDE,LONGITUDE,REGLT_SE,LMTT_VE,ROAD_ROUTE_NM,ITLPC,REFERENCE_DATE\n"
    "J0071,35.765665,128.13621,01,40,야천로,야천삼거리,2026-01-29\n",
    encoding="utf-8",
  )

  assert create_database_from_csv(csv_path, db_path) == 1

  camera = find_lead_camera(db_path, 35.764665, 128.13621, 0.0)
  assert camera is not None
  assert camera.id.startswith("J0071-")
  assert camera.speed_limit == 40
  assert camera.camera_type == "01"
