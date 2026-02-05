#!/usr/bin/env python3
# ruff: noqa: E402
import argparse
import datetime as dt
import enum
import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve()
REPO_ROOT = CURRENT_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.database import Base, engine
from backend.models import db_models  # noqa: F401

def _explain_connection_error(error: Exception) -> None:
    if isinstance(error, UnicodeError):
        raise UnicodeError(
            "Failed to connect to the database because DATABASE_URL contains non-UTF-8 characters. "
            "Ensure your .env/backend.env file is saved as UTF-8 and avoid non-UTF-8 symbols in the "
            "connection string. If you use Docker, run the export inside the backend container or "
            "set DATABASE_URL to the host-accessible Postgres (e.g. "
            "postgresql://postgres:postgres@localhost:5432/delivery_calc)."
        ) from error
    raise error


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def export_to_json(output_path: Path) -> None:
    payload = {
        "meta": {
            "exported_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "tables": [],
        },
        "data": {},
    }

    try:
        with engine.connect() as connection:
            for table in Base.metadata.sorted_tables:
                rows = connection.execute(table.select()).mappings().all()
                serialized_rows = []
                for row in rows:
                    serialized_rows.append({key: _serialize_value(value) for key, value in row.items()})
                payload["data"][table.name] = serialized_rows
                payload["meta"]["tables"].append({"name": table.name, "rows": len(serialized_rows)})
    except Exception as exc:
        _explain_connection_error(exc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export database contents to JSON snapshot.")
    parser.add_argument(
        "--output",
        default="db_snapshot.json",
        help="Path to output JSON file (default: db_snapshot.json).",
    )
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve()
    export_to_json(output_path)
    print(f"Snapshot saved to: {output_path}")


if __name__ == "__main__":
    main()
