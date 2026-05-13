#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

root = Path("D:/openpilot/openpilot")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root.parent))

from selfdrive.navd.osm_roads import connect_readonly_db, find_current_road


DB_PATH = Path("C:/Users/atom9/.comma/navd/db/osm_roads_kr.sqlite3")
NAVD_LOG_ROOT = Path("D:/openpilot/logs/navd")
STOPPED_LOG_SPEED_MPS = 1.0


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


def analyze_all_logs_stateless() -> None:
  if not DB_PATH.exists():
    print(f"DB not found at {DB_PATH}")
    return
  if not NAVD_LOG_ROOT.exists():
    print(f"Log root not found at {NAVD_LOG_ROOT}")
    return

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
  failure_clusters: Counter[str] = Counter()
  moving_failure_clusters: Counter[str] = Counter()

  conn = connect_readonly_db(DB_PATH)
  log_dirs = sorted(d for d in NAVD_LOG_ROOT.iterdir() if d.is_dir())
  print(f"Found {len(log_dirs)} log directories under {NAVD_LOG_ROOT}\n")

  try:
    for log_dir in log_dirs:
      trace_rows = _read_csv(log_dir / "osm_prediction_trace.csv")
      failure_rows = _read_csv(log_dir / "osm_prediction_failures.csv")
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
        if _speed_mps(row) >= STOPPED_LOG_SPEED_MPS:
          moving_failure_clusters[key] += 1

        if find_current_road(conn, lat, lon, bearing):
          recovered_current_match += 1

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

      print(f"Log: {log_dir.name}")
      print(f"  - Trace samples: {len(trace_rows)}")
      print(f"  - Graph samples: {len(graph_rows)} ({_format_rate(len(graph_rows), len(trace_rows))})")
      print(f"  - Failure samples: {len(non_graph_rows)}")
      print(f"  - Failure CSV rows: {len(failure_rows)}")
      print(f"  - Failure CSV/trace mismatch: {subset_mismatches}")
      print(f"  - Stopped samples skipped by new logger: {stopped_rows}")
      print(f"  - Moving graph rate after stop filter: {_format_rate(len(moving_graph_rows), len(moving_rows))}")
      print(f"  - Currentless failures: {len(currentless_failures)}")
      print(f"  - Current-present graph failures: {len(current_present_failures)}")
      print(f"  - Stateless current-match recoverable: {recovered_current_match} / {len(non_graph_rows)}")
  finally:
    conn.close()

  print("\n" + "=" * 48)
  print("GLOBAL STATISTICS")
  print("=" * 48)
  print(f"Trace samples: {total_rows}")
  print(f"Graph samples: {total_graph_rows} ({_format_rate(total_graph_rows, total_rows)})")
  print(f"Failure samples: {total_failure_rows}")
  print(f"Failure CSV/trace mismatch: {total_subset_mismatches}")
  print(f"Stopped samples skipped by new logger: {total_stopped_rows}")
  print(f"Moving graph rate after stop filter: {_format_rate(total_moving_graph_rows, total_moving_rows)}")
  print(f"Currentless failures: {total_currentless_failures}")
  print(f"Current-present graph failures: {total_current_present_failures}")
  print(f"Stateless current-match recoverable: {total_recovered_current_match} / {total_failure_rows}")

  if failure_clusters:
    print("\nTop failure clusters:")
    for loc, count in failure_clusters.most_common(10):
      print(f"  - {loc}: {count}")

  if moving_failure_clusters:
    print("\nTop moving failure clusters:")
    for loc, count in moving_failure_clusters.most_common(10):
      print(f"  - {loc}: {count}")


if __name__ == "__main__":
  analyze_all_logs_stateless()
