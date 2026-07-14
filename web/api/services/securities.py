
# web/api/services/securities.py
# ---------------------------------------------------------------------------
# Securities service : read-side lookups over dim_entity (+ dim_security and its
# equity/fund/bond extensions) for the price-viewer picker. asset_class is
# derived from which extension table the security lives in (the real schema has
# no single asset_class column); ISIN comes from dim_entity_identifiers.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

# Shared derivation: high-level asset_class from entity_type + extension tables.
_ASSET_CLASS = """
    CASE WHEN e.entity_type = 'cash'           THEN 'cash'
         WHEN eq.security_id IS NOT NULL        THEN 'equity'
         WHEN bd.security_id IS NOT NULL        THEN 'bond'
         WHEN fnd.security_id IS NOT NULL
              OR e.entity_type = 'fund'         THEN 'fund'
         ELSE 'security' END
"""
_SECURITY_JOINS = """
    FROM dim_entity e
    LEFT JOIN dim_security        s   ON s.entity_id   = e.entity_id
    LEFT JOIN dim_security_equity eq  ON eq.security_id = s.security_id
    LEFT JOIN dim_security_fund   fnd ON fnd.security_id = s.security_id
    LEFT JOIN dim_security_bond   bd  ON bd.security_id = s.security_id
    LEFT JOIN dim_entity_identifiers idi ON idi.entity_id = e.entity_id AND idi.id_type = 'isin'
"""


def list_securities(search: str | None = None, limit: int = 100) -> list[dict]:
    """Return securities for a picker, optionally filtered by name/ticker/ISIN."""
    sql = f"""
        SELECT e.entity_id,
               COALESCE(s.security_name, s.name, e.name) AS display_name,
               s.ticker,
               s.currency AS base_currency,
               {_ASSET_CLASS} AS asset_class,
               eq.sector AS sector,
               idi.id_value AS isin
        {_SECURITY_JOINS}
        WHERE e.entity_type IN ('security', 'fund', 'cash')
    """
    params: list = []
    if search:
        sql += " AND (COALESCE(s.security_name, s.name, e.name) ILIKE %s OR s.ticker ILIKE %s OR idi.id_value ILIKE %s)"
        like = f"%{search}%"
        params += [like, like, like]
    sql += " ORDER BY display_name LIMIT %s"
    params.append(limit)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

