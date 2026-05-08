import importlib
import os
from pathlib import Path

import selfdrive.navd.paths as navd_paths


def test_navd_root_env_splits_data_dirs(tmp_path, monkeypatch) -> None:
  monkeypatch.setenv("NAVD_ROOT", str(tmp_path / "navd"))

  paths = importlib.reload(navd_paths)
  try:
    assert paths.DEFAULT_NAVD_DB_DIR == tmp_path / "navd" / "db"
    assert paths.DEFAULT_NAVD_SOURCE_DIR == tmp_path / "navd" / "source"
    assert paths.DEFAULT_NAVD_TMP_DIR == tmp_path / "navd" / "tmp"
  finally:
    monkeypatch.delenv("NAVD_ROOT", raising=False)
    importlib.reload(navd_paths)


def test_pc_navd_default_uses_comma_home(monkeypatch) -> None:
  monkeypatch.delenv("NAVD_ROOT", raising=False)
  monkeypatch.delenv("NAVD_DB_ROOT", raising=False)
  monkeypatch.delenv("NAVD_SOURCE_ROOT", raising=False)
  monkeypatch.delenv("NAVD_TMP_ROOT", raising=False)

  paths = importlib.reload(navd_paths)
  if not paths.PC:
    return

  expected_root = Path.home() / f".comma{os.environ.get('OPENPILOT_PREFIX', '')}" / "navd"
  try:
    assert paths.DEFAULT_NAVD_ROOT == expected_root
    assert paths.DEFAULT_NAVD_DB_DIR == expected_root / "db"
    assert paths.DEFAULT_NAVD_SOURCE_DIR == expected_root / "source"
    assert paths.DEFAULT_NAVD_TMP_DIR == expected_root / "tmp"
  finally:
    importlib.reload(navd_paths)


def test_navd_specific_env_overrides(tmp_path, monkeypatch) -> None:
  monkeypatch.setenv("NAVD_ROOT", str(tmp_path / "navd"))
  monkeypatch.setenv("NAVD_DB_ROOT", str(tmp_path / "db"))
  monkeypatch.setenv("NAVD_SOURCE_ROOT", str(tmp_path / "source"))
  monkeypatch.setenv("NAVD_TMP_ROOT", str(tmp_path / "tmp"))

  paths = importlib.reload(navd_paths)
  try:
    assert paths.DEFAULT_NAVD_DB_DIR == tmp_path / "db"
    assert paths.DEFAULT_NAVD_SOURCE_DIR == tmp_path / "source"
    assert paths.DEFAULT_NAVD_TMP_DIR == tmp_path / "tmp"
  finally:
    for key in ("NAVD_ROOT", "NAVD_DB_ROOT", "NAVD_SOURCE_ROOT", "NAVD_TMP_ROOT"):
      monkeypatch.delenv(key, raising=False)
    importlib.reload(navd_paths)


def test_ensure_navd_dirs_creates_standard_layout(tmp_path, monkeypatch) -> None:
  monkeypatch.setenv("NAVD_ROOT", str(tmp_path / "navd"))

  paths = importlib.reload(navd_paths)
  try:
    paths.ensure_navd_dirs()

    assert (tmp_path / "navd" / "db").is_dir()
    assert (tmp_path / "navd" / "source").is_dir()
    assert (tmp_path / "navd" / "source" / "region").is_dir()
    assert (tmp_path / "navd" / "tmp").is_dir()
  finally:
    monkeypatch.delenv("NAVD_ROOT", raising=False)
    importlib.reload(navd_paths)
