"""
Apostille Crop OCR Service
==========================
Renders page 2 of a PCC PDF, applies targeted noise-removal preprocessing
to the sticker area, and extracts stamp_no (0I XXXXXXX) and apostille_date.

Called automatically when normal text-based extraction returns empty values.
Designed to complete in < 15 seconds on a typical Mac.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path


def _find_poppler() -> str | None:
    if shutil.which("pdftoppm"):
        return None
    for d in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]:
        if Path(d, "pdftoppm").exists():
            return d
    return None


def _render_page2(pdf_bytes: bytes, dpi: int = 250):
    """Return a PIL Image of page 2 at the given DPI, or None on failure."""
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(
            pdf_bytes, dpi=dpi,
            first_page=2, last_page=2,
            poppler_path=_find_poppler(),
        )
        return pages[0] if pages else None
    except Exception:
        return None


def _make_variants(crop):
    """
    Yield 5 targeted preprocessing variants for apostille sticker OCR.
    The rotation variant is important: it compensates for slightly skewed stickers
    and was the key to reading "06-May-2026" from pcceng1 samples.
    """
    from PIL import ImageFilter, ImageOps

    gray = ImageOps.grayscale(crop)
    gray = ImageOps.autocontrast(gray, cutoff=1)

    def up(img):
        return img.resize((img.width * 2, img.height * 2))

    # V1: plain gray — best for printed text (dates)
    yield up(gray)
    # V2: light threshold — suppresses rosette noise for dark stamp ink
    yield up(gray.point(lambda p: 255 if p > 130 else 0))
    # V3: medium threshold
    yield up(gray.point(lambda p: 255 if p > 150 else 0))
    # V4: sharpened + threshold — improves embossed text
    sharp = gray.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
    yield up(sharp.point(lambda p: 255 if p > 140 else 0))
    # V5: slight CCW rotation + threshold — corrects skewed stickers
    #     (empirically found to be necessary for reading dates from RPO Chandigarh stickers)
    rotated = gray.rotate(-3, expand=True, fillcolor=255)
    yield up(rotated.point(lambda p: 255 if p > 140 else 0))


def _ocr_stamp(img) -> str:
    """OCR optimised for stamp number pattern (0I/OI + digits).
    Tries PSM 6 (block) and PSM 7 (single line) — PSM 7 often works better when
    the stamp number appears on a single line within the sticker area.
    """
    try:
        import pytesseract
        wl = "-c tessedit_char_whitelist=0123456789OI "
        t6  = pytesseract.image_to_string(img, config=f"--oem 3 --psm 6 {wl}").strip()
        t7  = pytesseract.image_to_string(img, config=f"--oem 3 --psm 7 {wl}").strip()
        # Return whichever reads more non-whitespace chars
        return t6 if len(t6.replace(" ","")) >= len(t7.replace(" ","")) else t7
    except Exception:
        return ""


def _ocr_text(img) -> str:
    """General OCR for dates and full text (PSM 11 = sparse text)."""
    try:
        import pytesseract
        return pytesseract.image_to_string(img, config="--oem 3 --psm 11").strip()
    except Exception:
        return ""


# Indian MEA apostille stamps are exactly 7 digits after OI/0I.
# Strict 7-digit match avoids false positives from rosette noise.
# O and I within the digit run are normalised to 0 and 1 respectively.
_STAMP_RE = re.compile(r"\b([O0]I\s*[0-9OI]{7})\b", re.IGNORECASE)

_DATE_RES = [
    re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]20\d{2})\b"),
    re.compile(
        r"\b(\d{1,2}[\-\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*[\-\s]20\d{2})\b", re.IGNORECASE,
    ),
    re.compile(
        r"\bel\s+(\d{1,2}\s+de\s+[A-Za-záéíóú]+\s+de\s+20\d{2})\b",
        re.IGNORECASE,
    ),
    # Noisy "Date:" fallback — reconstruct DD-MM-YYYY from garbled OCR
    # e.g. "Date: . 247-906-2026" → "24/06/2026"
    re.compile(
        r"Date\s*[:\-]?\s*[^0-9\n]{0,6}([0-9]{1,2})[0-9]{0,2}[^0-9]{1,4}"
        r"[0-9]{0,2}([0-9]{2})[^0-9]{1,4}(20[0-9]{2})"
    ),
]


def _find_stamp(text: str) -> str:
    """Return only the 7-digit number (no OI/0I prefix) — the template
    now has the '0I ' label hardcoded before <<0I_NO>>."""
    m = _STAMP_RE.search(text)
    if not m:
        return ""
    raw = re.sub(r"\s+", "", m.group(1).upper())
    # Strip the 2-char OI/0I prefix
    digits = raw[2:]
    # Normalise OCR confusion chars in the digit portion: I→1, O→0
    digits = digits.replace("I", "1").replace("O", "0")
    if not digits.isdigit() or len(digits) != 7:
        return ""
    return digits


def _find_date(text: str) -> str:
    for pat in _DATE_RES[:-1]:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    # Noisy "Date:" fallback
    m = _DATE_RES[-1].search(text)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        try:
            if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
                return f"{int(day):02d}/{int(month):02d}/{year}"
        except ValueError:
            pass
    return ""


def extract_apostille_from_pdf(pdf_bytes: bytes) -> dict[str, str]:
    """
    Main entry point.  Renders page 2, crops to the apostille sticker area,
    applies 5 preprocessing variants, and returns a dict with keys
    'stamp_no' and 'apostille_date'.  Empty string = not found.

    Runs at most 10 OCR calls → typically completes in 5–25 seconds.
    Stops early the moment both values are found.
    """
    result: dict[str, str] = {"stamp_no": "", "apostille_date": ""}

    page = _render_page2(pdf_bytes, dpi=250)
    if page is None:
        return result

    w, h = page.size
    # Apostille sticker is in the bottom half of page 2.
    # Crop to bottom 55% full-width — covers all RPO layouts.
    crop = page.crop((0, int(h * 0.45), w, h))

    for variant in _make_variants(crop):
        # Stamp OCR pass (whitelist)
        if not result["stamp_no"]:
            result["stamp_no"] = _find_stamp(_ocr_stamp(variant))
        # Text OCR pass (date + any stamp visible in plain text)
        text = _ocr_text(variant)
        if not result["stamp_no"]:
            result["stamp_no"] = _find_stamp(text)
        if not result["apostille_date"]:
            result["apostille_date"] = _find_date(text)
        # Stop as soon as both are found
        if result["stamp_no"] and result["apostille_date"]:
            return result

    return result

