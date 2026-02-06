#!/usr/bin/env python3
import argparse
import datetime as dt
import sys
import time
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve()
REPO_ROOT = CURRENT_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUTPUT = REPO_ROOT / "backend" / "storage" / "db_snapshot.json"

def _export_to_json(output_path: Path) -> None:
    from backend.scripts.export_db_json import export_to_json

    export_to_json(output_path)


def run(output_path: Path, interval_hours: float, run_once: bool) -> None:
    interval_seconds = max(interval_hours, 0.01) * 3600

    while True:
        started_at = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
        try:
            _export_to_json(output_path)
            print(f"[{started_at}] Snapshot saved to: {output_path}")
        except Exception as exc:
            print(f"[{started_at}] Snapshot failed: {exc}")

        if run_once:
            break
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DB snapshot export on schedule (default: every 6 hours)."
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path to output JSON file (default: backend/storage/db_snapshot.json).",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=6,
        help="Snapshot interval in hours (default: 6).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one snapshot and exit.",
    )
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve()
    run(output_path=output_path, interval_hours=args.interval_hours, run_once=args.once)


if __name__ == "__main__":
    main()
