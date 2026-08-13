# tests/positions/fms/test_common.py
# ---------------------------------------------------------------
# Unit tests for the shared FMS-positions helpers in _common.py. Pure
# functions only (no DB): the row-by-row executor, portfolio helpers that
# need a cursor, and load_portfolios/flip are exercised via the feed
# integration path, not here.
# ---------------------------------------------------------------

import numpy as np
import pandas as pd
import pytest
from psycopg.types.json import Jsonb

from src.pipelines.positions.fms import _common


# ---- new_batch_id ---------------------------------------------

def test_new_batch_id_uses_prefix_and_timestamp():
    bid = _common.new_batch_id("fms_test")
    assert bid.startswith("fms_test_")
    stamp = bid[len("fms_test_"):]
    d, t = stamp.split("_")
    assert len(d) == 8 and d.isdigit()
    assert len(t) == 6 and t.isdigit()


# ---- validate_columns -----------------------------------------

def test_validate_columns_passes_and_raises():
    df = pd.DataFrame([{"a": 1, "b": 2}])
    _common.validate_columns(df, ["a", "b"])  # no raise
    with pytest.raises(ValueError, match="c"):
        _common.validate_columns(df, ["a", "c"])


# ---- validate_not_null (table + id_col parameterized) ---------

def test_validate_not_null_raises_naming_column_table_and_id():
    df = pd.DataFrame([{"key_id": "AAA", "amount": None}])
    with pytest.raises(ValueError) as exc:
        _common.validate_not_null(df, ["amount"], table="fact_x", id_col="key_id")
    msg = str(exc.value)
    assert "amount" in msg and "fact_x" in msg and "AAA" in msg


def test_validate_not_null_passes_when_complete():
    df = pd.DataFrame([{"key_id": "AAA", "amount": 1.0}])
    _common.validate_not_null(df, ["amount"], table="fact_x", id_col="key_id")


# ---- unresolved_funds -----------------------------------------

def test_unresolved_funds():
    stg = pd.DataFrame({"codigo_fondo": ["A", "B", "A", None]})
    portfolios = pd.DataFrame({"procode": ["A"], "portfolio_id": [1]})
    assert _common.unresolved_funds(stg, portfolios) == ["B"]


def test_unresolved_funds_empty_staging():
    portfolios = pd.DataFrame({"procode": ["A"], "portfolio_id": [1]})
    assert _common.unresolved_funds(pd.DataFrame(), portfolios) == []


# ---- row_to_params --------------------------------------------

def test_row_to_params_coerces_nan_numpy_and_jsonb():
    row = pd.Series({"a": np.nan, "b": "x", "c": np.int64(5), "d": {"k": 1}})
    params = _common.row_to_params(row, ["a", "b", "c", "d"], jsonb_column="d")
    assert params[0] is None
    assert params[1] == "x"
    assert params[2] == 5 and isinstance(params[2], int)
    assert isinstance(params[3], Jsonb)


# ---- logging helpers (smoke: must not raise) ------------------

def test_log_helpers_do_not_raise():
    _common.log_reconciliation(3, 3, 3, [], 1)
    _common.log_reconciliation(3, 3, 2, ["FONDOX"], 0)
    _common.log_null_counts(pd.DataFrame({"x": [None, 1]}), "staging")
    _common.log_null_counts(pd.DataFrame(), "staging")
