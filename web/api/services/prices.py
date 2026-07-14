
# web/api/services/prices.py
# ---------------------------------------------------------------------------
# Prices service : price history for one security, split by source. In the pgetl
# schema prices live in fact_prices keyed by series_id; series_registry resolves
# (entity_id, field, source). The price-viewer compares the PX_LAST series across
# sources for one entity.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from src.db.connection import get_connection

logger = logging.getLogger(__name__)

_ASSET_CLASS = """
    CASE WHEN e.entity_type = 'cash'    THEN 'cash'
         WHEN eq.security_id IS NOT NULL THEN 'equity'
         WHEN bd.security_id IS NOT NULL THEN 'bond'
         WHEN fnd.security_id IS NOT NULL OR e.entity_type = 'fund' THEN 'fund'
         ELSE 'security' END
"""


def get_price_series(
    entity_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    sources: list[str] | None = None,
) -> dict:
    """Return {entity, series:[{source, points:[{date, price}]}]} for one security."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT e.entity_id,
                       COALESCE(s.security_name, s.name, e.name) AS display_name,
                       {_ASSET_CLASS} AS asset_class,
                       eq.sector AS sector,
                       s.ticker,
                       s.currency AS base_currency,
                       idi.id_value AS isin
                FROM dim_entity e
                LEFT JOIN dim_security        s   ON s.entity_id   = e.entity_id
                LEFT JOIN dim_security_equity eq  ON eq.security_id = s.security_id
                LEFT JOIN dim_security_fund   fnd ON fnd.security_id = s.security_id
                LEFT JOIN dim_security_bond   bd  ON bd.security_id = s.security_id
                LEFT JOIN dim_entity_identifiers idi ON idi.entity_id = e.entity_id AND idi.id_type = 'isin'
                WHERE e.entity_id = %s""",
            (entity_id,),
        )
        entity_row = cur.fetchone()
        if entity_row is None:
            return {"entity": None, "series": []}
        entity = dict(entity_row)

        sql = """
            SELECT sr.source, fp.date, fp.price
            FROM series_registry sr
            JOIN fact_prices fp ON fp.series_id = sr.series_id
            WHERE sr.entity_id = %s AND sr.domain = 'prices' AND sr.field = 'PX_LAST'
        """
        params: list = [entity_id]
        if date_from:
            sql += " AND fp.date >= %s::date"
            params.append(date_from)
        if date_to:
            sql += " AND fp.date <= %s::date"
            params.append(date_to)
        if sources:
            placeholders = ",".join("%s" for _ in sources)
            sql += f" AND sr.source IN ({placeholders})"
            params += sources
        sql += " ORDER BY sr.source, fp.date"

        cur.execute(sql, params)
        series: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            series.setdefault(row["source"], []).append(
                {"date": row["date"].isoformat(), "price": row["price"]}
            )

    return {
        "entity": entity,
        "series": [{"source": src, "points": pts} for src, pts in series.items()],
    }

