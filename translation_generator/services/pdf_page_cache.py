"""
Process-level cache for rendered PDF pages.

Prevents the same PDF from being re-rendered at the same DPI multiple times
within a single request (e.g. main OCR + stamp crop + apostille crop).
Keyed by (pdf content fingerprint, dpi, first_page, last_page).
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from PIL import Image

# Cache storage: {(fingerprint, dpi, first_page, last_page): [PIL.Image, ...]}
_cache: dict[tuple, list[Image.Image]] = {}
_MAX_ENTRIES = 10  # Keep at most 10 distinct renders in memory


def _find_poppler() -> str | None:
    """Resolve poppler binary directory (mirrors ocr_reader logic)."""
    if shutil.which("pdfinfo"):
        return None
    env = os.getenv("POPPLER_PATH", "").strip()
    if env:
        d = Path(env)
        if d.is_dir() and (d / "pdfinfo").exists():
            return str(d)
        if d.is_file() and d.name == "pdfinfo":
            return str(d.parent)
    for candidate in [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]:
        if (candidate / "pdfinfo").exists():
            return str(candidate)
    return None


def _key(pdf_bytes: bytes, dpi: int, first_page: int, last_page: int) -> tuple:
    # Hash only the first 4 KB + total length — fast fingerprint
    h = hashlib.md5(
        pdf_bytes[:4096] + len(pdf_bytes).to_bytes(8, "big")
    ).hexdigest()
    return (h, dpi, first_page, last_page)


def get_pages(
    pdf_bytes: bytes,
    dpi: int = 250,
    first_page: int = 1,
    last_page: int = 0,
) -> list[Image.Image]:
    """
    Return rendered PIL Image pages for *pdf_bytes*, using a process-level cache.

    Parameters
    ----------
    pdf_bytes : bytes
        Raw PDF file content.
    dpi : int
        Render resolution. 250 is the default for crop OCR.
    first_page : int
        1-based first page to render (1 = start).
    last_page : int
        1-based last page to render (0 = all pages).
    """
    cache_key = _key(pdf_bytes, dpi, first_page, last_page)
    if cache_key in _cache:
        return _cache[cache_key]

    # Evict oldest entry when full
    while len(_cache) >= _MAX_ENTRIES:
        _cache.pop(next(iter(_cache)))

    from pdf2image import convert_from_bytes

    kwargs: dict = dict(dpi=dpi, poppler_path=_find_poppler())
    if first_page > 1:
        kwargs["first_page"] = first_page
    if last_page > 0:
        kwargs["last_page"] = last_page

    try:
        pages: list[Image.Image] = convert_from_bytes(pdf_bytes, **kwargs)
    except Exception:  # noqa: BLE001
        pages = []

    _cache[cache_key] = pages
    return pages


def invalidate(pdf_bytes: bytes | None = None) -> None:
    """Clear cached renders for a specific PDF (or all entries if None)."""
    if pdf_bytes is None:
        _cache.clear()
        return
    prefix = _key(pdf_bytes, 0, 0, 0)[0]
    for k in [k for k in _cache if k[0] == prefix]:
        del _cache[k]
