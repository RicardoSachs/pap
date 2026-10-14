# web/api/routes/_spp_common.py
# ---------------------------------------------------------------------------
# Shared plumbing of the SPP routers (spp, spp_write, benchmarks, tradebook):
# the upload limit, the ISO-date parser for URL input, the read-and-validate
# of an uploaded file and the truthy-flag convention of the forms. One owner
# for each so the routers cannot drift.
# ---------------------------------------------------------------------------
from __future__ import annotations

from datetime import date

from fastapi import HTTPException, UploadFile

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_UPLOAD_BYTES = 40 * 10**6  # the SBS historical Excel is ~5 MB


def iso_date(raw) -> str | None:
    """
    ISO date from the URL, or None. Malformed browser input is treated
    as absent - never forwarded into a ::date cast or pd.to_datetime
    where it would become a 500.
    """
    try:
        return date.fromisoformat(str(raw).strip()).isoformat() if raw else None
    except ValueError:
        return None


def is_yes(flag: str | None) -> bool:
    """The forms' truthy convention for flags sent as text."""
    return str(flag or "").lower() in ("1", "true", "si", "yes")


def _too_big(size: int) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"El archivo pesa {size / 1e6:.1f} MB; el limite son "
               f"{MAX_UPLOAD_BYTES // 10**6} MB.")


async def read_upload(upload: UploadFile) -> bytes:
    """
    Reads and validates an upload. The size is checked BEFORE the body
    is read into memory (Starlette knows it from the multipart part);
    the check after the read only covers a client that sent no length.
    Raises HTTPException 400 (empty) or 413 (too big).
    """
    if upload.size is not None and upload.size > MAX_UPLOAD_BYTES:
        raise _too_big(upload.size)
    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=400, detail="No llego ningun archivo.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise _too_big(len(raw))
    return raw
