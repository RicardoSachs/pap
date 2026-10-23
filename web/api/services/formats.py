# web/api/services/formats.py
# ---------------------------------------------------------------------------
# Which columns each upload site expects: just enough to draw the help
# window - the headers and one example row.
#
# The column NAMES come from the same constants the reader parses with,
# not from a list written apart. A separate list drifts the first time
# someone touches a reader, and then it lies - worse than being absent,
# because the operator follows it and the file fails for no visible reason.
#
# The only hand-written parts are the example row, which cannot be derived
# from anything, and the SBS history: there is no column reader to consult
# there - it is the Excel the SBS publishes, with its own layout - so
# instead of a table it carries `notes`, which the window shows when there
# are no columns to display.
# ---------------------------------------------------------------------------
from __future__ import annotations

from src.pipelines.tradebook import operaciones as tb


def _column(name: str, required: bool, example=None) -> dict:
    """What the window shows for each column, and nothing more."""
    return {"name": name, "required": required, "example": example}


TRADEBOOK_EXAMPLE = {
    "fecha": "10/09/2026", "fondo": "2", "lado": "compra",
    "instrumento": "PERU 3.55 03/31", "cantidad": "1,000,000", "precio": "98.45",
    "monto": "984,500.00", "moneda": "USD", "contraparte": "BCP",
    "referencia": "OP00123",
    "trader": "R. SACHS", "nota": "", "operador": "M. LOPEZ",
}


def _tradebook(origin: str) -> dict:
    from_traders = origin in tb.ORIGENES_TRADER
    columns = []
    for name in tb._ALIAS:
        if name == "trader" and not from_traders:
            continue
        required = name in tb._OBLIGATORIAS or (name == "trader" and from_traders)
        columns.append(_column(tb.encabezado(name), required, TRADEBOOK_EXAMPLE.get(name)))
    return {
        "title": ("Operaciones · registro del trader" if from_traders
                  else "Operaciones · reporte de FMS"),
        "columns": columns,
        "template": f"/api/tradebook/plantilla?origen={origin}",
    }


def _valor_cuota_history() -> dict:
    """The one that comes from no column reader: the SBS's own Excel,
    and what there is to say about the format is not to touch it."""
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
    "tradebook_traders": lambda: _tradebook("excel"),
    "tradebook_fms": lambda: _tradebook("fms"),
    "valor_cuota_history": _valor_cuota_history,
}


def describe(key: str) -> dict:
    """The format of one upload site. Raises KeyError for an unknown key."""
    if key not in FORMATS:
        raise KeyError(key)
    return {"key": key, **FORMATS[key]()}
