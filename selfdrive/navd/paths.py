#!/usr/bin/env python3
import os
from pathlib import Path

try:
  from openpilot.system.hardware import PC
except ModuleNotFoundError:
  try:
    from system.hardware import PC
  except ModuleNotFoundError:
    PC = os.name == "nt" or not Path("/data").is_dir()


REPO_NAVD_DATA_DIR = Path(__file__).resolve().parent / "data"
PC_NAVD_ROOT = Path.home() / f".comma{os.environ.get('OPENPILOT_PREFIX', '')}" / "navd"
DEVICE_NAVD_ROOT = Path("/data/navd")


def _env_path(name: str) -> Path | None:
  value = os.getenv(name)
  return Path(value) if value else None


def navd_root() -> Path:
  return _env_path("NAVD_ROOT") or (PC_NAVD_ROOT if PC else DEVICE_NAVD_ROOT)


def navd_db_dir() -> Path:
  return _env_path("NAVD_DB_ROOT") or navd_root() / "db"


def navd_source_dir() -> Path:
  return _env_path("NAVD_SOURCE_ROOT") or navd_root() / "source"


def navd_tmp_dir() -> Path:
  return _env_path("NAVD_TMP_ROOT") or navd_root() / "tmp"


def ensure_navd_dirs(
  db_dir: Path | None = None,
  source_dir: Path | None = None,
  tmp_dir: Path | None = None,
  region_dir: Path | None = None,
) -> None:
  db_path = Path(db_dir) if db_dir is not None else navd_db_dir()
  source_path = Path(source_dir) if source_dir is not None else navd_source_dir()
  tmp_path = Path(tmp_dir) if tmp_dir is not None else navd_tmp_dir()
  region_path = Path(region_dir) if region_dir is not None else source_path / "region"

  for path in (db_path, source_path, region_path, tmp_path):
    path.mkdir(parents=True, exist_ok=True)


DEFAULT_NAVD_ROOT = navd_root()
DEFAULT_NAVD_DB_DIR = navd_db_dir()
DEFAULT_NAVD_SOURCE_DIR = navd_source_dir()
DEFAULT_NAVD_TMP_DIR = navd_tmp_dir()
