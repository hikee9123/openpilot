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


DEFAULT_NAVD_ROOT = navd_root()
DEFAULT_NAVD_DB_DIR = navd_db_dir()
DEFAULT_NAVD_SOURCE_DIR = navd_source_dir()
DEFAULT_NAVD_TMP_DIR = navd_tmp_dir()
