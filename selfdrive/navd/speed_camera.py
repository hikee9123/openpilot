#!/usr/bin/env python3
import csv
import json
import math
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DB_VERSION = 1
PUBLIC_DATA_PK = "15028200"
PUBLIC_DATA_BASE_URL = "https://www.data.go.kr"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def _default_data_root() -> Path:
  if "SPEED_CAMERA_ROOT" in os.environ:
    return Path(os.environ["SPEED_CAMERA_ROOT"])
  return DEFAULT_DATA_DIR


DEFAULT_DB_PATH = _default_data_root() / "speed_cameras.sqlite3"
DEFAULT_CSV_PATH = _default_data_root() / "speed_cameras.csv"

LOOKAHEAD_DISTANCE_M = 2500.0
LOOKAHEAD_ANGLE_DEG = 45.0
CAMERA_DIRECTION_ANGLE_DEG = 70.0
EARTH_RADIUS_M = 6371000.0
DATA_GO_KR_TIMEOUT_SECONDS = 30
DATA_GO_KR_RETRY_COUNT = 3
DATA_GO_KR_USER_AGENT = "Mozilla/5.0 (openpilot speed camera updater)"


FIELD_ALIASES = {
  "id": ("무인교통단속카메라관리번호", "무인교통단속카메라 관리번호", "관리번호", "MNLSS_REGLT_CAMERA_MANAGE_NO", "id"),
  "lat": ("위도", "LATITUDE", "lat", "latitude"),
  "lon": ("경도", "LONGITUDE", "lon", "lng", "longitude"),
  "camera_type": ("단속구분", "단속유형", "REGLT_SE", "camera_type", "type"),
  "speed_limit": ("제한속도", "제한속도(km/h)", "LMTT_VE", "speed_limit"),
  "road_name": ("도로노선명", "소재지도로명주소", "도로명", "ROAD_ROUTE_NM", "RDNMADR", "road_name"),
  "place": ("설치장소", "소재지지번주소", "ITLPC", "LNMADR", "place"),
  "direction": ("도로노선방향", "방향", "ROAD_ROUTE_DRC", "direction"),
  "section_type": ("단속구간위치구분", "REGLT_SCTN_LC_SE", "section_type"),
  "section_length_m": ("과속단속구간길이", "과속단속구간길이(m)", "OVRSPD_REGLT_SCTN_LT", "section_length_m"),
  "school_zone": ("보호구역구분", "PRTCAREA_TYPE", "school_zone"),
  "updated_at": ("데이터기준일자", "최종수정일", "REFERENCE_DATE", "updated_at"),
}


@dataclass(frozen=True)
class SpeedCamera:
  id: str
  lat: float
  lon: float
  camera_type: str
  speed_limit: int
  road_name: str
  place: str
  direction: str
  section_type: str
  section_length_m: int
  distance_m: float = 0.0
  bearing_deg: float = 0.0
  angle_diff_deg: float = 0.0


def _first(row: dict[str, str], field: str) -> str:
  for key in FIELD_ALIASES[field]:
    if key in row and row[key] is not None:
      return row[key].strip()
  return ""


def _parse_float(value: str) -> float | None:
  try:
    return float(value.replace(",", ""))
  except (AttributeError, ValueError):
    return None


def _parse_int(value: str) -> int:
  parsed = _parse_float(value)
  return int(parsed) if parsed is not None else 0


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
  for encoding in ("utf-8-sig", "cp949", "euc-kr"):
    try:
      with csv_path.open("r", encoding=encoding, newline="") as f:
        return list(csv.DictReader(f))
    except UnicodeDecodeError:
      continue
  with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
    return list(csv.DictReader(f))


def init_db(conn: sqlite3.Connection) -> None:
  conn.executescript("""
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS speed_cameras (
      id TEXT PRIMARY KEY,
      lat REAL NOT NULL,
      lon REAL NOT NULL,
      camera_type TEXT NOT NULL,
      speed_limit INTEGER NOT NULL,
      road_name TEXT NOT NULL,
      place TEXT NOT NULL,
      direction TEXT NOT NULL,
      section_type TEXT NOT NULL,
      section_length_m INTEGER NOT NULL,
      school_zone TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_lat_lon ON speed_cameras(lat, lon);
  """)
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("version", str(DB_VERSION)))
  conn.commit()


def create_database_from_csv(csv_path: Path = DEFAULT_CSV_PATH, db_path: Path = DEFAULT_DB_PATH) -> int:
  rows = _read_csv_rows(csv_path)
  db_path.parent.mkdir(parents=True, exist_ok=True)

  with sqlite3.connect(db_path) as conn:
    init_db(conn)
    conn.execute("DELETE FROM speed_cameras")

    inserted = 0
    for idx, row in enumerate(rows):
      lat = _parse_float(_first(row, "lat"))
      lon = _parse_float(_first(row, "lon"))
      if lat is None or lon is None:
        continue

      raw_camera_id = _first(row, "id") or f"camera-{idx}"
      camera_id = f"{raw_camera_id}-{lat:.7f}-{lon:.7f}"
      conn.execute("""
        INSERT OR REPLACE INTO speed_cameras(
          id, lat, lon, camera_type, speed_limit, road_name, place, direction,
          section_type, section_length_m, school_zone, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """, (
        camera_id,
        lat,
        lon,
        _first(row, "camera_type"),
        _parse_int(_first(row, "speed_limit")),
        _first(row, "road_name"),
        _first(row, "place"),
        _first(row, "direction"),
        _first(row, "section_type"),
        _parse_int(_first(row, "section_length_m")),
        _first(row, "school_zone"),
        _first(row, "updated_at"),
      ))
      inserted += 1

    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM speed_cameras").fetchone()[0]


def _fetch_data_go_json(path: str, params: dict, timeout: int = DATA_GO_KR_TIMEOUT_SECONDS):
  url = f"{PUBLIC_DATA_BASE_URL}{path}?{urlencode(params, doseq=True)}"
  request = Request(url, headers={"User-Agent": DATA_GO_KR_USER_AGENT, "Accept": "application/json"})
  for attempt in range(DATA_GO_KR_RETRY_COUNT):
    try:
      with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
    except OSError:
      if attempt == DATA_GO_KR_RETRY_COUNT - 1:
        raise
      time.sleep(1.0 + attempt)


def download_public_speed_camera_csv(
  csv_path: Path = DEFAULT_CSV_PATH,
  public_data_pk: str = PUBLIC_DATA_PK,
  per_page: int = 10000,
  max_pages: int | None = None,
  progress_callback: Callable[[int, int], None] | None = None,
) -> int:
  header = _fetch_data_go_json("/download/columList.json", {"pk": public_data_pk, "ext": "CSV"})
  column_list = header["columList"]
  column_codes = [item["columCode"] for item in column_list]
  column_names = [item["columNm"] for item in column_list]
  total_count = int(header["totalCount"])
  svc_table_name = header["tableVO"]["svcTableNm"]
  col_name_list = header["tableVO"].get("colNmList") or column_codes

  per_page = max(1, min(10000, int(per_page)))
  page_count = math.ceil(total_count / per_page)
  if max_pages is not None:
    page_count = min(page_count, max(0, int(max_pages)))

  csv_path.parent.mkdir(parents=True, exist_ok=True)
  written = 0
  if progress_callback is not None:
    progress_callback(written, total_count)

  with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(column_names)

    for page in range(1, page_count + 1):
      rows = _fetch_data_go_json("/download/standard.json", {
        "publicDataPk": public_data_pk,
        "colNmList": col_name_list,
        "totalCount": total_count,
        "svcTableNm": svc_table_name,
        "perPage": per_page,
        "page": page,
      })
      if not isinstance(rows, list):
        raise ValueError(f"unexpected public data response on page {page}: {type(rows).__name__}")

      for row in rows:
        writer.writerow([row.get(code, "") for code in column_codes])
        written += 1
      if progress_callback is not None:
        progress_callback(written, total_count)

  return written


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  d_phi = math.radians(lat2 - lat1)
  d_lambda = math.radians(lon2 - lon1)

  a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
  return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  d_lambda = math.radians(lon2 - lon1)

  y = math.sin(d_lambda) * math.cos(phi2)
  x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
  return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
  return abs((a - b + 180.0) % 360.0 - 180.0)


def camera_type_code(camera_type: str, section_type: str = "") -> int:
  code = camera_type.strip()
  if code in ("01", "1"):
    return 1
  if code in ("02", "2"):
    return 2
  if code in ("03", "3", "04", "4"):
    return 0

  text = f"{camera_type} {section_type}"
  has_speed = "속도" in text or "과속" in text
  has_signal = "신호" in text
  has_section = "구간" in text

  if has_section:
    return 4
  if has_speed and has_signal:
    return 3
  if has_speed:
    return 1
  if has_signal:
    return 2
  return 0


def direction_bearing_deg(direction: str) -> float | None:
  normalized = direction.strip().upper()
  if not normalized:
    return None

  directions = [
    (("북", "NORTH", "NB"), 0.0),
    (("동", "EAST", "EB"), 90.0),
    (("남", "SOUTH", "SB"), 180.0),
    (("서", "WEST", "WB"), 270.0),
  ]
  matches = [bearing for names, bearing in directions if any(name in normalized for name in names)]
  if len(matches) == 1:
    return matches[0]
  return None


def _bounding_box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
  lat_delta = math.degrees(radius_m / EARTH_RADIUS_M)
  lon_radius = max(math.cos(math.radians(lat)), 0.01)
  lon_delta = math.degrees(radius_m / (EARTH_RADIUS_M * lon_radius))
  return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _row_to_camera(row: sqlite3.Row, distance_m: float, bearing: float, angle_diff: float) -> SpeedCamera:
  return SpeedCamera(
    id=row["id"],
    lat=row["lat"],
    lon=row["lon"],
    camera_type=row["camera_type"],
    speed_limit=row["speed_limit"],
    road_name=row["road_name"],
    place=row["place"],
    direction=row["direction"],
    section_type=row["section_type"],
    section_length_m=row["section_length_m"],
    distance_m=distance_m,
    bearing_deg=bearing,
    angle_diff_deg=angle_diff,
  )


def find_lead_camera(
  db_path: Path,
  lat: float,
  lon: float,
  heading_deg: float,
  max_distance_m: float = LOOKAHEAD_DISTANCE_M,
  max_angle_deg: float = LOOKAHEAD_ANGLE_DEG,
  camera_direction_angle_deg: float = CAMERA_DIRECTION_ANGLE_DEG,
  ignored_ids: set[str] | None = None,
) -> SpeedCamera | None:
  if not db_path.exists():
    return None

  ignored_ids = ignored_ids or set()
  lat_min, lat_max, lon_min, lon_max = _bounding_box(lat, lon, max_distance_m)

  with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
      SELECT * FROM speed_cameras
      WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
    """, (lat_min, lat_max, lon_min, lon_max)).fetchall()

  best: SpeedCamera | None = None
  for row in rows:
    if row["id"] in ignored_ids:
      continue

    distance = haversine_distance_m(lat, lon, row["lat"], row["lon"])
    if distance > max_distance_m:
      continue

    cam_bearing = bearing_deg(lat, lon, row["lat"], row["lon"])
    diff = angle_diff_deg(cam_bearing, heading_deg)
    if diff > max_angle_deg:
      continue

    camera_direction = direction_bearing_deg(row["direction"])
    if camera_direction is not None and angle_diff_deg(camera_direction, heading_deg) > camera_direction_angle_deg:
      continue

    camera = _row_to_camera(row, distance, cam_bearing, diff)
    if best is None or camera.distance_m < best.distance_m:
      best = camera

  return best
