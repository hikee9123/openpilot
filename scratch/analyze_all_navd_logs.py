#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from openpilot.selfdrive.navd.osm_roads import connect_readonly_db, find_current_road
from openpilot.selfdrive.navd.paths import DEFAULT_NAVD_DB_DIR, DEFAULT_NAVD_LOG_DIR


STOPPED_LOG_SPEED_MPS = 1.0
DEFAULT_HORIZONS = (1, 2, 3, 5, 10, 15, 20, 30)
PC_NAVD_DIR = Path.home() / ".comma" / "navd"


@dataclass(frozen=True)
class LogSet:
  name: str
  trace_path: Path
  failure_path: Path


def _read_csv(path: Path) -> list[dict[str, str]]:
  if not path.exists():
    return []
  with path.open("r", encoding="utf-8", newline="") as f:
    return list(csv.DictReader(f))


def _is_graph_mode(row: dict[str, str]) -> bool:
  return row.get("mode", "").startswith("graph")


def _speed_mps(row: dict[str, str]) -> float:
  try:
    return float(row.get("speed_mps", "0") or 0.0)
  except ValueError:
    return 0.0


def _road_id(row: dict[str, str]) -> int | None:
  try:
    return int(row.get("current_road_id", "") or 0) or None
  except ValueError:
    return None


def _road_ids(value: str) -> set[int]:
  ids: set[int] = set()
  for item in (value or "").split():
    try:
      ids.add(int(item))
    except ValueError:
      continue
  return ids


def _debug_value(row: dict[str, str], key: str) -> str:
  match = re.search(rf"(?<!\w){re.escape(key)}=([^\s]+)", row.get("debug", ""))
  return match.group(1) if match is not None else ""


def _row_key(row: dict[str, str]) -> tuple[str, ...]:
  return tuple(row.get(field, "") for field in row.keys())


def _count_failure_subset_mismatch(trace_rows: list[dict[str, str]], failure_rows: list[dict[str, str]]) -> int:
  trace_non_graph = Counter(_row_key(row) for row in trace_rows if not _is_graph_mode(row))
  mismatches = 0
  for row in failure_rows:
    key = _row_key(row)
    if trace_non_graph[key] <= 0:
      mismatches += 1
      continue
    trace_non_graph[key] -= 1
  return mismatches + sum(trace_non_graph.values())


def _format_rate(count: int, total: int) -> str:
  return "0.00%" if total <= 0 else f"{count / total * 100.0:.2f}%"


def _future_hit_counts(rows: list[dict[str, str]], horizon: int) -> tuple[int, int]:
  hits = 0
  total = 0
  for idx, row in enumerate(rows[:-horizon]):
    future_current_id = _road_id(rows[idx + horizon])
    if future_current_id is None:
      continue
    total += 1
    if future_current_id in _road_ids(row.get("predicted_road_ids", "")):
      hits += 1
  return hits, total


def _future_hit_counts_by_reason(rows: list[dict[str, str]], horizon: int) -> list[tuple[str, int, int]]:
  counts: list[tuple[str, int, int]] = []
  reasons = sorted({row.get("failure_reason", "") for row in rows})
  for reason in reasons:
    hits = 0
    total = 0
    for idx, row in enumerate(rows[:-horizon]):
      if row.get("failure_reason", "") != reason:
        continue
      future_current_id = _road_id(rows[idx + horizon])
      if future_current_id is None:
        continue
      total += 1
      if future_current_id in _road_ids(row.get("predicted_road_ids", "")):
        hits += 1
    counts.append((reason or "-", hits, total))
  return counts


def _discover_log_sets(log_root: Path) -> list[LogSet]:
  direct_trace = log_root / "osm_prediction_trace.csv"
  direct_failure = log_root / "osm_prediction_failures.csv"
  if direct_trace.exists():
    return [LogSet(log_root.name, direct_trace, direct_failure)]

  log_sets: list[LogSet] = []
  for log_dir in sorted(path for path in log_root.iterdir() if path.is_dir()):
    trace_path = log_dir / "osm_prediction_trace.csv"
    if trace_path.exists():
      log_sets.append(LogSet(log_dir.name, trace_path, log_dir / "osm_prediction_failures.csv"))
  return log_sets


def analyze_logs(db_path: Path, log_root: Path, horizons: tuple[int, ...]) -> int:
  if not db_path.exists():
    print(f"DB not found: {db_path}")
    return 1
  if not log_root.exists():
    print(f"Log root not found: {log_root}")
    return 1

  log_sets = _discover_log_sets(log_root)
  if not log_sets:
    print(f"No osm_prediction_trace.csv found under {log_root}")
    return 1

  total_rows = 0
  total_graph_rows = 0
  total_failure_rows = 0
  total_moving_rows = 0
  total_moving_graph_rows = 0
  total_stopped_rows = 0
  total_currentless_failures = 0
  total_current_present_failures = 0
  total_recovered_current_match = 0
  total_subset_mismatches = 0
  mode_counts: Counter[str] = Counter()
  reason_counts: Counter[str] = Counter()
  confidence_counts: Counter[str] = Counter()
  failure_clusters: Counter[str] = Counter()
  future_hits: Counter[int] = Counter()
  future_totals: Counter[int] = Counter()

  conn = connect_readonly_db(db_path)
  print(f"Found {len(log_sets)} log set(s) under {log_root}\n")

  try:
    for log_set in log_sets:
      trace_rows = _read_csv(log_set.trace_path)
      failure_rows = _read_csv(log_set.failure_path)
      graph_rows = [row for row in trace_rows if _is_graph_mode(row)]
      non_graph_rows = [row for row in trace_rows if not _is_graph_mode(row)]
      moving_rows = [row for row in trace_rows if _speed_mps(row) >= STOPPED_LOG_SPEED_MPS]
      moving_graph_rows = [row for row in moving_rows if _is_graph_mode(row)]
      stopped_rows = len(trace_rows) - len(moving_rows)
      currentless_failures = [row for row in non_graph_rows if not row.get("current_road_id")]
      current_present_failures = [row for row in non_graph_rows if row.get("current_road_id")]
      subset_mismatches = _count_failure_subset_mismatch(trace_rows, failure_rows)
      recovered_current_match = 0

      for row in non_graph_rows:
        try:
          lat = float(row["lat"])
          lon = float(row["lon"])
          bearing = float(row["bearing_deg"])
        except (KeyError, ValueError):
          continue

        key = f"{lat:.4f}, {lon:.4f}"
        failure_clusters[key] += 1
        if find_current_road(conn, lat, lon, bearing):
          recovered_current_match += 1

      for horizon in horizons:
        hits, horizon_total = _future_hit_counts(trace_rows, horizon)
        future_hits[horizon] += hits
        future_totals[horizon] += horizon_total

      total_rows += len(trace_rows)
      total_graph_rows += len(graph_rows)
      total_failure_rows += len(non_graph_rows)
      total_moving_rows += len(moving_rows)
      total_moving_graph_rows += len(moving_graph_rows)
      total_stopped_rows += stopped_rows
      total_currentless_failures += len(currentless_failures)
      total_current_present_failures += len(current_present_failures)
      total_recovered_current_match += recovered_current_match
      total_subset_mismatches += subset_mismatches
      mode_counts.update(row.get("mode", "-") or "-" for row in trace_rows)
      reason_counts.update(row.get("failure_reason", "-") or "-" for row in trace_rows)
      confidence_counts.update(_debug_value(row, "confidence") or "-" for row in trace_rows)

      print(f"Log: {log_set.name}")
      print(f"  - Trace samples: {len(trace_rows)}")
      print(f"  - Graph samples: {len(graph_rows)} ({_format_rate(len(graph_rows), len(trace_rows))})")
      print(f"  - Failure samples: {len(non_graph_rows)}")
      print(f"  - Failure CSV rows: {len(failure_rows)}")
      print(f"  - Failure CSV/trace mismatch: {subset_mismatches}")
      print(f"  - Stopped samples skipped by logger: {stopped_rows}")
      print(f"  - Moving graph rate: {_format_rate(len(moving_graph_rows), len(moving_rows))}")
      print(f"  - Currentless failures: {len(currentless_failures)}")
      print(f"  - Current-present graph failures: {len(current_present_failures)}")
      print(f"  - Stateless current-match recoverable: {recovered_current_match} / {len(non_graph_rows)}")
      for horizon in horizons:
        hits, horizon_total = _future_hit_counts(trace_rows, horizon)
        print(f"  - Future hit +{horizon}s: {hits}/{horizon_total} ({_format_rate(hits, horizon_total)})")
      if 5 in horizons:
        print("  - Future hit +5s by reason:")
        for reason, hits, horizon_total in _future_hit_counts_by_reason(trace_rows, 5):
          print(f"    {reason}: {hits}/{horizon_total} ({_format_rate(hits, horizon_total)})")
      print()
  finally:
    conn.close()

  print("=" * 48)
  print("GLOBAL STATISTICS")
  print("=" * 48)
  print(f"Trace samples: {total_rows}")
  print(f"Graph samples: {total_graph_rows} ({_format_rate(total_graph_rows, total_rows)})")
  print(f"Failure samples: {total_failure_rows}")
  print(f"Failure CSV/trace mismatch: {total_subset_mismatches}")
  print(f"Stopped samples skipped by logger: {total_stopped_rows}")
  print(f"Moving graph rate: {_format_rate(total_moving_graph_rows, total_moving_rows)}")
  print(f"Currentless failures: {total_currentless_failures}")
  print(f"Current-present graph failures: {total_current_present_failures}")
  print(f"Stateless current-match recoverable: {total_recovered_current_match} / {total_failure_rows}")

  print("\nMode counts:")
  for mode, count in mode_counts.most_common():
    print(f"  - {mode}: {count}")

  print("\nFailure reason counts:")
  for reason, count in reason_counts.most_common():
    print(f"  - {reason}: {count}")

  print("\nConfidence counts:")
  for confidence, count in confidence_counts.most_common():
    print(f"  - {confidence}: {count}")

  print("\nFuture hit rates:")
  for horizon in horizons:
    hits = future_hits[horizon]
    horizon_total = future_totals[horizon]
    print(f"  - +{horizon}s: {hits}/{horizon_total} ({_format_rate(hits, horizon_total)})")

  if failure_clusters:
    print("\nTop failure clusters:")
    for loc, count in failure_clusters.most_common(10):
      print(f"  - {loc}: {count}")

  return 0


def parse_args() -> argparse.Namespace:
  default_db = DEFAULT_NAVD_DB_DIR / "osm_roads_kr.sqlite3"
  if not default_db.exists():
    default_db = PC_NAVD_DIR / "db" / "osm_roads_kr.sqlite3"

  default_logs = DEFAULT_NAVD_LOG_DIR
  if not (default_logs / "osm_prediction_trace.csv").exists():
    default_logs = PC_NAVD_DIR / "logs"

  parser = argparse.ArgumentParser(description="Analyze navd OSM prediction trace/failure CSV logs.")
  parser.add_argument("--db", type=Path, default=default_db,
                      help="Path to osm_roads_kr.sqlite3.")
  parser.add_argument("--logs", type=Path, default=default_logs,
                      help="Directory containing osm_prediction_trace.csv or child log directories.")
  parser.add_argument("--horizons", type=int, nargs="+", default=list(DEFAULT_HORIZONS),
                      help="Future sample offsets used to score predicted road-id hits.")
  return parser.parse_args()


if __name__ == "__main__":
  args = parse_args()
  raise SystemExit(analyze_logs(args.db.expanduser(), args.logs.expanduser(), tuple(args.horizons)))
