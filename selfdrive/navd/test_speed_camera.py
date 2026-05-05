from pathlib import Path

import openpilot.selfdrive.navd.speed_camera as speed_camera
from openpilot.selfdrive.navd.speed_camera import (
  camera_type_code,
  create_database_from_csv,
  database_data_date,
  direction_bearing_deg,
  download_public_speed_camera_csv,
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

  permissive_camera = find_lead_camera(db_path, 37.0, 127.0, 0.0, camera_direction_angle_deg=181.0)
  assert permissive_camera is not None
  assert permissive_camera.id.startswith("A1-")


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
  assert database_data_date(db_path) == "2026-01-29"


def test_download_public_speed_camera_csv(tmp_path: Path, monkeypatch) -> None:
  def fake_fetch(path: str, params: dict, timeout: int = speed_camera.DATA_GO_KR_TIMEOUT_SECONDS):
    if path.endswith("columList.json"):
      return {
        "totalCount": 2,
        "fileName": "전국무인교통단속카메라표준데이터",
        "columList": [
          {"columCode": "MNLSS_REGLT_CAMERA_MANAGE_NO", "columNm": "무인교통단속카메라관리번호"},
          {"columCode": "LATITUDE", "columNm": "위도"},
          {"columCode": "LONGITUDE", "columNm": "경도"},
          {"columCode": "REGLT_SE", "columNm": "단속구분"},
          {"columCode": "LMTT_VE", "columNm": "제한속도"},
          {"columCode": "ITLPC", "columNm": "설치장소"},
        ],
        "tableVO": {
          "colNmList": ["MNLSS_REGLT_CAMERA_MANAGE_NO", "LATITUDE", "LONGITUDE", "REGLT_SE", "LMTT_VE", "ITLPC"],
          "svcTableNm": "tn_pubr_public_unmanned_traffic_camera_svc",
        },
      }
    assert path.endswith("standard.json")
    assert params["page"] == 1
    return [
      {
        "MNLSS_REGLT_CAMERA_MANAGE_NO": "J0071",
        "LATITUDE": "35.765665",
        "LONGITUDE": "128.13621",
        "REGLT_SE": "01",
        "LMTT_VE": "40",
        "ITLPC": "야천삼거리",
      },
      {
        "MNLSS_REGLT_CAMERA_MANAGE_NO": "J0070",
        "LATITUDE": "35.7655683",
        "LONGITUDE": "128.1360521",
        "REGLT_SE": "01",
        "LMTT_VE": "60",
        "ITLPC": "야천삼거리",
      },
    ]

  monkeypatch.setattr(speed_camera, "_fetch_data_go_json", fake_fetch)

  csv_path = tmp_path / "speed_cameras.csv"
  db_path = tmp_path / "speed_cameras.sqlite3"
  progress = []

  assert download_public_speed_camera_csv(
    csv_path,
    per_page=10000,
    progress_callback=lambda written, total: progress.append((written, total)),
  ) == 2
  assert create_database_from_csv(csv_path, db_path) == 2
  assert progress == [(0, 2), (2, 2)]
