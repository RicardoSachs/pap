
# src/pipelines/prices/sbs/rf_local/loader.py
# ---------------------------------------------------------------
# Loads transformed rf_local data into fact_prices and updates
# dim_security with bond attributes discovered from SBS files.
#
# All values are native Python types (date, float) — psycopg3
# handles the PG type mapping automatically.
# ---------------------------------------------------------------

import logging
import pandas as pd

logger = logging.getLogger(__name__)


def load_facts(conn, df: pd.DataFrame) -> tuple[int, int]:
    """
    Inserts transformed rf_local price rows into fact_prices.
    ON CONFLICT (series_id, date) DO NOTHING for idempotency.

    Transform outputs 'date' as a date object — passed directly
    to PostgreSQL without conversion.
    """
    if df.empty:
        return 0, 0
    loaded = skipped = 0
    for _, row in df.iterrows():
        cur = conn.execute(
            """
            INSERT INTO fact_prices (series_id, date, price, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (series_id, date) DO NOTHING
            """,
            (
                int(row["series_id"]),
                row["date"],
                float(row["value"]),
                row["source"],
            ),
        )
        if cur.rowcount > 0:
            loaded += 1
        else:
            skipped += 1
    logger.info(f"fact_prices (rf_local): {loaded} loaded, {skipped} skipped.")
    return loaded, skipped


def load_dims(conn, df: pd.DataFrame) -> None:
    """
    Partial update of dim_security with bond attributes
    discovered from SBS rf_local files.
    Uses COALESCE to preserve existing values — only fills NULLs.
    """
    if df.empty:
        return
    for _, row in df.iterrows():
        conn.execute(
            """
            UPDATE dim_security
            SET security_type = COALESCE(security_type, %s),
                currency      = COALESCE(currency, %s),
                updated_at    = CASE
                    WHEN security_type IS NULL OR currency IS NULL
                    THEN NOW()
                    ELSE updated_at
                END
            WHERE entity_id = %s
            """,
            (
                row.get("instrument_type"),
                row.get("currency"),
                int(row["entity_id"]),
            ),
        )
    logger.info(f"dim_security partial update (rf_local): {len(df)} rows processed.")
