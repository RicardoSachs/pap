# tests/shared/test_env.py
# ---------------------------------------------------------------
# Pins down env accessors:
#   - optional() treats an EMPTY value as unset (regression: the
#     .env.example template ships every key blank, and letting ''
#     win over the default once turned every data path CWD-relative)
#   - required() never falls back
# ---------------------------------------------------------------

import pytest

from src.shared.env import MissingSecret, optional, required


def test_optional_empty_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("TEST_EMPTY", "")
    assert optional("TEST_EMPTY", "default") == "default"


def test_optional_unset_falls_back(monkeypatch):
    monkeypatch.delenv("TEST_UNSET", raising=False)
    assert optional("TEST_UNSET", "default") == "default"


def test_optional_value_wins(monkeypatch):
    monkeypatch.setenv("TEST_VALUE", "value")
    assert optional("TEST_VALUE", "default") == "value"


def test_required_empty_raises(monkeypatch):
    monkeypatch.setenv("TEST_SECRET", "")
    with pytest.raises(MissingSecret):
        required("TEST_SECRET")
