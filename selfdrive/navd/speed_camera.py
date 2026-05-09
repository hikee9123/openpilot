#!/usr/bin/env python3
import csv
import json
import math
import os
import re
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
  from openpilot.selfdrive.navd.paths import (
    DEFAULT_NAVD_DB_DIR,
    DEFAULT_NAVD_ROOT,
    DEFAULT_NAVD_SOURCE_DIR,
    DEFAULT_NAVD_TMP_DIR,
    REPO_NAVD_DATA_DIR,
  )
  from openpilot.selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, find_current_road, road_name_matches
except ModuleNotFoundError:
  from selfdrive.navd.paths import (
    DEFAULT_NAVD_DB_DIR,
    DEFAULT_NAVD_ROOT,
    DEFAULT_NAVD_SOURCE_DIR,
    DEFAULT_NAVD_TMP_DIR,
    REPO_NAVD_DATA_DIR,
  )
  from selfdrive.navd.osm_roads import DEFAULT_OSM_ROADS_DB_PATH, find_current_road, road_name_matches


DB_VERSION = 9
PUBLIC_DATA_PK = "15028200"
PUBLIC_DATA_BASE_URL = "https://www.data.go.kr"
DEFAULT_DATA_DIR = REPO_NAVD_DATA_DIR


def _default_source_root() -> Path:
  if "SPEED_CAMERA_ROOT" in os.environ:
    return Path(os.environ["SPEED_CAMERA_ROOT"])
  return DEFAULT_NAVD_SOURCE_DIR


def _default_db_root() -> Path:
  if "SPEED_CAMERA_DB_ROOT" in os.environ:
    return Path(os.environ["SPEED_CAMERA_DB_ROOT"])
  if "SPEED_CAMERA_ROOT" in os.environ:
    return Path(os.environ["SPEED_CAMERA_ROOT"])
  return DEFAULT_NAVD_DB_DIR


DEFAULT_DB_PATH = Path(os.getenv("SPEED_CAMERA_DB", str(_default_db_root() / "speed_cameras.sqlite3")))
DEFAULT_CSV_PATH = Path(os.getenv("SPEED_CAMERA_CSV", str(_default_source_root() / "speed_cameras.csv")))
DEFAULT_REGION_DIR = Path(os.getenv("SPEED_CAMERA_REGION_DIR", str(_default_source_root() / "region")))
DEFAULT_MAP_HTML_PATH = Path(os.getenv("SPEED_CAMERA_MAP_HTML", str(DEFAULT_NAVD_ROOT / "speed_cameras.html")))
DEFAULT_DOWNLOAD_TMP_DIR = DEFAULT_NAVD_TMP_DIR

LOOKAHEAD_DISTANCE_M = 2500.0
LOOKAHEAD_ANGLE_DEG = 45.0
CAMERA_DIRECTION_ANGLE_DEG = 70.0
LOOKAHEAD_SIDE_DISTANCE_M = 180.0
LOOKAHEAD_EXPRESSWAY_SIDE_DISTANCE_M = 90.0
LOOKAHEAD_LOCAL_ROAD_SIDE_DISTANCE_M = 260.0
LOOKAHEAD_FORWARD_ROAD_MAX_ANGLE_DEG = 50.0
LOOKAHEAD_FORWARD_ROAD_DEFAULT_SIDE_DISTANCE_M = 45.0
LOOKAHEAD_FORWARD_ROAD_MAJOR_SIDE_DISTANCE_M = 80.0
MANAGE_NO_DEDUP_DISTANCE_M = 50.0
OSM_EXTENDED_LOOKUP_RADIUS_MULTIPLIER = 1.8
EARTH_RADIUS_M = 6371000.0
DATA_GO_KR_TIMEOUT_SECONDS = 30
DATA_GO_KR_RETRY_COUNT = 3
DATA_GO_KR_USER_AGENT = "Mozilla/5.0 (openpilot speed camera updater)"


FIELD_ALIASES = {
  "id": (
    "무인교통단속카메라관리번호",
    "무인교통단속카메라 관리번호",
    "관리번호",
    "MNLSS_REGLT_CAMERA_MANAGE_NO",
    "manage_no",
    "camera_id",
    "id",
  ),
  "lat": ("위도", "LATITUDE", "lat", "latitude"),
  "lon": ("경도", "LONGITUDE", "lon", "lng", "longitude"),
  "camera_type": (
    "단속구분",
    "단속유형",
    "단속종류",
    "REGLT_SE",
    "regltSe",
    "camera_type",
    "type",
  ),
  "speed_limit": ("제한속도", "제한속도(km/h)", "LMTT_VE", "lmttVe", "speed_limit"),
  "region": ("시도명", "시도", "CTPRVN_NM", "SIDO_NM", "region", "sido"),
  "road_type": (
    "도로종류",
    "도로구분",
    "도로유형",
    "ROAD_KND",
    "roadKnd",
    "road_knd",
    "road_type",
  ),
  "road_name": ("도로노선명", "소재지도로명주소", "도로명", "ROAD_ROUTE_NM", "RDNMADR", "road_name"),
  "place": ("설치장소", "소재지지번주소", "ITLPC", "LNMADR", "place"),
  "direction": ("도로노선방향", "방향", "ROAD_ROUTE_DRC", "direction"),
  "section_type": ("단속구간위치구분", "REGLT_SCTN_LC_SE", "section_type"),
  "section_length_m": ("과속단속구간길이", "과속단속구간길이(m)", "OVRSPD_REGLT_SCTN_LT", "section_length_m"),
  "school_zone": ("보호구역구분", "PRTCAREA_TYPE", "school_zone"),
  "updated_at": ("데이터기준일자", "최종수정일", "REFERENCE_DATE", "updated_at"),
}

REGION_ALIASES = {
  "강원": "강원특별자치도",
  "강원도": "강원특별자치도",
  "강원특별자치도": "강원특별자치도",
  "경기": "경기도",
  "경기도": "경기도",
  "경남": "경상남도",
  "경상남도": "경상남도",
  "경북": "경상북도",
  "경상북도": "경상북도",
  "광주": "광주광역시",
  "광주광역시": "광주광역시",
  "대구": "대구광역시",
  "대구광역시": "대구광역시",
  "대전": "대전광역시",
  "대전광역시": "대전광역시",
  "부산": "부산광역시",
  "부산광역시": "부산광역시",
  "서울": "서울특별시",
  "서울시": "서울특별시",
  "서울특별시": "서울특별시",
  "세종": "세종특별자치시",
  "세종시": "세종특별자치시",
  "세종특별자치시": "세종특별자치시",
  "울산": "울산광역시",
  "울산광역시": "울산광역시",
  "인천": "인천광역시",
  "인천광역시": "인천광역시",
  "전남": "전라남도",
  "전라남도": "전라남도",
  "전북": "전북특별자치도",
  "전라북도": "전북특별자치도",
  "전북특별자치도": "전북특별자치도",
  "제주": "제주특별자치도",
  "제주도": "제주특별자치도",
  "제주특별자치도": "제주특별자치도",
  "충남": "충청남도",
  "충청남도": "충청남도",
  "충북": "충청북도",
  "충청북도": "충청북도",
}

CAMERA_CATEGORY_CODES = {
  "ETC": 0,
  "SPEED": 1,
  "SIGNAL": 2,
  "SPEED_SIGNAL": 3,
  "SECTION_SPEED": 4,
  "PARKING": 5,
  "BUS_LANE": 6,
  "TRAFFIC": 7,
  "SECURITY": 8,
  "UNKNOWN": 9,
  "PROTECTED_ZONE": 10,
}

ROAD_CLASS_CODES = {
  "UNKNOWN": 0,
  "EXPRESSWAY": 1,
  "NATIONAL_ROAD": 2,
  "NATIONAL_LOCAL_ROAD": 3,
  "LOCAL_ROAD": 4,
  "CITY_ROAD": 5,
  "COUNTY_ROAD": 6,
  "DISTRICT_ROAD": 7,
  "ETC": 8,
}

SOURCE_TYPE_PRIORITY = {
  "public": 1,
  "region": 2,
  "custom": 3,
}

SPEED_CAMERA_COLUMNS = (
  "id",
  "lat",
  "lon",
  "camera_type",
  "camera_type_raw",
  "camera_category",
  "camera_type_code",
  "is_speed_camera",
  "is_signal_camera",
  "is_section_camera",
  "is_etc_camera",
  "speed_limit",
  "region",
  "road_type_raw",
  "road_class",
  "road_class_code",
  "is_expressway",
  "is_national_road",
  "road_name",
  "place",
  "direction",
  "section_type",
  "section_length_m",
  "school_zone",
  "updated_at",
  "source_type",
  "source_file",
  "dedup_key",
  "osm_road_name",
  "osm_road_ref",
  "osm_road_match_dist_m",
  "osm_road_match_heading_deg",
)


@dataclass(frozen=True)
class CsvSource:
  path: Path
  source_type: str


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
  forward_m: float = 0.0
  side_m: float = 0.0
  bearing_deg: float = 0.0
  angle_diff_deg: float = 0.0
  relative_angle_deg: float = 0.0
  camera_category: str = "UNKNOWN"
  camera_type_code: int = 0
  region: str = ""
  road_type_raw: str = ""
  road_class: str = "UNKNOWN"
  road_class_code: int = 0
  is_expressway: bool = False
  is_national_road: bool = False
  source_type: str = ""
  source_file: str = ""
  osm_road_name: str = ""
  osm_road_ref: str = ""
  osm_road_match_dist_m: float = 0.0
  osm_road_match_heading_deg: float = 0.0
  local_road_match: bool = False
  forward_road_match: bool = False
  direction_kind: str = ""
  route_hint: str = ""


@dataclass(frozen=True)
class OsmRoadEnrichmentStats:
  total_count: int = 0
  matched_count: int = 0
  unmatched_count: int = 0
  primary_match_count: int = 0
  extended_match_count: int = 0
  extended_radius_m: float = 0.0
  unmatched_by_category: tuple[tuple[str, int], ...] = ()

  @property
  def match_percent(self) -> int:
    if self.total_count <= 0:
      return 0
    return int(round(self.matched_count * 100 / self.total_count))


def _first(row: dict[str, str], field: str) -> str:
  aliases = FIELD_ALIASES[field]
  for key in aliases:
    if key in row and row[key] is not None:
      return row[key].strip()

  lower_aliases = {key.lower() for key in aliases}
  for key, value in row.items():
    if key is not None and key.strip().lower() in lower_aliases and value is not None:
      return value.strip()
  return ""


def _parse_float(value: str) -> float | None:
  try:
    return float(value.replace(",", ""))
  except (AttributeError, ValueError):
    return None


def _parse_int(value: str) -> int:
  parsed = _parse_float(value)
  return int(parsed) if parsed is not None else 0


def infer_missing_speed_limit(
  camera_type: str,
  section_type: str,
  road_name: str,
  place: str,
  speed_limit: int,
) -> int:
  if speed_limit > 0:
    return speed_limit

  camera_type = (camera_type or "").strip()
  if camera_type in ("02", "2"):
    return speed_limit

  text = f"{camera_type} {section_type or ''} {road_name or ''} {place or ''}".replace(" ", "")
  protected_keywords = (
    "어린이보호구역",
    "보호구역",
    "초등학교",
    "초교",
    "어린이",
    "노인보호",
  )
  if camera_type in ("04", "4") or any(keyword in text for keyword in protected_keywords):
    return 30

  return speed_limit


def _normalize_region(value: str) -> str:
  token = value.strip().split()[0] if value else ""
  return REGION_ALIASES.get(token, "")


def _extract_region(row: dict[str, str]) -> str:
  direct_region = _normalize_region(_first(row, "region"))
  if direct_region:
    return direct_region

  for field in ("road_name", "place"):
    region = _normalize_region(_first(row, field))
    if region:
      return region
  return "미분류"


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
  for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
    try:
      with csv_path.open("r", encoding=encoding, newline="") as f:
        return list(csv.DictReader(f))
    except UnicodeDecodeError:
      continue
  with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
    return list(csv.DictReader(f))


def normalize_camera_category(
  camera_type: str,
  section_type: str = "",
  context_text: str = "",
  speed_limit: int = 0,
) -> str:
  camera_type = (camera_type or "").strip()
  section_type = (section_type or "").strip()
  context_text = (context_text or "").strip()
  raw = f"{camera_type} {section_type}".strip()
  context_raw = f"{raw} {context_text}".strip()
  context_compact = context_raw.replace(" ", "")
  compact = raw.replace(" ", "").upper()

  if not raw:
    return "UNKNOWN"

  if camera_type in ("03", "3"):
    return "SECURITY"

  if camera_type in ("04", "4"):
    return "PROTECTED_ZONE"

  has_speed = (
    camera_type in ("01", "1") or
    compact in ("01+02", "1+2", "01/02", "1/02", "01/2") or
    "과속" in raw or
    "속도" in raw or
    "SPEED" in compact
  )

  has_signal = (
    camera_type in ("02", "2") or
    compact in ("01+02", "1+2", "01/02", "1/02", "01/2") or
    "신호" in raw or
    "SIGNAL" in compact
  )
  if camera_type in ("02", "2") and speed_limit > 0:
    has_speed = True

  has_section = (
    (camera_type == "99" and section_type in ("01", "1", "02", "2")) or
    (camera_type == "99" and any(keyword in context_raw for keyword in ("구간", "시점", "종점"))) or
    (camera_type == "99" and "어린이보호구역" in context_compact) or
    (camera_type == "99" and speed_limit == 30 and "초등학교" in context_compact) or
    "구간" in raw or
    "SECTION" in compact
  )

  if has_section:
    return "SECTION_SPEED"

  if has_speed and has_signal:
    return "SPEED_SIGNAL"

  if has_speed:
    return "SPEED"

  if has_signal:
    return "SIGNAL"

  if "주정차" in raw or "불법주정차" in raw or "주차" in raw or "정차" in raw:
    return "PARKING"

  if "버스전용" in raw or "버스차로" in raw or "버스" in raw:
    return "BUS_LANE"

  if "통행" in raw or "진입" in raw or "교차로" in raw or "꼬리" in raw or "끼어들기" in raw:
    return "TRAFFIC"

  if "방범" in raw or "CCTV" in compact:
    return "SECURITY"

  if "기타" in raw or compact == "ETC":
    return "ETC"

  return "UNKNOWN"


def camera_category_code(camera_category: str) -> int:
  return CAMERA_CATEGORY_CODES.get(camera_category, 0)


def is_speed_category(camera_category: str) -> bool:
  return camera_category in ("SPEED", "SPEED_SIGNAL", "SECTION_SPEED")


def is_signal_category(camera_category: str) -> bool:
  return camera_category in ("SIGNAL", "SPEED_SIGNAL")


def is_section_category(camera_category: str) -> bool:
  return camera_category == "SECTION_SPEED"


def is_etc_category(camera_category: str) -> bool:
  return camera_category not in ("SPEED", "SIGNAL", "SPEED_SIGNAL", "SECTION_SPEED")


def _is_alertable_category(camera_category: str) -> bool:
  return (
    is_speed_category(camera_category) or
    is_signal_category(camera_category) or
    camera_category in ("SECURITY", "PROTECTED_ZONE")
  )


def same_corridor_likely(camera: "SpeedCamera") -> bool:
  angle = abs(camera.relative_angle_deg)
  if angle <= 15.0:
    return True
  if camera.is_expressway and angle <= 25.0:
    return True
  return False


def forward_road_likely(camera: "SpeedCamera") -> bool:
  side_limit = (
    LOOKAHEAD_FORWARD_ROAD_MAJOR_SIDE_DISTANCE_M
    if camera.is_expressway or camera.is_national_road
    else LOOKAHEAD_FORWARD_ROAD_DEFAULT_SIDE_DISTANCE_M
  )
  return (
    camera.forward_m > 0.0 and
    abs(camera.side_m) <= side_limit and
    abs(camera.relative_angle_deg) <= LOOKAHEAD_FORWARD_ROAD_MAX_ANGLE_DEG and
    (camera.local_road_match or same_corridor_likely(camera))
  )


def _alert_priority(camera: "SpeedCamera") -> tuple[int, int, int, int, float, float, float]:
  return (
    0 if is_speed_category(camera.camera_category) else 1,
    0 if camera.forward_road_match else 1,
    0 if camera.local_road_match else 1,
    0 if same_corridor_likely(camera) else 1,
    abs(camera.side_m),
    max(0.0, camera.forward_m),
    abs(camera.relative_angle_deg),
  )


def camera_type_code(camera_type: str, section_type: str = "", context_text: str = "", speed_limit: int = 0) -> int:
  category = normalize_camera_category(camera_type, section_type, context_text, speed_limit)
  return camera_category_code(category)


def _compact_road_text(value: str) -> str:
  return re.sub(r"\s+", "", value or "").upper()


def _road_class_from_type(road_type: str) -> str:
  compact = _compact_road_text(road_type)
  if not compact:
    return "UNKNOWN"

  if "고속국도" in compact or compact == "고속도로":
    return "EXPRESSWAY"

  if "일반국도" in compact or compact == "국도":
    return "NATIONAL_ROAD"

  if "국가지원지방도" in compact or "국지도" in compact:
    return "NATIONAL_LOCAL_ROAD"

  if "지방도" in compact:
    return "LOCAL_ROAD"

  if "특별시도" in compact or "특별광역시도" in compact or compact == "시도":
    return "CITY_ROAD"

  if "군도" in compact:
    return "COUNTY_ROAD"

  if "구도" in compact:
    return "DISTRICT_ROAD"

  if "기타" in compact or compact == "ETC":
    return "ETC"

  return "UNKNOWN"


def _looks_like_expressway_name(road_name: str, place: str) -> bool:
  compact = _compact_road_text(f"{road_name or ''} {place or ''}")
  if not compact:
    return False

  if any(excluded in compact for excluded in (
    "고속버스",
    "고속터미널",
    "고속철",
    "고속주유소",
    "고속화도로",
    "도시고속",
    "고속도로진입",
    "고속도로방면",
  )):
    return False

  return "고속국도" in compact or "고속도로" in compact


def normalize_road_class(road_type: str, road_name: str = "", place: str = "") -> str:
  road_class = _road_class_from_type(road_type)
  if road_class != "UNKNOWN":
    return road_class

  if _looks_like_expressway_name(road_name, place):
    return "EXPRESSWAY"

  if not f"{road_type or ''} {road_name or ''} {place or ''}".strip():
    return "UNKNOWN"

  return "UNKNOWN"


def road_class_code(road_class: str) -> int:
  return ROAD_CLASS_CODES.get(road_class, 0)


def is_expressway_class(road_class: str) -> bool:
  return road_class == "EXPRESSWAY"


def is_national_road_class(road_class: str) -> bool:
  return road_class == "NATIONAL_ROAD"


def build_dedup_key(
  row: dict[str, str],
  lat: float,
  lon: float,
  speed_limit: int,
  camera_category: str,
  road_class: str,
  region: str,
  place: str,
  fallback_id: str,
) -> str:
  manage_no = _first(row, "id")
  if manage_no:
    return f"NO|{manage_no}"

  if lat is not None and lon is not None:
    return f"GPS|{lat:.6f}|{lon:.6f}|{speed_limit}|{camera_category}|{road_class}"

  if region and place:
    return f"LOC|{region}|{place}|{speed_limit}|{camera_category}|{road_class}"

  return f"ROW|{fallback_id}"


def init_db(conn: sqlite3.Connection, backfill: bool = True) -> None:
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
      camera_type_raw TEXT NOT NULL,
      camera_category TEXT NOT NULL,
      camera_type_code INTEGER NOT NULL,
      is_speed_camera INTEGER NOT NULL,
      is_signal_camera INTEGER NOT NULL,
      is_section_camera INTEGER NOT NULL,
      is_etc_camera INTEGER NOT NULL,
      speed_limit INTEGER NOT NULL,
      region TEXT NOT NULL,
      road_type_raw TEXT NOT NULL,
      road_class TEXT NOT NULL,
      road_class_code INTEGER NOT NULL,
      is_expressway INTEGER NOT NULL,
      is_national_road INTEGER NOT NULL,
      road_name TEXT NOT NULL,
      place TEXT NOT NULL,
      direction TEXT NOT NULL,
      section_type TEXT NOT NULL,
      section_length_m INTEGER NOT NULL,
      school_zone TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      source_type TEXT NOT NULL,
      source_file TEXT NOT NULL,
      dedup_key TEXT NOT NULL,
      osm_road_name TEXT NOT NULL,
      osm_road_ref TEXT NOT NULL,
      osm_road_match_dist_m REAL NOT NULL,
      osm_road_match_heading_deg REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS speed_camera_region_counts (
      region TEXT PRIMARY KEY,
      count INTEGER NOT NULL
    );
  """)

  column_defaults = {
    "region": "TEXT NOT NULL DEFAULT ''",
    "camera_type_raw": "TEXT NOT NULL DEFAULT ''",
    "camera_category": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
    "camera_type_code": "INTEGER NOT NULL DEFAULT 0",
    "is_speed_camera": "INTEGER NOT NULL DEFAULT 0",
    "is_signal_camera": "INTEGER NOT NULL DEFAULT 0",
    "is_section_camera": "INTEGER NOT NULL DEFAULT 0",
    "is_etc_camera": "INTEGER NOT NULL DEFAULT 0",
    "road_type_raw": "TEXT NOT NULL DEFAULT ''",
    "road_class": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
    "road_class_code": "INTEGER NOT NULL DEFAULT 0",
    "is_expressway": "INTEGER NOT NULL DEFAULT 0",
    "is_national_road": "INTEGER NOT NULL DEFAULT 0",
    "source_type": "TEXT NOT NULL DEFAULT 'public'",
    "source_file": "TEXT NOT NULL DEFAULT ''",
    "dedup_key": "TEXT NOT NULL DEFAULT ''",
    "osm_road_name": "TEXT NOT NULL DEFAULT ''",
    "osm_road_ref": "TEXT NOT NULL DEFAULT ''",
    "osm_road_match_dist_m": "REAL NOT NULL DEFAULT 0.0",
    "osm_road_match_heading_deg": "REAL NOT NULL DEFAULT 0.0",
  }
  columns = {row[1] for row in conn.execute("PRAGMA table_info(speed_cameras)")}
  for column, definition in column_defaults.items():
    if column not in columns:
      conn.execute(f"ALTER TABLE speed_cameras ADD COLUMN {column} {definition}")

  conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_speed_cameras_lat_lon
    ON speed_cameras(lat, lon);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_category
    ON speed_cameras(camera_category);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_type_code
    ON speed_cameras(camera_type_code);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_speed
    ON speed_cameras(is_speed_camera);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_signal
    ON speed_cameras(is_signal_camera);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_road_class
    ON speed_cameras(road_class);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_expressway
    ON speed_cameras(is_expressway);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_is_national_road
    ON speed_cameras(is_national_road);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_source
    ON speed_cameras(source_type);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_dedup
    ON speed_cameras(dedup_key);

    CREATE INDEX IF NOT EXISTS idx_speed_cameras_osm_road_name
    ON speed_cameras(osm_road_name);
  """)
  if backfill:
    _backfill_derived_columns(conn)
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("version", str(DB_VERSION)))
  conn.commit()


def _backfill_derived_columns(conn: sqlite3.Connection) -> None:
  rows = conn.execute("""
    SELECT
      id, lat, lon, camera_type, camera_type_raw, camera_category, camera_type_code,
      speed_limit, region, road_type_raw, road_class, road_name, place, section_type,
      source_type, source_file, dedup_key
    FROM speed_cameras
  """).fetchall()

  for row in rows:
    (
      camera_id,
      lat,
      lon,
      camera_type,
      camera_type_raw,
      camera_category,
      _stored_type_code,
      speed_limit,
      _region,
      road_type_raw,
      road_class,
      road_name,
      place,
      section_type,
      source_type,
      source_file,
      dedup_key,
    ) = row

    raw_camera_type = camera_type_raw or camera_type or ""
    speed_limit = infer_missing_speed_limit(
      raw_camera_type, section_type or "", road_name or "", place or "", int(speed_limit or 0)
    )
    category = normalize_camera_category(
      raw_camera_type, section_type or "", f"{road_name or ''} {place or ''}", speed_limit
    )
    type_code = camera_category_code(category)

    raw_road_type = road_type_raw or ""
    normalized_road_class = normalize_road_class(raw_road_type, road_name or "", place or "")
    if normalized_road_class == "UNKNOWN" and road_class:
      normalized_road_class = str(road_class)
    road_code = road_class_code(normalized_road_class)

    normalized_source_type = _source_type(source_type or "public")
    normalized_dedup_key = dedup_key or f"GPS|{float(lat):.6f}|{float(lon):.6f}|{int(speed_limit or 0)}"

    conn.execute("""
      UPDATE speed_cameras
      SET
        camera_type_raw = ?,
        camera_category = ?,
        camera_type_code = ?,
        is_speed_camera = ?,
        is_signal_camera = ?,
        is_section_camera = ?,
        is_etc_camera = ?,
        speed_limit = ?,
        road_type_raw = ?,
        road_class = ?,
        road_class_code = ?,
        is_expressway = ?,
        is_national_road = ?,
        source_type = ?,
        source_file = ?,
        dedup_key = ?
      WHERE id = ?
    """, (
      raw_camera_type,
      category,
      type_code,
      int(is_speed_category(category)),
      int(is_signal_category(category)),
      int(is_section_category(category)),
      int(is_etc_category(category)),
      speed_limit,
      raw_road_type,
      normalized_road_class,
      road_code,
      int(is_expressway_class(normalized_road_class)),
      int(is_national_road_class(normalized_road_class)),
      normalized_source_type,
      source_file or "",
      normalized_dedup_key,
      camera_id,
    ))


def _date_priority(value: str) -> int:
  parts = [int(part) for part in re.findall(r"\d+", value or "")]
  if len(parts) >= 3:
    return parts[0] * 10000 + parts[1] * 100 + parts[2]
  if len(parts) == 1 and parts[0] > 9999999:
    return parts[0]
  return 0


def _source_type(source_type: str) -> str:
  normalized = (source_type or "custom").strip().lower()
  if normalized in SOURCE_TYPE_PRIORITY:
    return normalized
  return "custom"


def _merge_priority(record: dict[str, object]) -> tuple[int, int, int, int, int]:
  return (
    int(str(record["camera_category"]) != "UNKNOWN"),
    _date_priority(str(record["updated_at"])),
    SOURCE_TYPE_PRIORITY.get(str(record["source_type"]), 0),
    int(record["lat"] is not None and record["lon"] is not None),
    len(str(record["place"])),
  )


def _dedup_categories_are_compatible(
  record: dict[str, object],
  cluster: dict[str, object],
) -> bool:
  category = str(record["camera_category"])
  speed_limit = int(record["speed_limit"])
  cluster_categories = set(str(category) for category in cluster["categories"])
  cluster_speed_limits = set(int(speed_limit) for speed_limit in cluster["speed_limits"])
  non_unknown_categories = {cluster_category for cluster_category in cluster_categories if cluster_category != "UNKNOWN"}

  if category != "UNKNOWN":
    if non_unknown_categories and non_unknown_categories != {category}:
      return False
    if "UNKNOWN" not in cluster_categories:
      return True

  if category == "UNKNOWN" and len(non_unknown_categories) > 1:
    return False

  return cluster_speed_limits == {speed_limit}


def _dedup_road_class_is_compatible(
  record: dict[str, object],
  cluster: dict[str, object],
) -> bool:
  road_class = str(record["road_class"])
  cluster_road_classes = set(str(road_class) for road_class in cluster["road_classes"])
  return cluster_road_classes == {road_class}


def _manage_no_dedup_key(
  record: dict[str, object],
  manage_no_clusters: dict[str, list[dict[str, object]]],
) -> str | None:
  manage_no = str(record.get("_manage_no", ""))
  if not manage_no:
    return None

  lat = float(record["lat"])
  lon = float(record["lon"])
  clusters = manage_no_clusters.setdefault(manage_no, [])
  for cluster in clusters:
    distance = haversine_distance_m(lat, lon, float(cluster["lat"]), float(cluster["lon"]))
    if (
      distance <= MANAGE_NO_DEDUP_DISTANCE_M and
      _dedup_categories_are_compatible(record, cluster) and
      _dedup_road_class_is_compatible(record, cluster)
    ):
      cluster["categories"].add(str(record["camera_category"]))
      cluster["speed_limits"].add(int(record["speed_limit"]))
      cluster["road_classes"].add(str(record["road_class"]))
      return str(cluster["key"])

  key = (
    f"NO|{manage_no}|{str(record['camera_category'])}|"
    f"{int(record['speed_limit'])}|{str(record['road_class'])}|{lat:.6f}|{lon:.6f}"
  )
  clusters.append({
    "key": key,
    "lat": lat,
    "lon": lon,
    "categories": {str(record["camera_category"])},
    "speed_limits": {int(record["speed_limit"])},
    "road_classes": {str(record["road_class"])},
  })
  return key


def _standardize_csv_row(row: dict[str, str], csv_source: CsvSource, idx: int) -> dict[str, object] | None:
  lat = _parse_float(_first(row, "lat"))
  lon = _parse_float(_first(row, "lon"))
  if lat is None or lon is None:
    return None

  source_type = _source_type(csv_source.source_type)
  source_file = csv_source.path.name
  manage_no = _first(row, "id")
  raw_camera_id = manage_no or f"{source_type}-{csv_source.path.stem}-{idx}"
  camera_id = f"{raw_camera_id}-{lat:.7f}-{lon:.7f}"

  raw_road_type = _first(row, "road_type")
  road_name = _first(row, "road_name")
  place = _first(row, "place")
  speed_limit = _parse_int(_first(row, "speed_limit"))
  raw_camera_type = _first(row, "camera_type")
  section_type = _first(row, "section_type")
  speed_limit = infer_missing_speed_limit(raw_camera_type, section_type, road_name, place, speed_limit)
  category = normalize_camera_category(raw_camera_type, section_type, f"{road_name} {place}", speed_limit)
  type_code = camera_category_code(category)

  road_class = normalize_road_class(raw_road_type, road_name, place)
  road_code = road_class_code(road_class)
  region = _extract_region(row)
  fallback_id = f"{source_type}-{source_file}-{idx}"
  dedup_key = build_dedup_key(row, lat, lon, speed_limit, category, road_class, region, place, fallback_id)

  return {
    "id": camera_id,
    "lat": lat,
    "lon": lon,
    "camera_type": raw_camera_type,
    "camera_type_raw": raw_camera_type,
    "camera_category": category,
    "camera_type_code": type_code,
    "is_speed_camera": int(is_speed_category(category)),
    "is_signal_camera": int(is_signal_category(category)),
    "is_section_camera": int(is_section_category(category)),
    "is_etc_camera": int(is_etc_category(category)),
    "speed_limit": speed_limit,
    "region": region,
    "road_type_raw": raw_road_type,
    "road_class": road_class,
    "road_class_code": road_code,
    "is_expressway": int(is_expressway_class(road_class)),
    "is_national_road": int(is_national_road_class(road_class)),
    "road_name": road_name,
    "place": place,
    "direction": _first(row, "direction"),
    "section_type": section_type,
    "section_length_m": _parse_int(_first(row, "section_length_m")),
    "school_zone": _first(row, "school_zone"),
    "updated_at": _first(row, "updated_at"),
    "source_type": source_type,
    "source_file": source_file,
    "dedup_key": dedup_key,
    "osm_road_name": "",
    "osm_road_ref": "",
    "osm_road_match_dist_m": 0.0,
    "osm_road_match_heading_deg": 0.0,
    "_manage_no": manage_no,
  }


def create_database_from_csv(csv_path: Path = DEFAULT_CSV_PATH, db_path: Path = DEFAULT_DB_PATH) -> int:
  return create_database_from_csvs([CsvSource(csv_path, "public")], db_path)


def create_database_from_csvs(
  csv_sources: list[CsvSource],
  db_path: Path = DEFAULT_DB_PATH,
  osm_roads_db_path: Path | None = None,
  osm_lookup_radius_m: float = 60.0,
) -> int:
  merged: dict[str, dict[str, object]] = {}
  manage_no_clusters: dict[str, list[dict[str, object]]] = {}
  for csv_source in csv_sources:
    rows = _read_csv_rows(csv_source.path)
    for idx, row in enumerate(rows):
      record = _standardize_csv_row(row, csv_source, idx)
      if record is None:
        continue

      dedup_key = _manage_no_dedup_key(record, manage_no_clusters) or str(record["dedup_key"])
      record["dedup_key"] = dedup_key
      current = merged.get(dedup_key)
      if current is None or _merge_priority(record) > _merge_priority(current):
        merged[dedup_key] = record

  records = sorted(merged.values(), key=lambda record: str(record["id"]))
  db_path.parent.mkdir(parents=True, exist_ok=True)

  with closing(sqlite3.connect(db_path)) as conn:
    init_db(conn, backfill=False)
    conn.execute("DELETE FROM speed_cameras")

    placeholders = ", ".join("?" for _ in SPEED_CAMERA_COLUMNS)
    columns = ", ".join(SPEED_CAMERA_COLUMNS)
    conn.executemany(
      f"INSERT OR REPLACE INTO speed_cameras({columns}) VALUES ({placeholders})",
      [tuple(record[column] for column in SPEED_CAMERA_COLUMNS) for record in records],
    )

    conn.execute("DELETE FROM speed_camera_region_counts")
    conn.execute("""
      INSERT INTO speed_camera_region_counts(region, count)
      SELECT region, COUNT(*)
      FROM speed_cameras
      WHERE is_speed_camera = 1
      GROUP BY region
      ORDER BY region
    """)

    source_updated_at = ""
    if records:
      source_updated_at = str(max(records, key=lambda record: _date_priority(str(record["updated_at"])))["updated_at"])
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("source_updated_at", source_updated_at))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_enriched_count", "0"))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_primary_match_count", "0"))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_extended_match_count", "0"))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_unmatched_count", str(len(records))))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_extended_radius_m", "0"))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_db_path", ""))
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("version", str(DB_VERSION)))
    conn.commit()
    if osm_roads_db_path is not None:
      enrich_speed_camera_osm_roads(conn, osm_roads_db_path, osm_lookup_radius_m)
    return conn.execute("SELECT COUNT(*) FROM speed_cameras").fetchone()[0]


def enrich_speed_camera_osm_roads(
  conn: sqlite3.Connection,
  osm_roads_db_path: Path = DEFAULT_OSM_ROADS_DB_PATH,
  lookup_radius_m: float = 60.0,
) -> int:
  if not osm_roads_db_path.exists():
    return 0

  init_db(conn, backfill=False)
  conn.row_factory = sqlite3.Row
  rows = conn.execute("""
    SELECT id, lat, lon, direction, road_name, place
    FROM speed_cameras
  """).fetchall()

  updates = []
  unmatched_rows = []
  for row in rows:
    camera_direction = direction_bearing_deg(str(_row_get(row, "direction", "")))
    previous_name = f"{_row_get(row, 'road_name', '')} {_row_get(row, 'place', '')}"
    match = find_current_road(
      osm_roads_db_path,
      float(row["lat"]),
      float(row["lon"]),
      camera_direction,
      lookup_radius_m,
      previous_name=previous_name,
    )
    if match is None:
      unmatched_rows.append(row)
      continue
    updates.append((
      match.display_name,
      match.ref,
      float(match.distance_m),
      float(match.heading_diff_deg),
      row["id"],
    ))

  primary_match_count = len(updates)
  extended_radius_m = lookup_radius_m * OSM_EXTENDED_LOOKUP_RADIUS_MULTIPLIER
  extended_updates = []
  for row in unmatched_rows:
    camera_direction = direction_bearing_deg(str(_row_get(row, "direction", "")))
    previous_name = f"{_row_get(row, 'road_name', '')} {_row_get(row, 'place', '')}"
    match = find_current_road(
      osm_roads_db_path,
      float(row["lat"]),
      float(row["lon"]),
      camera_direction,
      extended_radius_m,
      previous_name=previous_name,
    )
    if match is None:
      continue
    if not road_name_matches(previous_name, match.display_name, match.ref):
      continue
    extended_updates.append((
      match.display_name,
      match.ref,
      float(match.distance_m),
      float(match.heading_diff_deg),
      row["id"],
    ))

  updates.extend(extended_updates)
  extended_match_count = len(extended_updates)
  unmatched_count = max(0, len(rows) - len(updates))

  if updates:
    conn.executemany("""
      UPDATE speed_cameras
      SET osm_road_name = ?,
          osm_road_ref = ?,
          osm_road_match_dist_m = ?,
          osm_road_match_heading_deg = ?
      WHERE id = ?
    """, updates)

  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_enriched_count", str(len(updates))))
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_primary_match_count", str(primary_match_count)))
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_extended_match_count", str(extended_match_count)))
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_unmatched_count", str(unmatched_count)))
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_extended_radius_m", f"{extended_radius_m:.1f}"))
  conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("osm_road_db_path", str(osm_roads_db_path)))
  conn.commit()
  return len(updates)


def database_data_date(db_path: Path = DEFAULT_DB_PATH) -> str:
  try:
    if not db_path.exists():
      return ""
  except OSError:
    return ""

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return ""

  with closing(conn):
    try:
      row = conn.execute("SELECT value FROM metadata WHERE key = ?", ("source_updated_at",)).fetchone()
      if row and row[0]:
        return str(row[0])
    except sqlite3.Error:
      pass

    try:
      row = conn.execute("SELECT MAX(updated_at) FROM speed_cameras").fetchone()
      return str(row[0] or "")
    except sqlite3.Error:
      return ""


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
  try:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
  except sqlite3.Error:
    return set()


def database_osm_road_enriched_count(db_path: Path = DEFAULT_DB_PATH) -> int:
  return database_osm_road_enrichment_stats(db_path).matched_count


def database_osm_road_enrichment_stats(db_path: Path = DEFAULT_DB_PATH) -> OsmRoadEnrichmentStats:
  try:
    if not db_path.exists():
      return OsmRoadEnrichmentStats()
  except OSError:
    return OsmRoadEnrichmentStats()

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return OsmRoadEnrichmentStats()

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if not {"osm_road_name", "osm_road_ref"}.issubset(columns):
      return OsmRoadEnrichmentStats()
    metadata = _metadata_map(conn)
    try:
      row = conn.execute("""
        SELECT
          COUNT(*) AS total_count,
          SUM(CASE WHEN COALESCE(osm_road_name, '') != '' OR COALESCE(osm_road_ref, '') != '' THEN 1 ELSE 0 END) AS matched_count
        FROM speed_cameras
      """).fetchone()
      total_count = int(row[0] if row else 0)
      matched_count = int(row[1] if row and row[1] is not None else 0)
    except (sqlite3.Error, TypeError, ValueError):
      return OsmRoadEnrichmentStats()

    unmatched_count = max(0, total_count - matched_count)
    extended_match_count = _metadata_int(metadata, "osm_road_extended_match_count")
    primary_match_count = _metadata_int(metadata, "osm_road_primary_match_count")
    if primary_match_count <= 0 and matched_count > 0:
      primary_match_count = max(0, matched_count - extended_match_count)
    if primary_match_count + extended_match_count != matched_count and matched_count > 0:
      extended_match_count = max(0, min(extended_match_count, matched_count))
      primary_match_count = max(0, matched_count - extended_match_count)
    extended_radius_m = _metadata_float(metadata, "osm_road_extended_radius_m")
    unmatched_by_category: tuple[tuple[str, int], ...] = ()
    if unmatched_count > 0 and "camera_category" in columns:
      try:
        rows = conn.execute("""
          SELECT camera_category, COUNT(*)
          FROM speed_cameras
          WHERE COALESCE(osm_road_name, '') = '' AND COALESCE(osm_road_ref, '') = ''
          GROUP BY camera_category
          ORDER BY COUNT(*) DESC, camera_category
        """).fetchall()
        unmatched_by_category = tuple((str(category or "UNKNOWN"), int(count)) for category, count in rows)
      except (sqlite3.Error, TypeError, ValueError):
        unmatched_by_category = ()

    return OsmRoadEnrichmentStats(
      total_count,
      matched_count,
      unmatched_count,
      primary_match_count,
      extended_match_count,
      extended_radius_m,
      unmatched_by_category,
    )


def _metadata_map(conn: sqlite3.Connection) -> dict[str, str]:
  try:
    rows = conn.execute("SELECT key, value FROM metadata").fetchall()
  except sqlite3.Error:
    return {}
  return {str(key): str(value) for key, value in rows}


def _metadata_int(metadata: dict[str, str], key: str) -> int:
  try:
    return max(0, int(metadata.get(key, "0")))
  except ValueError:
    return 0


def _metadata_float(metadata: dict[str, str], key: str) -> float:
  try:
    return max(0.0, float(metadata.get(key, "0")))
  except ValueError:
    return 0.0


def database_region_counts(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if "is_speed_camera" in columns:
      try:
        rows = conn.execute("""
          SELECT region, COUNT(*)
          FROM speed_cameras
          WHERE is_speed_camera = 1
          GROUP BY region
          ORDER BY COUNT(*) DESC, region
        """).fetchall()
        if rows:
          return [(str(region or "미분류"), int(count)) for region, count in rows]
      except sqlite3.Error:
        pass

    try:
      rows = conn.execute("""
        SELECT region, count
        FROM speed_camera_region_counts
        ORDER BY count DESC, region
      """).fetchall()
      if rows:
        return [(str(region), int(count)) for region, count in rows]
    except sqlite3.Error:
      pass

    try:
      rows = conn.execute("""
        SELECT region, COUNT(*)
        FROM speed_cameras
        GROUP BY region
        ORDER BY COUNT(*) DESC, region
      """).fetchall()
      return [(str(region or "미분류"), int(count)) for region, count in rows]
    except sqlite3.Error:
      return []


def database_region_stats(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int, int, str]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if {"region", "is_speed_camera", "updated_at"}.issubset(columns):
      try:
        rows = conn.execute("""
          SELECT
            region,
            COUNT(*) AS total_count,
            SUM(CASE WHEN is_speed_camera = 1 THEN 1 ELSE 0 END) AS alert_count,
            MAX(updated_at) AS latest_updated_at
          FROM speed_cameras
          GROUP BY region
          ORDER BY alert_count DESC, total_count DESC, region
        """).fetchall()
        return [
          (str(region or "미분류"), int(total_count), int(alert_count or 0), str(latest_updated_at or ""))
          for region, total_count, alert_count, latest_updated_at in rows
        ]
      except sqlite3.Error:
        pass

    return [
      (region, count, count, "")
      for region, count in database_region_counts(db_path)
    ]


def database_category_counts(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if "camera_category" not in columns:
      return []

    try:
      rows = conn.execute("""
        SELECT camera_category, COUNT(*)
        FROM speed_cameras
        GROUP BY camera_category
        ORDER BY
          CASE camera_category
            WHEN 'SPEED' THEN 1
            WHEN 'SECTION_SPEED' THEN 2
            WHEN 'SIGNAL' THEN 3
            WHEN 'SECURITY' THEN 4
            WHEN 'PROTECTED_ZONE' THEN 5
            WHEN 'UNKNOWN' THEN 6
            ELSE 7
          END,
          camera_category
      """).fetchall()
      return [(str(category or "UNKNOWN"), int(count)) for category, count in rows]
    except sqlite3.Error:
      return []


def database_road_class_counts(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int]]:
  try:
    if not db_path.exists():
      return []
  except OSError:
    return []

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return []

  with closing(conn):
    columns = _table_columns(conn, "speed_cameras")
    if "road_class" not in columns:
      return []

    if "is_speed_camera" in columns:
      try:
        rows = conn.execute("""
          SELECT road_class, COUNT(*)
          FROM speed_cameras
          WHERE is_speed_camera = 1
          GROUP BY road_class
          ORDER BY COUNT(*) DESC, road_class
        """).fetchall()
        if rows:
          return [(str(road_class or "UNKNOWN"), int(count)) for road_class, count in rows]
      except sqlite3.Error:
        pass

    try:
      rows = conn.execute("""
        SELECT road_class, COUNT(*)
        FROM speed_cameras
        GROUP BY road_class
        ORDER BY COUNT(*) DESC, road_class
      """).fetchall()
      return [(str(road_class or "UNKNOWN"), int(count)) for road_class, count in rows]
    except sqlite3.Error:
      return []


def _leaflet_camera_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
  columns = _table_columns(conn, "speed_cameras")
  if not {"id", "lat", "lon", "speed_limit"}.issubset(columns):
    return []

  conn.row_factory = sqlite3.Row
  rows = conn.execute("""
    SELECT *
    FROM speed_cameras
    WHERE lat BETWEEN -90.0 AND 90.0
      AND lon BETWEEN -180.0 AND 180.0
    ORDER BY region, id
  """).fetchall()

  cameras = []
  for row in rows:
    camera_type = str(_row_get(row, "camera_type", ""))
    section_type = str(_row_get(row, "section_type", ""))
    road_name = str(_row_get(row, "road_name", ""))
    place = str(_row_get(row, "place", ""))
    speed_limit = int(_row_get(row, "speed_limit", 0))
    category = str(_row_get(row, "camera_category", ""))
    if not category or category == "UNKNOWN":
      category = normalize_camera_category(camera_type, section_type, f"{road_name} {place}", speed_limit)

    road_class = str(_row_get(row, "road_class", ""))
    road_type_raw = str(_row_get(row, "road_type_raw", ""))
    if not road_class or road_class == "UNKNOWN":
      road_class = normalize_road_class(road_type_raw, road_name, place)

    cameras.append({
      "uid": str(_row_get(row, "id", "")),
      "id": str(_row_get(row, "id", "")),
      "lat": float(_row_get(row, "lat", 0.0)),
      "lon": float(_row_get(row, "lon", 0.0)),
      "speed": speed_limit,
      "category": category,
      "roadClass": road_class,
      "roadType": road_type_raw,
      "region": str(_row_get(row, "region", "")),
      "road": road_name,
      "place": place,
      "source": str(_row_get(row, "source_type", "")),
      "updatedAt": str(_row_get(row, "updated_at", "")),
      "debug": {
        "camera_category": category,
        "camera_type_code": int(_row_get(row, "camera_type_code", 0)),
        "is_speed_camera": int(_row_get(row, "is_speed_camera", 0)),
        "is_signal_camera": int(_row_get(row, "is_signal_camera", 0)),
        "is_section_camera": int(_row_get(row, "is_section_camera", 0)),
        "road_class": road_class,
        "road_class_code": int(_row_get(row, "road_class_code", 0)),
        "is_expressway": int(_row_get(row, "is_expressway", 0)),
        "is_national_road": int(_row_get(row, "is_national_road", 0)),
        "dedup_key": str(_row_get(row, "dedup_key", "")),
        "source_type": str(_row_get(row, "source_type", "")),
        "source_file": str(_row_get(row, "source_file", "")),
      },
    })
  return cameras


def _raw_popup_fields(row: dict[str, str]) -> dict[str, str]:
  return {str(key): str(value) for key, value in row.items() if str(value or "").strip()}


def _camera_payload_from_record(record: dict[str, object], row_index: int, row: dict[str, str]) -> dict[str, object]:
  return {
    "uid": f"{record['source_file']}:{row_index}:{record['id']}",
    "id": str(record["id"]),
    "lat": float(record["lat"]),
    "lon": float(record["lon"]),
    "speed": int(record["speed_limit"]),
    "category": str(record["camera_category"]),
    "roadClass": str(record["road_class"]),
    "roadType": str(record["road_type_raw"]),
    "region": str(record["region"]),
    "road": str(record["road_name"]),
    "place": str(record["place"]),
    "source": str(record["source_type"]),
    "sourceFile": str(record["source_file"]),
    "updatedAt": str(record["updated_at"]),
    "rowIndex": row_index,
    "original": _raw_popup_fields(row),
    "debug": {
      "camera_category": str(record["camera_category"]),
      "camera_type_code": int(record["camera_type_code"]),
      "is_speed_camera": int(record["is_speed_camera"]),
      "is_signal_camera": int(record["is_signal_camera"]),
      "is_section_camera": int(record["is_section_camera"]),
      "road_class": str(record["road_class"]),
      "road_class_code": int(record["road_class_code"]),
      "is_expressway": int(record["is_expressway"]),
      "is_national_road": int(record["is_national_road"]),
      "dedup_key": str(record["dedup_key"]),
      "source_type": str(record["source_type"]),
      "source_file": str(record["source_file"]),
      "row_index": row_index,
    },
  }


def _leaflet_camera_rows_from_csvs(csv_sources: list[CsvSource]) -> list[dict[str, object]]:
  cameras = []
  for csv_source in csv_sources:
    rows = _read_csv_rows(csv_source.path)
    for idx, row in enumerate(rows):
      record = _standardize_csv_row(row, csv_source, idx)
      if record is None:
        continue
      cameras.append(_camera_payload_from_record(record, idx, row))
  return cameras


def _leaflet_camera_rows_from_db(db_path: Path) -> list[dict[str, object]] | None:
  if not db_path.exists():
    return None

  try:
    conn = sqlite3.connect(db_path)
  except sqlite3.Error:
    return None

  with closing(conn):
    try:
      return _leaflet_camera_rows(conn)
    except sqlite3.Error:
      return None


def _leaflet_dataset(input_source: str, source_file: str, cameras: list[dict[str, object]]) -> dict[str, object]:
  return {
    "inputSource": input_source,
    "sourceFile": source_file,
    "count": len(cameras),
    "cameras": cameras,
  }


def _leaflet_data_json(payload: dict[str, object]) -> str:
  return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _leaflet_dataset_dir(html_path: Path, data_dir: Path | None) -> Path:
  if data_dir is not None:
    return data_dir
  return html_path.with_name(f"{html_path.stem}_data")


def _leaflet_dataset_file_path(html_path: Path, data_dir: Path, dataset_key: str, suffix: str) -> Path:
  return data_dir / f"{dataset_key}{suffix}"


def _leaflet_html_data_url(html_path: Path, data_path: Path) -> str:
  return Path(os.path.relpath(data_path, html_path.parent)).as_posix()


def export_speed_camera_leaflet_html(
  db_path: Path = DEFAULT_DB_PATH,
  html_path: Path = DEFAULT_MAP_HTML_PATH,
  source_path: Path | None = None,
  csv_sources: list[CsvSource] | None = None,
  active_source: str | None = None,
  data_mode: str = "external",
  data_dir: Path | None = None,
) -> int:
  if data_mode not in ("inline", "external"):
    raise ValueError("data_mode must be 'inline' or 'external'")

  datasets: dict[str, dict[str, object]] = {}

  db_cameras = _leaflet_camera_rows_from_db(db_path)
  if db_cameras is not None:
    db_source_file = Path(source_path).name if source_path is not None else db_path.name
    datasets["db"] = _leaflet_dataset("DB", db_source_file, db_cameras)

  if csv_sources is not None:
    csv_cameras = _leaflet_camera_rows_from_csvs(csv_sources)
    csv_source_file = ", ".join(csv_source.path.name for csv_source in csv_sources)
    datasets["csv"] = _leaflet_dataset("CSV", csv_source_file, csv_cameras)
  else:
    if db_cameras is None:
      return 0

  default_source = "csv" if csv_sources is not None else "db"
  active_dataset = (active_source or default_source).lower()
  if active_dataset not in datasets:
    active_dataset = default_source if default_source in datasets else next(iter(datasets), "")
  if not active_dataset:
    return 0

  active = datasets[active_dataset]
  cameras = active["cameras"]
  category_counts = [
    {"category": category, "count": count}
    for category, count in database_category_counts(db_path)
  ]

  html_path.parent.mkdir(parents=True, exist_ok=True)
  if data_mode == "external":
    html_datasets = {}
    dataset_dir = _leaflet_dataset_dir(html_path, data_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    for key, dataset in datasets.items():
      dataset_payload = {
        "inputSource": dataset["inputSource"],
        "sourceFile": dataset["sourceFile"],
        "count": dataset["count"],
        "categoryCounts": category_counts,
        "cameras": dataset["cameras"],
      }
      json_path = _leaflet_dataset_file_path(html_path, dataset_dir, key, ".json")
      json_path.write_text(_leaflet_data_json(dataset_payload), encoding="utf-8")
      script_path = _leaflet_dataset_file_path(html_path, dataset_dir, key, ".js")
      script_path.write_text(
        "window.__NAVD_CAMERA_DATASETS__=window.__NAVD_CAMERA_DATASETS__||{};"
        f"window.__NAVD_CAMERA_DATASETS__[{json.dumps(key)}]={_leaflet_data_json(dataset_payload)};\n",
        encoding="utf-8",
      )
      html_datasets[key] = {
        "inputSource": dataset["inputSource"],
        "sourceFile": dataset["sourceFile"],
        "count": dataset["count"],
        "url": _leaflet_html_data_url(html_path, json_path),
        "scriptUrl": _leaflet_html_data_url(html_path, script_path),
      }
  else:
    html_datasets = datasets

  payload = {
    "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    "dbPath": str(db_path),
    "dataMode": data_mode,
    "activeDataset": active_dataset,
    "datasets": html_datasets,
    "inputSource": active["inputSource"],
    "sourceFile": active["sourceFile"],
    "count": len(cameras),
    "categoryCounts": category_counts,
  }
  if data_mode == "inline":
    payload["cameras"] = cameras

  html_path.write_text(_leaflet_html_template().replace("__NAVD_CAMERA_DATA__", _leaflet_data_json(payload)), encoding="utf-8")
  return len(cameras)


def _leaflet_html_template() -> str:
  return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>공공 단속카메라 Leaflet/OpenStreetMap 뷰어</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --line: #d8dee7;
      --text: #17202a;
      --muted: #5d6978;
      --strong: #0f172a;
      --accent: #2563eb;
      --popup-width: 2520px;
      --popup-viewport-width: 98vw;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
      min-height: 74px;
      padding: 12px 18px;
      border-bottom: 1px solid var(--line);
      background: #101820;
      color: #f8fafc;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.25;
      font-weight: 760;
    }
    .header-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      margin-top: 6px;
      color: #c8d1dc;
      font-size: 13px;
    }
    .header-stat {
      min-width: 120px;
      text-align: right;
      font-size: 13px;
      color: #c8d1dc;
    }
    .header-stat strong {
      display: block;
      color: #ffffff;
      font-size: 22px;
      line-height: 1.1;
    }
    .app {
      display: grid;
      grid-template-columns: minmax(340px, 420px) 1fr;
      min-height: 0;
    }
    aside {
      min-height: 0;
      overflow: auto;
      padding: 14px;
      border-right: 1px solid var(--line);
      background: #eef2f6;
    }
    #map {
      min-height: 0;
      height: 100%;
      width: 100%;
    }
    section {
      padding: 14px;
      margin-bottom: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }
    section h2 {
      margin: 0 0 10px;
      font-size: 15px;
      line-height: 1.2;
      color: var(--strong);
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .metric {
      min-height: 66px;
      padding: 10px;
      border: 1px solid #e1e7ef;
      border-radius: 8px;
      background: #f8fafc;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
    }
    .metric strong {
      display: block;
      margin-top: 4px;
      color: var(--strong);
      font-size: 22px;
      line-height: 1.1;
    }
    label {
      display: block;
      margin-bottom: 5px;
      color: #334155;
      font-size: 12px;
      font-weight: 650;
    }
    input, select, button {
      width: 100%;
      min-height: 34px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      font: inherit;
      font-size: 13px;
    }
    input, select { padding: 6px 8px; }
    .load-status {
      min-height: 18px;
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }
    .load-status.error {
      color: #b91c1c;
      font-weight: 650;
    }
    .load-status.loading {
      color: #1d4ed8;
      font-weight: 650;
    }
    button {
      cursor: pointer;
      background: #f8fafc;
      font-weight: 680;
    }
    button.primary {
      border-color: #1d4ed8;
      background: var(--accent);
      color: #ffffff;
    }
    .filters {
      display: grid;
      gap: 10px;
    }
    .filter-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .bars {
      display: grid;
      gap: 7px;
    }
    .bar-row {
      display: grid;
      grid-template-columns: minmax(96px, 1fr) 48px;
      gap: 8px;
      align-items: center;
      font-size: 12px;
    }
    .bar-label {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: #334155;
    }
    .category-dot {
      flex: 0 0 auto;
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--category-color, #525252);
      box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.18);
    }
    .bar-track {
      grid-column: 1 / -1;
      height: 7px;
      border-radius: 999px;
      background: #e5e7eb;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      min-width: 2px;
      border-radius: inherit;
      background: var(--bar-color, var(--accent));
    }
    .category-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      max-width: 100%;
      color: #0f172a;
      font-weight: 680;
    }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      padding: 8px 7px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      vertical-align: top;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: #475569;
      font-size: 11px;
    }
    tbody tr {
      cursor: pointer;
    }
    tbody tr:hover {
      background: #eff6ff;
    }
	    .table-note {
	      margin: 8px 0 0;
	      color: var(--muted);
	      font-size: 12px;
	    }
	    .leaflet-popup-content {
	      width: min(var(--popup-width), var(--popup-viewport-width));
	      max-width: var(--popup-width);
	    }
	    .popup-grid {
	      display: grid;
	      grid-template-columns: repeat(2, minmax(0, 1fr));
	      gap: 12px;
	      margin-top: 8px;
	    }
	    .popup-section {
	      min-width: 0;
	      max-height: 520px;
	      overflow: auto;
	      padding: 10px;
	      border: 1px solid #e5e7eb;
	      border-radius: 8px;
	      background: #f8fafc;
	    }
	    .popup-title {
	      position: sticky;
	      top: 0;
	      z-index: 1;
	      margin: -10px -10px 8px;
	      padding: 8px 10px;
	      border-bottom: 1px solid #e5e7eb;
	      background: #f8fafc;
	      color: #0f172a;
	      font-weight: 760;
	    }
	    .popup-row {
	      display: block;
	      padding: 6px 0;
	      border-bottom: 1px solid #e5e7eb;
	      font-size: 12px;
	    }
	    .popup-row:last-child {
	      border-bottom: 0;
	    }
	    .popup-key {
	      display: block;
	      margin-bottom: 2px;
	      color: #64748b;
	      font-size: 11px;
	      font-weight: 720;
	    }
	    .popup-value {
	      display: block;
	      color: #0f172a;
	      line-height: 1.35;
	      word-break: break-word;
	      overflow-wrap: anywhere;
	    }
	    .speed-limit-label {
	      border: 0;
	      background: transparent;
	      box-shadow: none;
	      color: #ffffff;
	      font-size: 10px;
	      font-weight: 800;
	      line-height: 1;
	      text-align: center;
	      text-shadow: 0 1px 2px rgba(15, 23, 42, 0.9);
	      pointer-events: none;
	    }
	    .speed-limit-label::before {
	      display: none;
	    }
	    @media (max-width: 900px) {
	      .leaflet-popup-content { width: min(520px, 88vw); }
	      .popup-grid { grid-template-columns: 1fr; }
	    }
    @media (max-width: 900px) {
      body { grid-template-rows: auto auto 60vh; }
      header { grid-template-columns: 1fr; }
      .header-stat { text-align: left; }
      .app { grid-template-columns: 1fr; grid-template-rows: auto 60vh; }
      aside { max-height: 48vh; border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>공공 단속카메라 Leaflet/OpenStreetMap 뷰어</h1>
      <div class="header-meta">
        <span>입력 데이터: <strong id="input-source">-</strong> <strong id="source-file">-</strong></span>
        <span>Google API Key 불필요</span>
        <span id="db-path"></span>
      </div>
    </div>
    <div class="header-stat">
      전체 카메라 건수
      <strong id="header-count">0</strong>
    </div>
  </header>
  <main class="app">
    <aside>
      <section>
        <h2>요약</h2>
        <div class="summary-grid">
          <div class="metric"><span>전체 카메라 수</span><strong id="metric-total">0</strong></div>
          <div class="metric"><span>과속 관련 카메라 수</span><strong id="metric-speed">0</strong></div>
          <div class="metric"><span>카테고리 수</span><strong id="metric-category">0</strong></div>
          <div class="metric"><span>지역 수</span><strong id="metric-region">0</strong></div>
        </div>
      </section>
      <section>
        <h2>필터</h2>
        <div class="filters">
          <div>
            <label for="dataset-source">입력 데이터</label>
            <select id="dataset-source"></select>
            <div id="dataset-load-status" class="load-status" aria-live="polite"></div>
          </div>
          <div>
            <label for="search">검색어</label>
            <input id="search" type="search" placeholder="지역 / 설치장소 / 도로명 / 주소 / 관리번호">
          </div>
          <div class="filter-row">
            <div>
              <label for="category-filter">카메라 카테고리</label>
              <select id="category-filter"></select>
            </div>
            <div>
              <label for="road-filter">도로종류</label>
              <select id="road-filter"></select>
            </div>
          </div>
          <div class="filter-row">
            <div>
              <label for="region-filter">시도</label>
              <select id="region-filter"></select>
            </div>
            <div>
              <label for="speed-filter">제한속도</label>
              <select id="speed-filter"></select>
            </div>
          </div>
          <div class="filter-row">
            <button id="fit-all" class="primary" type="button">지도 전체 보기</button>
            <button id="reset-filters" type="button">필터 초기화</button>
          </div>
        </div>
      </section>
      <section>
        <h2>카테고리 요약</h2>
        <div id="category-bars" class="bars"></div>
      </section>
      <section>
        <h2>도로종류 요약</h2>
        <div id="road-bars" class="bars"></div>
      </section>
      <section>
        <h2>카메라 목록</h2>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>카테고리</th>
                <th>제한속도</th>
                <th>지역 / 설치장소</th>
              </tr>
            </thead>
            <tbody id="camera-table"></tbody>
          </table>
        </div>
        <p id="table-note" class="table-note"></p>
      </section>
    </aside>
    <div id="map"></div>
  </main>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <script>
    const payload = __NAVD_CAMERA_DATA__;
    const datasets = payload.datasets || {
      [(payload.inputSource || "DB").toLowerCase()]: {
        inputSource: payload.inputSource || "DB",
        sourceFile: payload.sourceFile || "",
        count: payload.count || 0,
        cameras: payload.cameras || [],
      },
    };
    let activeDatasetKey = payload.activeDataset || (payload.inputSource || "db").toLowerCase();
    let activeDataset = datasets[activeDatasetKey] || Object.values(datasets)[0] || {};
    let cameras = Array.isArray(activeDataset.cameras) ? activeDataset.cameras : [];
    let dbCategoryCounts = normalizeCategoryCounts(payload.categoryCounts || []);
    const datasetCache = new Map();
    const colors = {
      SPEED: "#d73027",
      SPEED_SIGNAL: "#f59e0b",
      SECTION_SPEED: "#7c3aed",
      SIGNAL: "#2563eb",
      SECURITY: "#0891b2",
      PROTECTED_ZONE: "#16a34a",
      PARKING: "#64748b",
      BUS_LANE: "#0f766e",
      TRAFFIC: "#ea580c",
      ETC: "#737373",
      UNKNOWN: "#404040",
    };
    const speedCategories = new Set(["SPEED", "SPEED_SIGNAL", "SECTION_SPEED"]);
    const maxListRows = 500;

    const map = L.map("map", { preferCanvas: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    const cluster = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 48,
      disableClusteringAtZoom: 18,
    }).addTo(map);
    const markerById = new Map();

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[ch]));
    }

    function formatNumber(value) {
      return Number(value || 0).toLocaleString();
    }

    function cameraRoadType(camera) {
      return camera.roadType || camera.roadClass || "UNKNOWN";
    }

    function optionValue(value) {
      return String(value || "UNKNOWN");
    }

    function uniqueValues(items, getter) {
      return Array.from(new Set(items.map(getter).filter(Boolean))).sort((a, b) => String(a).localeCompare(String(b)));
    }

	    function normalizeCategoryCounts(rows) {
	      return (rows || [])
	        .map((row) => [String(row.category || "UNKNOWN"), Number(row.count || 0)])
	        .filter(([, count]) => count > 0);
	    }

	    function datasetName(key, dataset) {
	      if (key === "csv") return "CSV 원본";
	      if (key === "db") return "DB 저장 결과";
	      return dataset.inputSource || key.toUpperCase();
	    }

	    function datasetEntries() {
	      return Object.entries(datasets).filter(([, dataset]) => Array.isArray(dataset.cameras) || dataset.url || dataset.scriptUrl);
	    }

	    function fillDatasetSelect() {
	      const select = document.getElementById("dataset-source");
	      select.innerHTML = datasetEntries().map(([key, dataset]) => {
	        const count = dataset.count ?? (dataset.cameras || []).length;
	        return `<option value="${escapeHtml(key)}">${escapeHtml(datasetName(key, dataset))} (${formatNumber(count)}건)</option>`;
	      }).join("");
	      select.value = datasets[activeDatasetKey] ? activeDatasetKey : (datasetEntries()[0]?.[0] || "");
	    }

	    function showLoadStatus(message, isError = false, updateTableNote = true) {
	      const note = document.getElementById("table-note");
	      const datasetStatus = document.getElementById("dataset-load-status");
	      if (note && updateTableNote) {
	        note.textContent = message || "";
	        note.style.color = isError ? "#b91c1c" : "";
	      }
	      if (datasetStatus) {
	        datasetStatus.textContent = message || "";
	        datasetStatus.classList.toggle("error", Boolean(isError));
	        datasetStatus.classList.toggle("loading", Boolean(message && !isError));
	      }
	    }

	    async function loadDataset(key) {
	      const meta = datasets[key];
	      if (!meta) throw new Error(`unknown dataset: ${key}`);
	      if (Array.isArray(meta.cameras)) return meta;
	      if (datasetCache.has(key)) return datasetCache.get(key);
	      if (!meta.url && !meta.scriptUrl) throw new Error(`missing dataset url: ${key}`);

	      if (meta.url) {
	        try {
	          const response = await fetch(meta.url);
	          if (!response.ok) {
	            throw new Error(`failed to load ${meta.url}: ${response.status}`);
	          }
	          const data = await response.json();
	          const dataset = { ...meta, ...data };
	          datasetCache.set(key, dataset);
	          return dataset;
	        } catch (error) {
	          if (!meta.scriptUrl) throw error;
	        }
	      }

	      const data = await loadDatasetScript(key, meta.scriptUrl);
	      const dataset = { ...meta, ...data };
	      datasetCache.set(key, dataset);
	      return dataset;
	    }

	    function loadDatasetScript(key, scriptUrl) {
	      return new Promise((resolve, reject) => {
	        window.__NAVD_CAMERA_DATASETS__ = window.__NAVD_CAMERA_DATASETS__ || {};
	        if (window.__NAVD_CAMERA_DATASETS__[key]) {
	          resolve(window.__NAVD_CAMERA_DATASETS__[key]);
	          return;
	        }
	        const script = document.createElement("script");
	        script.src = scriptUrl;
	        script.async = true;
	        script.onload = () => {
	          const data = window.__NAVD_CAMERA_DATASETS__ && window.__NAVD_CAMERA_DATASETS__[key];
	          if (data) {
	            resolve(data);
	          } else {
	            reject(new Error(`loaded ${scriptUrl} but dataset ${key} was not registered`));
	          }
	        };
	        script.onerror = () => reject(new Error(`failed to load ${scriptUrl}`));
	        document.head.appendChild(script);
	      });
	    }

	    function fillSelect(id, values, allLabel) {
	      const select = document.getElementById(id);
	      select.innerHTML = [`<option value="">${escapeHtml(allLabel)}</option>`]
	        .concat(values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`))
	        .join("");
	    }

	    function fillCategorySelect(id, values, allLabel) {
	      const select = document.getElementById(id);
	      select.innerHTML = [`<option value="">${escapeHtml(allLabel)}</option>`]
	        .concat(values.map((value) => {
	          const category = optionValue(value);
	          return `<option value="${escapeHtml(category)}" style="color:${categoryColor(category)}">${escapeHtml(category)}</option>`;
	        }))
	        .join("");
	    }

	    function categoryColor(category) {
	      return colors[optionValue(category)] || colors.UNKNOWN;
	    }

	    function categoryDot(category) {
	      return `<span class="category-dot" style="--category-color:${categoryColor(category)}"></span>`;
	    }

	    function categoryChip(category) {
	      const label = optionValue(category);
	      return `<span class="category-chip">${categoryDot(label)}<span>${escapeHtml(label)}</span></span>`;
	    }
	
	    function objectRows(obj) {
	      return Object.entries(obj || {})
	        .filter(([, value]) => value !== undefined && value !== null && String(value) !== "")
	        .map(([key, value]) => `
	          <div class="popup-row">
	            <span class="popup-key">${escapeHtml(key)}</span>
	            <span class="popup-value">${escapeHtml(value)}</span>
	          </div>
	        `)
	        .join("");
	    }
	
	    function markerStyle(category) {
	      const color = categoryColor(category);
	      return {
	        radius: category === "SECTION_SPEED" ? 13 : 12,
	        color,
	        fillColor: color,
	        fillOpacity: 0.82,
	        opacity: 0.95,
	        weight: 1.5,
	      };
	    }

	    function speedLimitLabel(camera) {
	      const speed = Number(camera.speed || 0);
	      return speed > 0 ? String(speed) : "";
	    }
	
	    function makePopup(camera) {
	      const title = [camera.category, camera.speed ? `${camera.speed} km/h` : "", camera.road || camera.place].filter(Boolean).join(" · ");
	      const originalRows = objectRows(camera.original);
	      const debugRows = objectRows(camera.debug);
	      return `
	        <strong>${escapeHtml(title || camera.id)}</strong><br>
	        <div class="popup-grid">
	          <div class="popup-section">
	            <div class="popup-title">원본 데이터</div>
	            ${originalRows || objectRows({
	              관리번호: camera.id,
	              위도: camera.lat,
	              경도: camera.lon,
	              제한속도: camera.speed,
	              도로종류: cameraRoadType(camera),
	              시도: camera.region,
	              도로노선명: camera.road,
	              설치장소: camera.place,
	            })}
	          </div>
	          <div class="popup-section">
	            <div class="popup-title">Speed camera debug</div>
	            ${debugRows}
	          </div>
	        </div>
	      `;
	    }

    function buildMarkers(items) {
      cluster.clearLayers();
      markerById.clear();
	      const layers = [];
	      for (const camera of items) {
	        const category = camera.category || "UNKNOWN";
	        const marker = L.circleMarker([camera.lat, camera.lon], markerStyle(category));
	        const speedLabel = speedLimitLabel(camera);
	        if (speedLabel) {
	          marker.bindTooltip(speedLabel, {
	            permanent: true,
	            direction: "center",
	            className: "speed-limit-label",
	            opacity: 1,
	          });
	        }
	        marker.bindPopup(makePopup(camera));
	        markerById.set(camera.uid || camera.id, marker);
        layers.push(marker);
      }
      cluster.addLayers(layers);
    }

    function filteredCameras() {
      const search = document.getElementById("search").value.trim().toLowerCase();
      const category = document.getElementById("category-filter").value;
      const roadType = document.getElementById("road-filter").value;
      const region = document.getElementById("region-filter").value;
      const speed = document.getElementById("speed-filter").value;
      return cameras.filter((camera) => {
        if (category && camera.category !== category) return false;
        if (roadType && cameraRoadType(camera) !== roadType) return false;
        if (region && optionValue(camera.region) !== region) return false;
        if (speed && String(camera.speed || 0) !== speed) return false;
        if (!search) return true;
        const haystack = [
          camera.region,
          camera.place,
          camera.road,
          camera.roadType,
          camera.roadClass,
          camera.id,
        ].join(" ").toLowerCase();
        return haystack.includes(search);
      });
    }

    function countBy(items, getter) {
      const counts = new Map();
      for (const item of items) {
        const key = optionValue(getter(item));
        counts.set(key, (counts.get(key) || 0) + 1);
      }
      return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    }

    function renderBars(id, counts, colorGetter = null) {
      const max = Math.max(1, ...counts.map(([, count]) => count));
      document.getElementById(id).innerHTML = counts.map(([label, count]) => `
        <div class="bar-row">
          <div class="bar-label" title="${escapeHtml(label)}">
            ${colorGetter ? categoryDot(label) : ""}
            <span>${escapeHtml(label)}</span>
          </div>
          <strong>${formatNumber(count)}</strong>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, (count / max) * 100)}%;--bar-color:${colorGetter ? colorGetter(label) : "var(--accent)"}"></div></div>
        </div>
      `).join("");
    }

    function renderTable(items) {
      const rows = items.slice(0, maxListRows);
      document.getElementById("camera-table").innerHTML = rows.map((camera) => `
        <tr data-uid="${escapeHtml(camera.uid || camera.id)}">
          <td>${categoryChip(camera.category)}</td>
          <td>${escapeHtml(camera.speed || "-")}</td>
          <td><strong>${escapeHtml(camera.region || "-")}</strong><br>${escapeHtml(camera.place || camera.road || "-")}</td>
        </tr>
      `).join("");
      document.getElementById("table-note").textContent = `${formatNumber(items.length)}건 중 최대 ${formatNumber(Math.min(items.length, maxListRows))}건 표시`;
      for (const row of document.querySelectorAll("#camera-table tr")) {
        row.addEventListener("click", () => {
          const marker = markerById.get(row.dataset.uid);
          if (!marker) return;
          cluster.zoomToShowLayer(marker, () => {
            map.setView(marker.getLatLng(), Math.max(map.getZoom(), 16));
            marker.openPopup();
          });
        });
      }
    }

    function updateSummary(items) {
      document.getElementById("metric-total").textContent = formatNumber(items.length);
      document.getElementById("metric-speed").textContent = formatNumber(items.filter((camera) => speedCategories.has(camera.category)).length);
      document.getElementById("metric-category").textContent = formatNumber(
        dbCategoryCounts.length || new Set(items.map((camera) => optionValue(camera.category))).size
      );
      document.getElementById("metric-region").textContent = formatNumber(new Set(items.map((camera) => optionValue(camera.region))).size);
    }

    function fitMarkers(items) {
      if (items.length > 0) {
        const bounds = L.latLngBounds(items.map((camera) => [camera.lat, camera.lon]));
        map.fitBounds(bounds.pad(0.08));
      } else {
        map.setView([36.5, 127.8], 7);
      }
    }

    let updateTimer = 0;
    function render(fit = false) {
      const items = filteredCameras();
      updateSummary(items);
      renderBars("category-bars", dbCategoryCounts.length ? dbCategoryCounts : countBy(items, (camera) => camera.category), categoryColor);
      renderBars("road-bars", countBy(items, cameraRoadType));
      buildMarkers(items);
      renderTable(items);
      if (fit) fitMarkers(items);
    }

    function scheduleRender() {
      clearTimeout(updateTimer);
      updateTimer = setTimeout(() => render(true), 180);
    }

    function updateHeader() {
      document.getElementById("input-source").textContent = activeDataset.inputSource || activeDatasetKey.toUpperCase() || "-";
      document.getElementById("source-file").textContent = activeDataset.sourceFile || "-";
      document.getElementById("header-count").textContent = formatNumber(activeDataset.count ?? cameras.length);
      document.getElementById("db-path").textContent = payload.dbPath || "";
    }

    function refreshFilterOptions() {
      fillCategorySelect(
        "category-filter",
        dbCategoryCounts.length ? dbCategoryCounts.map(([category]) => category) : uniqueValues(cameras, (camera) => camera.category || "UNKNOWN"),
        "전체 카테고리"
      );
      fillSelect("road-filter", uniqueValues(cameras, cameraRoadType), "전체 도로종류");
      fillSelect("region-filter", uniqueValues(cameras, (camera) => optionValue(camera.region)), "전체 시도");
      fillSelect("speed-filter", uniqueValues(cameras, (camera) => String(camera.speed || 0)), "전체 제한속도");
    }

    function clearFilters() {
      document.getElementById("search").value = "";
      document.getElementById("category-filter").value = "";
      document.getElementById("road-filter").value = "";
      document.getElementById("region-filter").value = "";
      document.getElementById("speed-filter").value = "";
    }

    async function setActiveDataset(key, fit = true) {
      activeDatasetKey = datasets[key] ? key : (datasetEntries()[0]?.[0] || "db");
      activeDataset = datasets[activeDatasetKey] || {};
      cameras = Array.isArray(activeDataset.cameras) ? activeDataset.cameras : [];
      dbCategoryCounts = normalizeCategoryCounts(activeDataset.categoryCounts || payload.categoryCounts || []);
      document.getElementById("dataset-source").value = activeDatasetKey;
      clearFilters();
      updateHeader();
      refreshFilterOptions();
      showLoadStatus(`${datasetName(activeDatasetKey, datasets[activeDatasetKey] || {})} 데이터 로딩 중...`);
      try {
        activeDataset = await loadDataset(activeDatasetKey);
        cameras = activeDataset.cameras || [];
        dbCategoryCounts = normalizeCategoryCounts(activeDataset.categoryCounts || payload.categoryCounts || []);
        updateHeader();
        refreshFilterOptions();
        render(fit);
        showLoadStatus(`${datasetName(activeDatasetKey, activeDataset)} 데이터 로드 완료 (${formatNumber(cameras.length)}건)`, false, false);
      } catch (error) {
        cameras = [];
        cluster.clearLayers();
        markerById.clear();
        updateHeader();
        showLoadStatus(`데이터 파일을 불러오지 못했습니다: ${error.message}. 로컬 서버로 HTML을 열어주세요.`, true);
      }
    }

    fillDatasetSelect();
    setActiveDataset(activeDatasetKey, true);

    document.getElementById("dataset-source").addEventListener("change", (event) => {
      setActiveDataset(event.target.value, false);
    });

    for (const id of ["search", "category-filter", "road-filter", "region-filter", "speed-filter"]) {
      document.getElementById(id).addEventListener("input", scheduleRender);
      document.getElementById(id).addEventListener("change", scheduleRender);
    }
    document.getElementById("fit-all").addEventListener("click", () => fitMarkers(filteredCameras()));
    document.getElementById("reset-filters").addEventListener("click", () => {
      clearFilters();
      render(true);
    });
  </script>
</body>
</html>
"""


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
  tmp_dir: Path | None = None,
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
  effective_tmp_dir = tmp_dir or csv_path.parent
  tmp_path = effective_tmp_dir / f"{csv_path.name}.tmp"
  tmp_path.parent.mkdir(parents=True, exist_ok=True)
  written = 0
  if progress_callback is not None:
    progress_callback(written, total_count)

  try:
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
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
    os.replace(tmp_path, csv_path)
  except Exception:
    try:
      tmp_path.unlink()
    except OSError:
      pass
    raise

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


def relative_angle_deg(bearing: float, heading: float) -> float:
  return (bearing - heading + 180.0) % 360.0 - 180.0


def relative_projection_m(distance_m: float, relative_angle: float) -> tuple[float, float]:
  angle_rad = math.radians(relative_angle)
  return distance_m * math.cos(angle_rad), distance_m * math.sin(angle_rad)


def update_camera_position(camera: SpeedCamera, lat: float, lon: float, heading_deg: float) -> SpeedCamera:
  distance = haversine_distance_m(lat, lon, camera.lat, camera.lon)
  bearing = bearing_deg(lat, lon, camera.lat, camera.lon)
  relative_angle = relative_angle_deg(bearing, heading_deg)
  forward_m, side_m = relative_projection_m(distance, relative_angle)
  return replace(
    camera,
    distance_m=distance,
    forward_m=forward_m,
    side_m=side_m,
    bearing_deg=bearing,
    angle_diff_deg=abs(relative_angle),
    relative_angle_deg=relative_angle,
  )


def direction_kind(direction: str) -> str:
  normalized = direction.strip().upper()
  if normalized in ("3", "03", "양방향", "BOTH", "BIDIRECTIONAL"):
    return "BOTH"
  if normalized in ("1", "01"):
    return "UP"
  if normalized in ("2", "02"):
    return "DOWN"
  return ""


def direction_bearing_deg(direction: str) -> float | None:
  normalized = direction.strip().upper()
  if not normalized:
    return None
  if direction_kind(normalized):
    return None

  exact_directions = {
    "N": 0.0,
    "NB": 0.0,
    "E": 90.0,
    "EB": 90.0,
    "S": 180.0,
    "SB": 180.0,
    "W": 270.0,
    "WB": 270.0,
  }
  if normalized in exact_directions:
    return exact_directions[normalized]

  directions = [
    (("북", "NORTH"), 0.0),
    (("동", "EAST"), 90.0),
    (("남", "SOUTH"), 180.0),
    (("서", "WEST"), 270.0),
  ]
  matches = [bearing for names, bearing in directions if any(name in normalized for name in names)]
  if len(matches) == 1:
    return matches[0]
  return None


def route_hint_from_text(text: str) -> str:
  compact = re.sub(r"\s+", " ", text or "").strip()
  if not compact:
    return ""

  match = re.search(r"([^()]{1,32}?)\s*(?:→|->|⇒|➜)\s*([^()]{1,32})", compact)
  if match is None:
    return ""

  start = match.group(1).strip(" ,()[]")
  end = match.group(2).strip(" ,()[]")
  if not start or not end:
    return ""
  return f"{start}->{end}"


def _bounding_box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
  lat_delta = math.degrees(radius_m / EARTH_RADIUS_M)
  lon_radius = max(math.cos(math.radians(lat)), 0.01)
  lon_delta = math.degrees(radius_m / (EARTH_RADIUS_M * lon_radius))
  return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _row_get(row: sqlite3.Row, column: str, default):
  if column in row.keys():
    value = row[column]
    if value is not None:
      return value
  return default


def _row_to_camera(
  row: sqlite3.Row,
  distance_m: float,
  forward_m: float,
  side_m: float,
  bearing: float,
  angle_diff: float,
  relative_angle: float,
) -> SpeedCamera:
  camera_type = str(_row_get(row, "camera_type", ""))
  section_type = str(_row_get(row, "section_type", ""))
  road_name = str(_row_get(row, "road_name", ""))
  place = str(_row_get(row, "place", ""))

  category = str(_row_get(row, "camera_category", ""))
  speed_limit = int(row["speed_limit"])

  if not category or category == "UNKNOWN":
    category = normalize_camera_category(camera_type, section_type, f"{road_name} {place}", speed_limit)

  type_code = int(_row_get(row, "camera_type_code", 0))
  if type_code == 0:
    type_code = camera_type_code(camera_type, section_type, f"{road_name} {place}", speed_limit)

  road_type_raw = str(_row_get(row, "road_type_raw", ""))
  road_class = str(_row_get(row, "road_class", ""))
  if not road_class or road_class == "UNKNOWN":
    road_class = normalize_road_class(road_type_raw, road_name, place)

  road_code = int(_row_get(row, "road_class_code", 0))
  if road_code == 0:
    road_code = road_class_code(road_class)

  is_expressway = bool(int(_row_get(row, "is_expressway", int(is_expressway_class(road_class)))))
  is_national_road = bool(int(_row_get(row, "is_national_road", int(is_national_road_class(road_class)))))

  return SpeedCamera(
    id=str(row["id"]),
    lat=float(row["lat"]),
    lon=float(row["lon"]),
    camera_type=camera_type,
    speed_limit=speed_limit,
    road_name=road_name,
    place=place,
    direction=str(_row_get(row, "direction", "")),
    section_type=section_type,
    section_length_m=int(_row_get(row, "section_length_m", 0)),
    distance_m=distance_m,
    forward_m=forward_m,
    side_m=side_m,
    bearing_deg=bearing,
    angle_diff_deg=angle_diff,
    relative_angle_deg=relative_angle,
    camera_category=category,
    camera_type_code=type_code,
    region=str(_row_get(row, "region", "")),
    road_type_raw=road_type_raw,
    road_class=road_class,
    road_class_code=road_code,
    is_expressway=is_expressway,
    is_national_road=is_national_road,
    source_type=str(_row_get(row, "source_type", "")),
    source_file=str(_row_get(row, "source_file", "")),
    osm_road_name=str(_row_get(row, "osm_road_name", "")),
    osm_road_ref=str(_row_get(row, "osm_road_ref", "")),
    osm_road_match_dist_m=float(_row_get(row, "osm_road_match_dist_m", 0.0)),
    osm_road_match_heading_deg=float(_row_get(row, "osm_road_match_heading_deg", 0.0)),
    direction_kind=direction_kind(str(_row_get(row, "direction", ""))),
    route_hint=route_hint_from_text(f"{road_name} {place}"),
  )


def _database_version(conn: sqlite3.Connection) -> int:
  try:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", ("version",)).fetchone()
    return int(row[0]) if row and row[0] else 0
  except (sqlite3.Error, TypeError, ValueError):
    return 0


def _candidate_rows(
  conn: sqlite3.Connection,
  lat_min: float,
  lat_max: float,
  lon_min: float,
  lon_max: float,
) -> list[sqlite3.Row]:
  columns = _table_columns(conn, "speed_cameras")
  version = _database_version(conn)
  if {"is_speed_camera", "is_signal_camera", "camera_category"}.issubset(columns):
    rows = conn.execute("""
      SELECT * FROM speed_cameras
      WHERE lat BETWEEN ? AND ?
        AND lon BETWEEN ? AND ?
        AND (
          is_speed_camera = 1 OR
          is_signal_camera = 1 OR
          camera_category IN ('SECURITY', 'PROTECTED_ZONE')
        )
    """, (lat_min, lat_max, lon_min, lon_max)).fetchall()
    if rows or version >= DB_VERSION:
      return rows

  if "is_speed_camera" in columns:
    rows = conn.execute("""
      SELECT * FROM speed_cameras
      WHERE lat BETWEEN ? AND ?
        AND lon BETWEEN ? AND ?
        AND is_speed_camera = 1
    """, (lat_min, lat_max, lon_min, lon_max)).fetchall()
    if rows or version >= DB_VERSION:
      return rows

  return conn.execute("""
    SELECT * FROM speed_cameras
    WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
  """, (lat_min, lat_max, lon_min, lon_max)).fetchall()


def _max_side_distance_m(camera: SpeedCamera) -> float:
  if camera.local_road_match:
    return LOOKAHEAD_LOCAL_ROAD_SIDE_DISTANCE_M
  if camera.is_expressway:
    return LOOKAHEAD_EXPRESSWAY_SIDE_DISTANCE_M
  return LOOKAHEAD_SIDE_DISTANCE_M


def find_lead_cameras(
  db_path: Path,
  lat: float,
  lon: float,
  heading_deg: float,
  max_distance_m: float = LOOKAHEAD_DISTANCE_M,
  max_angle_deg: float = LOOKAHEAD_ANGLE_DEG,
  camera_direction_angle_deg: float = CAMERA_DIRECTION_ANGLE_DEG,
  ignored_ids: set[str] | None = None,
  limit: int = 3,
  current_road_name: str = "",
) -> list[SpeedCamera]:
  if not db_path.exists():
    return []

  ignored_ids = ignored_ids or set()
  lat_min, lat_max, lon_min, lon_max = _bounding_box(lat, lon, max_distance_m)

  with closing(sqlite3.connect(db_path)) as conn:
    conn.row_factory = sqlite3.Row
    rows = _candidate_rows(conn, lat_min, lat_max, lon_min, lon_max)

  candidates: list[SpeedCamera] = []
  for row in rows:
    if row["id"] in ignored_ids:
      continue

    distance = haversine_distance_m(lat, lon, row["lat"], row["lon"])
    if distance > max_distance_m:
      continue

    cam_bearing = bearing_deg(lat, lon, row["lat"], row["lon"])
    relative_angle = relative_angle_deg(cam_bearing, heading_deg)
    diff = abs(relative_angle)
    if diff > max_angle_deg:
      continue
    forward_m, side_m = relative_projection_m(distance, relative_angle)
    if forward_m <= 0.0:
      continue

    camera_direction = direction_bearing_deg(row["direction"])
    if camera_direction is not None and angle_diff_deg(camera_direction, heading_deg) > camera_direction_angle_deg:
      continue

    camera = _row_to_camera(row, distance, forward_m, side_m, cam_bearing, diff, relative_angle)
    if current_road_name:
      camera_road_names = (
        (camera.osm_road_name, camera.osm_road_ref)
        if (camera.osm_road_name or camera.osm_road_ref)
        else (camera.road_name, camera.place)
      )
      camera = replace(
        camera,
        local_road_match=road_name_matches(current_road_name, *camera_road_names),
      )
    camera = replace(camera, forward_road_match=forward_road_likely(camera))
    if abs(camera.side_m) > _max_side_distance_m(camera):
      continue
    if _is_alertable_category(camera.camera_category):
      candidates.append(camera)

  return sorted(candidates, key=_alert_priority)[:max(0, limit)]


def find_lead_camera(
  db_path: Path,
  lat: float,
  lon: float,
  heading_deg: float,
  max_distance_m: float = LOOKAHEAD_DISTANCE_M,
  max_angle_deg: float = LOOKAHEAD_ANGLE_DEG,
  camera_direction_angle_deg: float = CAMERA_DIRECTION_ANGLE_DEG,
  ignored_ids: set[str] | None = None,
  current_road_name: str = "",
) -> SpeedCamera | None:
  cameras = find_lead_cameras(
    db_path,
    lat,
    lon,
    heading_deg,
    max_distance_m,
    max_angle_deg,
    camera_direction_angle_deg,
    ignored_ids,
    limit=1,
    current_road_name=current_road_name,
  )
  return cameras[0] if cameras else None
