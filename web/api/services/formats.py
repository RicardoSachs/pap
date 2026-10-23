# web/api/services/formats.py
# ---------------------------------------------------------------------------
# Which columns each upload site expects: just enough to draw the help
# window - the headers and one example row.
#
# The column NAMES must come from the same constants the reader parses
# with, not from a list written apart: a separate list drifts the first
# time someone touches a reader, and then it lies - worse than being
# absent, because the operator follows it and the file fails for no
# visible reason. Today the one upload site is the SBS history, which has
# no column reader to consult: it is the Excel the SBS publishes, with its
# own layout, so instead of a table it carries `notes`, which the window
# shows when there are no columns to display.
# ---------------------------------------------------------------------------
from __future__ import annotations


def _valor_cuota_history() -> dict:
    return {
        "title": "Unit value history (the SBS file)",
        "columns": [],
        "notes": [
            "Download it with the \"Open the SBS page\" button next to this one, "
            "and choose \"Valores cuota desde Agosto 1993\".",
            "It brings the four AFPs and the four fund types on the same "
            "sheet; the reader splits them on its own.",
            "Future dates are discarded and reported.",
            "Uploading it loads NOTHING yet: it first shows what would change, "
            "and the load is confirmed afterwards.",
        ],
        "template": None,
    }


FORMATS = {
    "valor_cuota_history": _valor_cuota_history,
}


def describe(key: str) -> dict:
    """The format of one upload site. Raises KeyError for an unknown key."""
    if key not in FORMATS:
        raise KeyError(key)
    return {"key": key, **FORMATS[key]()}
