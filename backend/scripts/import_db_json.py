#!/usr/bin/env python3
# ruff: noqa: E402
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import text

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
            "connection string. If you use Docker, run the import inside the backend container or "
            "set DATABASE_URL to the host-accessible Postgres (e.g. "
            "postgresql://postgres:postgres@localhost:5432/delivery_calc)."
        ) from error
    raise error


def _load_payload(input_path: Path) -> Dict[str, Any]:
    if not input_path.exists():
        raise FileNotFoundError(
            "Snapshot file not found: "
            f"{input_path}. Run the export script first or pass the correct path via --input."
        )
    with input_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if "data" not in payload:
        raise ValueError("Snapshot JSON must contain a 'data' section.")
    return payload


def _reset_sequences_if_needed(connection) -> None:
    if engine.dialect.name != "postgresql":
        return

    for table in Base.metadata.sorted_tables:
        pk_columns = [col for col in table.primary_key.columns if col.autoincrement]
        if not pk_columns:
            continue
        for col in pk_columns:
            seq_name = connection.execute(
                text("SELECT pg_get_serial_sequence(:table, :column)"),
                {"table": table.name, "column": col.name},
            ).scalar()
            if not seq_name:
                continue
            connection.execute(
                text(
                    f"SELECT setval('{seq_name}', COALESCE((SELECT MAX({col.name}) FROM {table.name}), 0), true)"
                )
            )


def _coerce_row_types(table, row: Dict[str, Any]) -> Dict[str, Any]:
    coerced = dict(row)
    for column in table.columns:
        value = coerced.get(column.name)
        if value is None:
            continue
        if column.type.__class__.__name__ == "DateTime" and isinstance(value, str):
            try:
                if value.endswith("Z"):
                    value = value[:-1] + "+00:00"
                coerced[column.name] = dt.datetime.fromisoformat(value)
            except ValueError:
                pass
    return coerced


def import_from_json(input_path: Path, truncate: bool) -> None:
    payload = _load_payload(input_path)
    data: Dict[str, List[Dict[str, Any]]] = payload["data"]

    try:
        with engine.begin() as connection:
            if truncate:
                for table in reversed(Base.metadata.sorted_tables):
                    if table.name in data:
                        connection.execute(table.delete())

            for table in Base.metadata.sorted_tables:
                rows = data.get(table.name)
                if not rows:
                    continue
                coerced_rows = [_coerce_row_types(table, row) for row in rows]
                connection.execute(table.insert(), coerced_rows)

            _reset_sequences_if_needed(connection)
    except Exception as exc:
        _explain_connection_error(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import database contents from JSON snapshot.")
    parser.add_argument(
        "--input",
        default="db_snapshot.json",
        help="Path to JSON snapshot file (default: db_snapshot.json).",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Do not delete existing rows before importing.",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    import_from_json(input_path, truncate=not args.no_truncate)
    print(f"Snapshot imported from: {input_path}")


if __name__ == "__main__":
    main()
