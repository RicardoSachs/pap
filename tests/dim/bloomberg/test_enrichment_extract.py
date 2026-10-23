# tests/dim/bloomberg/test_enrichment_extract.py
# ---------------------------------------------------------------
# Pure helpers of the enrichment extract: BDP chunking and the request
# sentinel that lets 'new' mode tell "never asked" from "asked, not
# recognised". blpapi is stubbed: only the workstation has it.
# ---------------------------------------------------------------

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("blpapi", MagicMock())

from src.pipelines.dim.bloomberg.security.extract import (  # noqa: E402
    BDP_CHUNK, SENTINEL_FIELD, _chunks, sentinel_rows,
)


def test_chunks_cover_everything_in_order_without_overlap():
    items = list(range(2 * BDP_CHUNK + 7))
    chunks = _chunks(items, BDP_CHUNK)
    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [BDP_CHUNK, BDP_CHUNK, 7]
    assert [x for c in chunks for x in c] == items
    assert _chunks([], BDP_CHUNK) == []


def test_sentinel_marks_answered_and_no_data():
    requested = ["/isin/PE1", "/isin/PE2", "BAP PE Equity"]
    df = sentinel_rows(requested, answered={"/isin/PE1", "BAP PE Equity"}, loaded_at="2026-10-21T09:00:00")

    assert list(df.columns) == ["parsekyable", "field", "value", "loaded_at"]
    assert set(df["field"]) == {SENTINEL_FIELD}
    assert dict(zip(df["parsekyable"], df["value"])) == {
        "/isin/PE1": "answered", "/isin/PE2": "no_data", "BAP PE Equity": "answered",
    }
