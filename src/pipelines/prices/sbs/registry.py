
# src/pipeline/prices/sbs/registry.py
# ---------------------------------------------------------------
# Shared SBS universe registration logic.
# Called as Step 1 in each SBS pipeline run() before _classify().
#
# Discovers new instruments from the raw file DataFrame,
# diffs against already-registered codigo_sbs values in the DB,
# and registers new instruments directly into:
#   dim_entity
#   dim_entity_identifiers  (codigo_sbs + isin)
#   dim_security            (skeleton only)
#   series_registry         (one row per field, status=backfill-pending)
#
# Bypasses series.csv entirely - SBS universe is discovered
# from the regulator files, not manually curated.
#
# created_at in series_registry records when each instrument
# first appeared in the SBS files, providing the audit trail.
# ---------------------------------------------------------------

import logging
from datetime import date
from typing import Optional

import pandas as pd

from src.db.connection import get_connection
from src.db.queries import (
    get_or_create_entity_id,
    upsert_entity_identifier,
    resolve_entity_id_from_identifier
)

logger = logging.getLogger(__name__)


# ---- Field sets per file type ---------------------------------
# Maps file type name to the series fields that should be
# registered in series_registry for each instrument.

FILE_TYPE_FIELDS = {
    "vector_completo": ["PX_LAST"],
    "rf_local": [
        "PX_CLEAN_MNT", "PX_CLEAN_PCT",
        "PX_DIRTY_MNT", "PX_DIRTY_PCT",
        "ACCRUED_INT", "YTM", "SPREAD",
        "YTW", "DURATION",
        "CHG_CLEAN", "CHG_DIRTY", "CHG_YTM",
    ],
    "rf_exterior": [
        "PX_CLEAN_MNT", "PX_CLEAN_PCT",
        "PX_DIRTY_MNT", "PX_DIRTY_PCT",
        "ACCRUED_INT", "CHG_DIRTY",
    ],
    "tipo_cambio": ["PX_BID", "PX_ASK", "CHG_BID", "CHG_ASK"],
    "dividendos": ["DIV_ADJ_FACTOR"],
}


# ---- Public entry point ----------------------------------------

def discover_and_register(
    raw_df: pd.DataFrame,
    file_type: str,
    run_date: date,
    domain: str = "prices",
    source: str = "sbs",
    frequency: str = "daily",
) -> int:
    """
    Discovers new instruments in raw_df and registers them in the DB.
    Called as Step 1 in each SBS pipeline run() before _classify().

    Two-pass registration:
        Pass 1: normal ISIN instruments
        Pass 2: X-ISIN instruments (separate entities, Bloomberg linkage via prefix)

    raw_df:    raw DataFrame from read_raw() in extract.py.
               Must contain at minimum: codigo_sbs, isin (optional),
               tipo_instrumento (optional).
               For tipo_cambio: moneda_nocional, moneda_contraparte, fuente.

    file_type: one of vector_completo, rf_local, rf_exterior, tipo_cambio.
    run_date:  used as default_start_date for newly registered series.

    Returns number of new series registered.
    """
    if raw_df.empty:
        logger.info(f"registry [{file_type}]: empty DataFrame, nothing to register.")
        return 0

    fields = FILE_TYPE_FIELDS.get(file_type)
    if not fields:
        logger.warning(f"registry: unknown file_type '{file_type}'. Skipping.")
        return 0

    if file_type == "tipo_cambio":
        return _register_fx(
            raw_df=raw_df,
            fields=fields,
            run_date=run_date,
            domain=domain,
            source=source,
            frequency=frequency,
        )
    else:
        return _register_securities(
            raw_df=raw_df,
            file_type=file_type,
            fields=fields,
            run_date=run_date,
            domain=domain,
            source=source,
            frequency=frequency,
        )


# ---- Securities registration (vector_completo, rf_local, rf_exterior) --

def _register_securities(
    raw_df: pd.DataFrame,
    file_type: str,
    fields: list[str],
    run_date: date,
    domain: str,
    source: str,
    frequency: str,
) -> int:
    """
    Registers bond/equity securities from SBS files.
    One entity per codigo_sbs, multiple series per entity (one per field).

    Three passes:
        Pass 0: register missing series for EXISTING instruments
        Pass 1: normal ISIN instruments (new entities)
        Pass 2: X-ISIN instruments (separate entities)
    """
    # Get already-registered codigo_sbs values
    with get_connection() as conn:
        existing = _get_existing_sbs_codes(conn)

    # Unique instruments in file
    instruments = (
        raw_df[["codigo_sbs", "isin", "tipo_instrumento", "emisor", "moneda"]]
        .drop_duplicates(subset=["codigo_sbs"])
        .dropna(subset=["codigo_sbs"])
    )

    new_instruments = instruments[
        ~instruments["codigo_sbs"].astype(str).isin(existing)
    ]

    # ===================== PASS 0: existing instruments =====================
    # The entity and identifiers already exist (e.g. from vector_completo),
    # but this file_type's fields may not have series rows yet.
    # ON CONFLICT DO NOTHING makes this safe to re-run.
    existing_instruments = instruments[
        instruments["codigo_sbs"].astype(str).isin(existing)
    ]
    registered_existing = 0
    if not existing_instruments.empty:
        with get_connection() as conn:
            for _, row in existing_instruments.iterrows():
                codigo_sbs = str(row["codigo_sbs"]).strip()
                entity_id = resolve_entity_id_from_identifier(
                    conn, id_type="codigo_sbs", id_value=codigo_sbs, source="sbs"
                )
                if entity_id:
                    registered_existing += _register_series(
                        conn, entity_id, fields, run_date, domain, source, frequency
                    )
        if registered_existing:
            logger.info(
                f"registry [{file_type}]: {registered_existing} new series "
                f"registered for existing instruments."
            )
    # ===================== END PASS 0 =====================

    if new_instruments.empty:
        logger.info(
            f"registry [{file_type}]: no new instruments found "
            f"({len(instruments)} already registered)."
        )
        return registered_existing

    logger.info(
        f"registry [{file_type}]: {len(new_instruments)} new instruments "
        f"found in file. Registering..."
    )

    # Split into normal and X-ISIN
    normal_rows = new_instruments[
        ~new_instruments["isin"].apply(_is_x_isin)
    ]
    x_isin_rows = new_instruments[
        new_instruments["isin"].apply(_is_x_isin)
    ]

    registered = 0

    # Pass 1: normal ISINs
    if not normal_rows.empty:
        logger.info(
            f"registry [{file_type}]: Pass 1 - "
            f"{len(normal_rows)} normal ISIN instruments."
        )
        with get_connection() as conn:
            for _, row in normal_rows.iterrows():
                registered += _register_normal_instrument(
                    conn, row, fields, run_date, domain, source, frequency
                )

    # Pass 2: X-ISINs (always separate entities, after Pass 1)
    if not x_isin_rows.empty:
        logger.info(
            f"registry [{file_type}]: Pass 2 - "
            f"{len(x_isin_rows)} X-ISIN instruments."
        )
        with get_connection() as conn:
            for _, row in x_isin_rows.iterrows():
                registered += _register_x_isin_instrument(
                    conn, row, fields, run_date, domain, source, frequency
                )

    total = registered + registered_existing
    logger.info(
        f"registry [{file_type}]: {total} new series registered "
        f"({registered} new instruments, {registered_existing} existing instruments)."
    )
    return total


def _register_normal_instrument(
    conn,
    row,
    fields: list[str],
    run_date: date,
    domain: str,
    source: str,
    frequency: str,
) -> int:
    """
    Registers a normal ISIN instrument.
    Attempts to resolve against existing entity via ISIN.
    Creates new entity if not found.
    """
    codigo_sbs       = str(row["codigo_sbs"]).strip()
    isin             = _clean(row.get("isin"))
    tipo_instrumento = _clean(row.get("tipo_instrumento"))

    # Try to resolve existing entity via ISIN
    entity_id = None
    if isin:
        entity_id = resolve_entity_id_from_identifier(
            conn, id_type="isin", id_value=isin, source=None
        )
        
        # logger.info(
        #     f'entity_id found from isin:{entity_id}'
        #     f'isin:{isin}') #

    if entity_id is None:
        #logger.info('Creating entity')
        # New entity
        internal_code = f"SBS_{codigo_sbs}"
        entity_id = get_or_create_entity_id(
            conn,
            procode=internal_code,
            entity_type="security",
            name=_derive_name(row),
        )
        # dim_security skeleton
        conn.execute(
            """
            INSERT INTO dim_security (entity_id, security_type)
            VALUES (%s, %s)
            ON CONFLICT (entity_id) DO NOTHING
            """,
            (entity_id, tipo_instrumento),
        )
    else:
        logger.debug(
            f"Linked SBS instrument {codigo_sbs} to existing "
            f"entity_id={entity_id} via ISIN {isin}."
        )
    # DEBUGG: VERIFY
    # logger.info(f'entity_id={entity_id}')

    # verify = conn.execute(
    #     "SELECT entity_id FROM dim_entity WHERE entity_id = ?",
    #     (entity_id,)
    # ).fetchone()

    # logger.info(
    #     f'entity_id={entity_id} verify={verify}'
    # )

    # Always store codigo_sbs on the entity (new or existing)
    upsert_entity_identifier(
        conn, entity_id, "codigo_sbs", codigo_sbs, "sbs", is_primary=True
    )
    # ISIN stored as source="internal" - universal standard identifier
    if isin:
        upsert_entity_identifier(
            conn, entity_id, "isin", isin, "internal", is_primary=False
        )

    return _register_series(
        conn, entity_id, fields, run_date, domain, source, frequency
    )


def _register_x_isin_instrument(
    conn,
    row,
    fields: list[str],
    run_date: date,
    domain: str,
    source: str,
    frequency: str,
) -> int:
    """
    Registers an X-ISIN instrument as a SEPARATE entity.

    X-ISIN variants cannot share an entity with their parent because
    series_registry requires unique (entity_id, field, source) and
    both variants report the same fields from source='sbs'.

    Attempts parent ISIN prefix lookup for Bloomberg enrichment linkage.
    Stores parent_entity_id as a reference identifier if found.
    Flags unresolved cases with a warning.
    """
    codigo_sbs       = str(row["codigo_sbs"]).strip()
    isin_x           = _clean(row.get("isin"))
    tipo_instrumento = _clean(row.get("tipo_instrumento"))

    # Always create a new entity for this X-ISIN variant
    internal_code = f"SBS_{codigo_sbs}"
    entity_id = get_or_create_entity_id(
        conn,
        procode=internal_code,
        entity_type="security",
        name=_derive_name(row),
    )

    # dim_security skeleton
    conn.execute(
        """
        INSERT INTO dim_security (entity_id, security_type)
        VALUES (%s, %s)
        ON CONFLICT (entity_id) DO NOTHING
        """,
        (entity_id, tipo_instrumento),
    )

    # Store X-ISIN and codigo_sbs
    upsert_entity_identifier(
        conn, entity_id, "codigo_sbs", codigo_sbs, "sbs", is_primary=True
    )
    if isin_x:
        upsert_entity_identifier(
            conn, entity_id, "isin_x", isin_x, "sbs", is_primary=False
        )

    # Attempt parent resolution via ISIN prefix (first 11 chars)
    if isin_x:
        prefix        = isin_x[:-1]   # strip the X
        parent_entity = _resolve_by_isin_prefix(conn, prefix)

        if parent_entity:
            # Store parent entity reference for Bloomberg enrichment
            # This is NOT a merge - just a hint for enrichment pipelines
            upsert_entity_identifier(
                conn, entity_id,
                id_type="isin_prefix",
                id_value=prefix,
                source="sbs",
                is_primary=False,
            )
            conn.execute(
                """
                INSERT INTO dim_entity_identifiers
                    (entity_id, id_type, id_value, source, is_primary)
                VALUES (%s, 'parent_entity_id', %s, 'sbs', FALSE)
                ON CONFLICT (entity_id, id_type, source) DO UPDATE SET
                    id_value = EXCLUDED.id_value
                """,
                (entity_id, str(parent_entity)),
            )
            logger.debug(
                f"X-ISIN {isin_x} (entity_id={entity_id}) linked to "
                f"parent entity_id={parent_entity} via prefix {prefix}."
            )
        else:
            # Store prefix only - flag for manual review
            upsert_entity_identifier(
                conn, entity_id,
                id_type="isin_prefix",
                id_value=prefix,
                source="sbs",
                is_primary=False,
            )
            logger.warning(
                f"X-ISIN {isin_x} (codigo_sbs={codigo_sbs}): "
                f"no parent entity found for prefix '{prefix}'. "
                f"Bloomberg enrichment will not be linked until "
                f"parent instrument is onboarded. "
                f"entity_id={entity_id} flagged for manual review."
            )

    return _register_series(
        conn, entity_id, fields, run_date, domain, source, frequency
    )


# ---- FX registration (tipo_cambio) -----------------------------

def _register_fx(
    raw_df: pd.DataFrame,
    fields: list[str],
    run_date: date,
    domain: str,
    source: str,
    frequency: str,
) -> int:
    """
    Registers FX currency pairs from tipo_cambio file.
    Internal code: SBS_FX_{moneda_nocional}_{moneda_contraparte}_{fuente}
    One entity per pair+source, multiple series per entity.
    """
    with get_connection() as conn:
        existing = _get_existing_sbs_codes(conn)

    pairs = (
        raw_df[["moneda_nocional", "moneda_contraparte", "fuente"]]
        .drop_duplicates()
        .dropna(subset=["moneda_nocional", "moneda_contraparte", "fuente"])
    )

    registered = 0

    with get_connection() as conn:
        for _, row in pairs.iterrows():
            mn  = str(row["moneda_nocional"]).strip()
            mc  = str(row["moneda_contraparte"]).strip()
            src = str(row["fuente"]).strip()

            # Unique codigo for this pair+source
            codigo_sbs    = f"FX_{mn}_{mc}_{src}"
            internal_code = f"SBS_{codigo_sbs}"

            if codigo_sbs in existing:
                continue

            # 1. dim_entity
            entity_id = get_or_create_entity_id(
                conn,
                procode=internal_code,
                entity_type="security",
                name=f"{mn}/{mc} ({src})",
            )

            # 2. dim_entity_identifiers
            upsert_entity_identifier(
                conn, entity_id,
                id_type="codigo_sbs",
                id_value=codigo_sbs,
                source="sbs",
                is_primary=True,
            )

            # Store pair components for pipeline lookup
            for id_type, id_value in [
                ("moneda_nocional",    mn),
                ("moneda_contraparte", mc),
                ("fuente",             src),
            ]:
                conn.execute(
                    """
                    INSERT INTO dim_entity_identifiers
                        (entity_id, id_type, id_value, source, is_primary)
                    VALUES (%s, %s, %s, 'sbs', FALSE)
                    ON CONFLICT (entity_id, id_type, source) DO NOTHING
                    """,
                    (entity_id, id_type, id_value),
                )

            # 3. dim_security skeleton
            conn.execute(
                """
                INSERT INTO dim_security (entity_id, security_type)
                VALUES (%s, 'fx')
                ON CONFLICT (entity_id) DO NOTHING
                """,
                (entity_id,),
            )

            # 4. dim_security_fx
            # cur = conn.execute(
            #     "SELECT security_id FROM dim_security WHERE entity_id = %s",
            #     (entity_id,),
            # )
            # sec = cur.fetchone()
            # if sec:
            #     conn.execute(
            #         """
            #         INSERT INTO dim_security_fx
            #             (security_id, base_currency, quote_currency, pair, fx_type)
            #         VALUES (%s, %s, %s, %s, 'spot')
            #         ON CONFLICT (security_id) DO NOTHING
            #         """,
            #         (sec["security_id"], mn, mc, f"{mn}/{mc}"),
            #     )

            # 5. series_registry - one row per field
            for field in fields:
                # Store pair metadata on series for lookup in transform
                cur = conn.execute(
                    """
                    INSERT INTO series_registry (
                        entity_id, field, domain, source, frequency,
                        default_start_date, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'backfill-pending')
                    ON CONFLICT (entity_id, field, source) DO NOTHING
                    """,
                    (
                        entity_id, field, domain, source, frequency,
                        run_date.isoformat(),
                    ),
                )
                if cur.rowcount > 0:
                    registered += 1

            logger.debug(f"Registered FX: {internal_code} | {len(fields)} series")

    logger.info(
        f"registry [tipo_cambio]: {registered} new series registered."
    )
    return registered


# ---- Helpers ---------------------------------------------------

def _register_series(
    conn,
    entity_id: int,
    fields: list[str],
    run_date: date,
    domain: str,
    source: str,
    frequency: str,
) -> int:
    """Inserts series_registry rows for each field. Returns count inserted."""
    inserted = 0
    for field in fields:
        cur = conn.execute(
            """
            INSERT INTO series_registry (
                entity_id, field, domain, source, frequency,
                default_start_date, status
            ) VALUES (%s, %s, %s, %s, %s, %s, 'backfill-pending')
            ON CONFLICT (entity_id, field, source) DO NOTHING
            """,
            (entity_id, field, domain, source, frequency, run_date.isoformat()),
        )
        if cur.rowcount > 0:
            inserted += 1
    return inserted


def _get_existing_sbs_codes(conn) -> set[str]:
    """Returns set of all codigo_sbs values already registered."""
    cur = conn.execute(
        """
        SELECT id_value FROM dim_entity_identifiers
        WHERE id_type = 'codigo_sbs' AND source = 'sbs'
        """
    )
    rows = cur.fetchall()
    return {r["id_value"] for r in rows}


def _resolve_by_isin_prefix(conn, prefix: str) -> Optional[int]:
    """
    Finds entity_id whose ISIN starts with the given 11-char prefix.
    Returns entity_id if exactly one match found, None otherwise.
    Multiple matches are logged as a warning.
    """
    cur = conn.execute(
        """
        SELECT DISTINCT entity_id FROM dim_entity_identifiers
        WHERE id_type = 'isin'
          AND source  = 'internal'
          AND LEFT(id_value, 11) = %s
        """,
        (prefix,),
    )
    rows = cur.fetchall()

    if len(rows) == 1:
        return rows[0]["entity_id"]
    if len(rows) > 1:
        logger.warning(
            f"ISIN prefix '{prefix}' matched {len(rows)} entities: "
            f"{[r['entity_id'] for r in rows]}. Cannot resolve uniquely."
        )
    return None


def _is_x_isin(val) -> bool:
    """Returns True if val is an SBS X-ISIN (12 chars ending in X)."""
    if val is None:
        return False
    s = str(val).strip().upper()
    return len(s) == 12 and s.endswith("X")


def _derive_name(row) -> Optional[str]:
    """Derives a human-readable name from available row attributes."""
    emisor = _clean(row.get("emisor"))
    tipo   = _clean(row.get("tipo_instrumento"))
    isin   = _clean(row.get("isin"))
    parts  = [p for p in [emisor, tipo, isin] if p]
    return " | ".join(parts) if parts else None


def _clean(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none", "") else None
