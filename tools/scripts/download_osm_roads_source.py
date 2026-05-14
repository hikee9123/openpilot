#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from importlib import import_module
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
  from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_SOURCE_DIR, ensure_navd_dirs
except ModuleNotFoundError:
  navd_paths = import_module("selfdrive.navd.paths")
  DEFAULT_NAVD_SOURCE_DIR = navd_paths.DEFAULT_NAVD_SOURCE_DIR
  ensure_navd_dirs = navd_paths.ensure_navd_dirs


DEFAULT_SOURCE_URL = "https://download.geofabrik.de/asia/south-korea-latest.osm.pbf"
DEFAULT_OUTPUT = DEFAULT_NAVD_SOURCE_DIR / "south-korea-latest.osm.pbf"


def _md5_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
  digest = hashlib.md5(usedforsecurity=False)
  with path.open("rb") as f:
    for chunk in iter(lambda: f.read(chunk_size), b""):
      digest.update(chunk)
  return digest.hexdigest()


def _remote_md5(md5_url: str) -> str:
  response = requests.get(md5_url, timeout=30)
  response.raise_for_status()
  value = response.text.strip().split()[0].lower()
  if len(value) != 32:
    raise RuntimeError(f"unexpected md5 response from {md5_url}: {response.text[:120]}")
  return value


def _download(url: str, output: Path, expected_md5: str = "") -> None:
  output.parent.mkdir(parents=True, exist_ok=True)
  tmp_path = output.with_suffix(output.suffix + ".download")
  last_log_t = time.monotonic()
  downloaded = 0

  with requests.get(url, stream=True, timeout=(10, 60)) as response:
    response.raise_for_status()
    total = int(response.headers.get("content-length", "0") or 0)
    with tmp_path.open("wb") as f:
      for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
        if not chunk:
          continue
        f.write(chunk)
        downloaded += len(chunk)
        now = time.monotonic()
        if now - last_log_t >= 10.0:
          if total > 0:
            print(f"downloaded {downloaded:,} / {total:,} bytes ({downloaded / total * 100.0:.1f}%)", flush=True)
          else:
            print(f"downloaded {downloaded:,} bytes", flush=True)
          last_log_t = now

  if expected_md5:
    actual_md5 = _md5_file(tmp_path)
    if actual_md5.lower() != expected_md5.lower():
      tmp_path.unlink(missing_ok=True)
      raise RuntimeError(f"md5 mismatch for {tmp_path}: expected {expected_md5}, got {actual_md5}")

  tmp_path.replace(output)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Download the OSM PBF source used to build osm_roads_kr.sqlite3")
  parser.add_argument("--url", default=DEFAULT_SOURCE_URL, help=f"OSM PBF URL (default: {DEFAULT_SOURCE_URL})")
  parser.add_argument("--md5-url", default="", help="Optional .md5 URL. Defaults to <url>.md5 when --skip-md5 is not set.")
  parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"Output PBF path (default: {DEFAULT_OUTPUT})")
  parser.add_argument("--force", action="store_true", help="Download even when the output file already exists and passes md5 validation")
  parser.add_argument("--skip-md5", action="store_true", help="Do not download or verify md5")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  output = args.output.expanduser()
  ensure_navd_dirs(source_dir=output.parent)

  expected_md5 = ""
  if not args.skip_md5:
    md5_url = args.md5_url or f"{args.url}.md5"
    print(f"fetching md5 {md5_url}", flush=True)
    expected_md5 = _remote_md5(md5_url)
    print(f"remote md5 {expected_md5}", flush=True)

  if output.exists() and not args.force:
    if expected_md5:
      print(f"checking existing source {output}", flush=True)
      actual_md5 = _md5_file(output)
      if actual_md5.lower() == expected_md5.lower():
        print(f"source already up to date: {output}", flush=True)
        return 0
      print(f"existing md5 mismatch: expected {expected_md5}, got {actual_md5}; downloading again", flush=True)
    else:
      print(f"source already exists: {output}", flush=True)
      return 0

  print(f"downloading {args.url} -> {output}", flush=True)
  _download(args.url, output, expected_md5)
  print(f"downloaded source {output} ({output.stat().st_size:,} bytes)", flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
