import csv
import sqlite3
from pathlib import Path

_TABLES = ("teams", "games", "agent_decisions", "draft_results", "standings_snapshots", "skill_history")


def export_run(db_path: str | Path, run_id: str, out_dir: str | Path = "results") -> list[Path]:
    """Export all data tables for a run to CSV files. Returns list of paths written."""
    conn = sqlite3.connect(str(db_path))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for table in _TABLES:
        cursor = conn.execute(f"SELECT * FROM {table} WHERE run_id = ?", (run_id,))
        headers = [d[0] for d in cursor.description]
        path = out / f"{run_id}_{table}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(cursor.fetchall())
        paths.append(path)

    conn.close()
    return paths
