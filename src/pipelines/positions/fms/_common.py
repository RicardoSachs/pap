# src/pipelines/positions/fms/_common.py
# ---------------------------------------------------------------
# Shared helpers for the FMS positions feed pipelines (forwards, cash,
# and the coming securities / deposits / net_receivables).
#
# These are the pieces that were byte-for-byte identical across feeds:
# portfolio resolution, the backfill-pending flip, run-summary logging,
# and the row-by-row upsert primitives + validators.
#
# What stays in each feed (deliberately NOT here): run_full / run_from_stg
# orchestration, _read_staging_by_batch (per-feed table + columns), and the
# STG_*/FACT_* SQL and column constants. Keeping those local keeps the run
# flow explicit and debuggable.
#
# The two helpers that were feed-specific only by a constant are
# parameterized: new_batch_id(prefix) and
# validate_not_null(df, columns, table, id_col).
# ---------------------------------------------------------------

import logging
from datetime import datetime, timezone

import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Batch id / portfolio resolution
# ---------------------------------------------------------------

def new_batch_id(prefix: str) -> str:
    """Timestamped batch id, e.g. new_batch_id('fms_cash') -> 'fms_cash_20260622_081532'."""
    return f"{prefix}_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_portfolios(conn) -> pd.DataFrame:
    """Load dim_portfolio (source='fms') into a (procode, portfolio_id) DataFrame."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT procode, portfolio_id FROM dim_portfolio WHERE source = 'fms'"
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["procode", "portfolio_id"])
    logger.info(f"loaded {len(df)} FMS portfolios from dim_portfolio")
    return df


def unresolved_funds(stg_df: pd.DataFrame, portfolios: pd.DataFrame) -> list[str]:
    """
    Return the sorted codigo_fondo values present in staging that have no
    matching dim_portfolio (source='fms') row — i.e. the funds
    transform_for_fact will drop.
    """
    if stg_df.empty:
        return []
    known = set(portfolios["procode"])
    present = set(stg_df["codigo_fondo"].dropna().unique())
    return sorted(present - known)


def flip_backfill_pending_to_active(conn, fact_df: pd.DataFrame) -> int:
    """
    Any FMS portfolio in status 'backfill-pending' that produced at least one
    fact row in this run gets promoted to 'active'. Returns the number flipped.
    """
    if fact_df.empty:
        return 0
    portfolio_ids = fact_df["portfolio_id"].unique().tolist()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dim_portfolio
               SET status = 'active', updated_at = CURRENT_TIMESTAMP
             WHERE portfolio_id = ANY(%s)
               AND source = 'fms'
               AND status = 'backfill-pending'
            """,
            (portfolio_ids,),
        )
        flipped = cur.rowcount
    if flipped:
        logger.info(f"flipped {flipped} FMS portfolios from backfill-pending to active")
    return flipped


# ---------------------------------------------------------------
# Run-summary logging
# ---------------------------------------------------------------

def log_reconciliation(
    extracted: int,
    staged: int,
    loaded: int,
    unresolved: list[str],
    flipped: int,
) -> None:
    """One-line run summary so silent under-population is visible."""
    logger.info(
        f"reconciliation: extracted={extracted} staged={staged} "
        f"fact_loaded={loaded} unresolved_funds={len(unresolved)} "
        f"portfolios_activated={flipped}"
    )
    if unresolved:
        logger.warning(f"unresolved codigo_fondo dropped from fact: {unresolved}")


def log_null_counts(df: pd.DataFrame, stage: str) -> None:
    """
    Log any columns carrying nulls at a stage, so a source-origin null is
    visible before it trips a NOT NULL insert. Silent when nothing is null.
    """
    if df.empty:
        return
    nulls = {c: int(df[c].isna().sum()) for c in df.columns if df[c].isna().any()}
    if nulls:
        logger.info(f"null counts [{stage}]: {nulls}")


# ---------------------------------------------------------------
# Loader primitives (row-by-row upsert, matching the project convention)
# ---------------------------------------------------------------

def validate_columns(df: pd.DataFrame, expected: list[str]) -> None:
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing expected columns: {missing}")


def validate_not_null(df: pd.DataFrame, columns: list[str], table: str, id_col: str) -> None:
    """
    Raise a clear error if any NOT NULL fact column contains nulls, naming the
    column and a sample of offending id_col values — so a source-origin null
    fails loudly here instead of as an opaque psycopg NotNullViolation partway
    through the row loop.
    """
    for col in columns:
        null_mask = df[col].isna()
        if null_mask.any():
            n = int(null_mask.sum())
            sample = df.loc[null_mask, id_col].head(5).tolist()
            raise ValueError(
                f"{table}: {n} row(s) have NULL {col} (NOT NULL). "
                f"Sample {id_col}: {sample}"
            )


def execute_row_by_row(
    conn: Connection,
    sql: str,
    df: pd.DataFrame,
    columns: list[str],
    jsonb_column: str = None,
) -> int:
    """
    Iterate the DataFrame row-by-row and execute one INSERT per row (the
    project-wide convention: never trips Postgres's 65535 parameter cap, and
    per-row errors point at the specific offending row). NaN/NaT converted to
    None; jsonb_column values wrapped in Jsonb.
    """
    with conn.cursor() as cur:
        for i, row in df.iterrows():
            params = row_to_params(row, columns, jsonb_column)
            try:
                cur.execute(sql, params)
            except Exception:
                logger.error(f"insert failed for DataFrame row {i}: {dict(row[columns])}")
                raise
    return len(df)


def row_to_params(row: pd.Series, columns: list[str], jsonb_column: str = None) -> tuple:
    """Convert a DataFrame row to a psycopg-ready parameter tuple."""
    out = []
    for col in columns:
        v = row[col]
        if pd.isna(v):
            out.append(None)
        elif col == jsonb_column:
            out.append(Jsonb(v))
        else:
            out.append(v.item() if hasattr(v, "item") else v)
    return tuple(out)
