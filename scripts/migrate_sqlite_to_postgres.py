#!/usr/bin/env python3
"""Copy the FoodMaster SQLite database into an empty PostgreSQL database.

The script is intentionally opt-in and refuses to write into a non-empty
target unless --allow-nonempty is supplied. It does not alter or delete the
SQLite source file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, inspect, select


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from menu_core.database import Base  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(BASE_DIR / "data" / "foodmaster_menu.db"),
        help="Path to the SQLite database (default: data/foodmaster_menu.db)",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="SQLAlchemy PostgreSQL URL, for example postgresql://user:pass@host/db",
    )
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="Allow inserting into a target that already contains rows",
    )
    return parser.parse_args()


def migrate(source_path: Path, target_url: str, allow_nonempty: bool = False) -> dict[str, int]:
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite source tidak ditemukan: {source_path}")

    source_engine = create_engine(f"sqlite:///{source_path}")
    target_engine = create_engine(target_url, pool_pre_ping=True)
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    target_metadata = Base.metadata
    target_metadata.create_all(target_engine)

    source_tables = set(inspect(source_engine).get_table_names())
    counts: dict[str, int] = {}

    with target_engine.connect() as target_conn:
        for table in target_metadata.sorted_tables:
            if table.name not in source_tables:
                continue
            existing = target_conn.execute(select(func.count()).select_from(table)).scalar_one()
            if existing and not allow_nonempty:
                raise RuntimeError(
                    f"Target table '{table.name}' sudah berisi {existing} baris. "
                    "Gunakan database kosong atau --allow-nonempty secara eksplisit."
                )

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        for table in target_metadata.sorted_tables:
            if table.name not in source_tables:
                continue
            source_table = source_metadata.tables[table.name]
            rows = [
                dict(row._mapping)
                for row in source_conn.execution_options(stream_results=True).execute(select(source_table))
            ]
            if rows:
                target_conn.execute(table.insert(), rows)
            counts[table.name] = len(rows)

    source_engine.dispose()
    target_engine.dispose()
    return counts


def main() -> int:
    args = parse_args()
    counts = migrate(Path(args.source), args.target, allow_nonempty=args.allow_nonempty)
    for table_name, count in counts.items():
        print(f"{table_name}: {count}")
    print("Migrasi selesai. SQLite source tidak diubah.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
