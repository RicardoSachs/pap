# scripts/clean_database.py
# ---------------------------------------------------------------
# Drops all tables from a PostgreSQL database, via the project's
# get_connection(). Supports --dry-run. Destructive DDL utility.
# ---------------------------------------------------------------

import sys
from pathlib import Path

sys.path.insert(0,
                str(Path(__file__).resolve().parent.parent))

import argparse
import logging

from src.db.connection import get_connection
from src.shared.logging import setup_logging

logger = logging.getLogger(__name__)

def get_all_tables(conn, schema: str = "public") -> list[str]:
    """Retrieve all table names in the given schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = %s
            ORDER BY tablename;
            """,
            (schema,),
        )
        # dict_row returns dicts
        return [row["tablename"] for row in cur.fetchall()]

def drop_all_tables(
    schema: str = "public",
    dry_run: bool = False,
    config: dict = None,
) -> None:
    """
    Drop all tables in the specified schema.

    Parameters
    ----------
    schema : str
        Schema from which to drop tables (default: 'public').
    dry_run : bool
        If True, only logs the tables that would be dropped.
    config : dict, optional
        Custom DB config dict. If None, uses get_db_config() from
        src.shared.config_pg.
    """
    with get_connection(config) as conn:
        tables = get_all_tables(conn, schema)

        if not tables:
            logger.info("No tables found in schema '%s'. Nothing to do.", schema)
            return

        logger.info(
            "Found %d table(s) in schema '%s': %s",
            len(tables),
            schema,
            ", ".join(tables),
        )

        if dry_run:
            logger.info("[DRY RUN] No tables were dropped.")
            return

        # Drop all tables in a single statement
        table_list = ", ".join(
            f'"{schema}"."{table}"' for table in tables
        )
        drop_query = f"DROP TABLE IF EXISTS {table_list} CASCADE;"

        logger.info("Executing: %s", drop_query)
        with conn.cursor() as cur:
            cur.execute(drop_query)

        # commit is handled by the context manager on clean exit
        logger.info("All %d table(s) dropped successfully.", len(tables))

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Drop all tables from a PostgreSQL database."
    )
    parser.add_argument(
        "--schema",
        type=str,
        default="public",
        help="Target schema (default: 'public').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List tables without dropping them.",
    )
    
    args = parser.parse_args()

    setup_logging('clean_database')

    drop_all_tables(
        schema=args.schema,
        dry_run=args.dry_run,
    )

if __name__ == "__main__":
    main()
