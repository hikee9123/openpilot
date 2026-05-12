
import sys
import os
import sqlite3
from pathlib import Path

# openpilot 경로 추가
root = Path("D:/openpilot/openpilot")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root.parent))

from selfdrive.navd.osm_roads import find_current_road, connect_readonly_db

def analyze_all_logs_stateless():
    db_path = Path("C:/Users/atom9/.comma/navd/db/osm_roads_kr.sqlite3")
    navd_root = Path("D:/openpilot/logs/navd")
    
    if not db_path.exists():
        print(f"DB not found at {db_path}")
        return

    total_samples = 0
    total_original_success = 0
    total_original_failed = 0
    total_new_success_from_fails = 0
    
    still_failing_points = []
    
    conn = connect_readonly_db(db_path)
    
    log_dirs = [d for d in navd_root.iterdir() if d.is_dir()]
    print(f"Found {len(log_dirs)} log directories.\n")

    for log_dir in log_dirs:
        trace_file = log_dir / "osm_prediction_trace.csv"
        fail_file = log_dir / "osm_prediction_failures.csv"
        
        dir_trace_count = 0
        dir_fail_count = 0
        dir_now_success = 0
        
        if trace_file.exists():
            with open(trace_file, "r", encoding="utf-8") as f:
                dir_trace_count = sum(1 for line in f if line.strip())
        
        if fail_file.exists():
            with open(fail_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    parts = line.split(",")
                    if len(parts) < 5: continue
                    
                    try:
                        lat, lon, bearing, speed = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                        dir_fail_count += 1
                        
                        # OSMRoadPredictor.update 대신 직접 find_current_road 호출 (상태 무관)
                        match = find_current_road(conn, lat, lon, bearing)
                        
                        if match:
                            dir_now_success += 1
                        else:
                            still_failing_points.append({
                                "log": log_dir.name,
                                "lat": lat, "lon": lon, "bearing": bearing, "speed": speed
                            })
                    except (ValueError, IndexError):
                        continue
        
        total_samples += (dir_trace_count + dir_fail_count)
        total_original_success += dir_trace_count
        total_original_failed += dir_fail_count
        total_new_success_from_fails += dir_now_success
        
        print(f"Log: {log_dir.name}")
        print(f"  - Original Success: {dir_trace_count}")
        print(f"  - Original Failed: {dir_fail_count}")
        print(f"  - Now Recovered: {dir_now_success} / {dir_fail_count}")

    conn.close()

    total_new_success = total_original_success + total_new_success_from_fails
    print("\n" + "="*40)
    print("GLOBAL STATISTICS (All Logs)")
    print("="*40)
    print(f"Total Combined Samples: {total_samples}")
    print(f"Original Global Success Rate: {(total_original_success/total_samples)*100:.4f}%")
    print(f"Updated Global Success Rate: {(total_new_success/total_samples)*100:.4f}%")
    print(f"Total Still Failing: {len(still_failing_points)}")
    
    if still_failing_points:
        print("\n--- Analysis of Persistent Failures ---")
        # 실패 지점들을 좌표별로 그룹화하여 주요 지점 파악
        clusters = {}
        for p in still_failing_points:
            key = f"{p['lat']:.4f}, {p['lon']:.4f}"
            clusters[key] = clusters.get(key, 0) + 1
        
        sorted_clusters = sorted(clusters.items(), key=lambda x: x[1], reverse=True)
        for loc, count in sorted_clusters[:10]:
            print(f"Location {loc}: {count} failures")

if __name__ == "__main__":
    analyze_all_logs_stateless()
