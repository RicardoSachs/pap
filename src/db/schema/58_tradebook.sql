-- 58_tradebook.sql
-- ---------------------------------------------------------------
-- tradebook: the desk's own operations, one row per trade.
--
-- Grain is the TRADE, not the position: two identical buys of the
-- same bond on the same day at the same price are two rows, because
-- they are two trades. That is why the key is a surrogate id and not
-- the natural columns - a composite key over (fecha, fondo,
-- instrumento, lado, cantidad, precio) would silently collapse them
-- into one and understate the day's volume.
--
-- What keeps a reload from duplicating is `referencia`: the id the
-- source system gives each trade. When it comes, it is unique and the
-- load upserts on it; when it does not, the load can only offer the
-- operator a count of what looks like a repeat. Hence the PARTIAL
-- unique index - a plain UNIQUE would allow exactly one NULL row in
-- the whole table.
--
-- Direction lives in `lado` alone. `monto` and `cantidad` are always
-- positive: signing them too would let a row say "sell" twice and
-- disagree with itself, and every reader would have to decide which
-- of the two to believe.
--
-- `instrumento` is the text the source used, kept verbatim so a row
-- always says what was traded. `entity_id` is that text RESOLVED to
-- the security dimension, and stays NULL when it cannot be - the
-- trade is still a fact, whether or not we manage to name it in our
-- own dimension.
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tradebook (
    operacion_id      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Idempotency handle from the source system, when it has one.
    referencia        TEXT,

    -- What, when, for whom
    fecha             DATE    NOT NULL,
    fondo             INTEGER NOT NULL,
    lado              TEXT    NOT NULL
        CONSTRAINT ck_tradebook_lado
        CHECK (lado IN ('compra', 'venta')),
    instrumento       TEXT    NOT NULL
        CONSTRAINT ck_tradebook_instrumento
        CHECK (length(trim(instrumento)) > 0),
    entity_id         INTEGER REFERENCES dim_entity(entity_id),

    -- How much. cantidad * precio should be monto, but the source is
    -- the authority on monto: fees, accrued interest and rounding make
    -- the product disagree, and recomputing it here would quietly
    -- restate what the desk actually paid.
    cantidad          NUMERIC(24, 8) NOT NULL
        CONSTRAINT ck_tradebook_cantidad CHECK (cantidad > 0),
    precio            NUMERIC(18, 8),
    monto             NUMERIC(18, 4) NOT NULL
        CONSTRAINT ck_tradebook_monto CHECK (monto >= 0),
    moneda            TEXT    NOT NULL
        CONSTRAINT ck_tradebook_moneda
        CHECK (length(trim(moneda)) > 0),

    -- With whom, and when it settles
    contraparte       TEXT,
    fecha_liquidacion DATE,

    -- Where the row came from. 'posiciones' means it was DERIVED from
    -- a change in holdings rather than observed as a trade, which is
    -- weaker evidence and has to stay visible in the row itself.
    origen            TEXT NOT NULL DEFAULT 'manual'
        CONSTRAINT ck_tradebook_origen
        CHECK (origen IN ('excel', 'manual', 'posiciones')),
    nota              TEXT,

    creado_en         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Settlement before trade is a typo, never a trade.
    CONSTRAINT ck_tradebook_liquidacion
        CHECK (fecha_liquidacion IS NULL OR fecha_liquidacion >= fecha)
);

-- Partial, so the many rows without a source id do not collide with
-- each other while the ones that have it stay unique.
CREATE UNIQUE INDEX IF NOT EXISTS ux_tradebook_referencia
    ON tradebook (referencia) WHERE referencia IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_tradebook_fecha
    ON tradebook (fecha DESC);
CREATE INDEX IF NOT EXISTS ix_tradebook_fondo_fecha
    ON tradebook (fondo, fecha DESC);
CREATE INDEX IF NOT EXISTS ix_tradebook_contraparte
    ON tradebook (contraparte);
CREATE INDEX IF NOT EXISTS ix_tradebook_entity
    ON tradebook (entity_id);
