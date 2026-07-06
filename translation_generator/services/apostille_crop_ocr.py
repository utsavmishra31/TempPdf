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


def _render_page2(pdf_bytes: bytes, dpi: int = 350):
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
    yield up(gray.point(lambda p: 255 if p > 120 else 0))
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
    """General OCR for dates and full text."""
    try:
        import pytesseract
        sparse = pytesseract.image_to_string(img, config="--oem 3 --psm 11").strip()
        block = pytesseract.image_to_string(img, config="--oem 3 --psm 6").strip()
        return "\n".join(part for part in [sparse, block] if part)
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
        r"\b([0-9ITl]{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*[\-\s]*20[0-9OIS]{2})\b", re.IGNORECASE,
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


def _find_reference_no(text: str) -> str:
    """Extract Indian MEA apostille reference number.
    Typically printed as 'N° XXXXXXXXXX' or a standalone 10-15 digit sequence.
    """
    # Labeled pattern first: N° / No. followed by digits
    m = re.search(
        r"(?:N[°º.]\s*|(?:reference\s*(?:no|n[°º])?\s*[:.\-]?\s*))([0-9]{8,15})",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    # Fallback: standalone 12–15 digit number (typical MEA reference length)
    candidates = re.findall(r"(?<![0-9])([0-9]{12,15})(?![0-9])", text)
    if candidates:
        preferred = [candidate for candidate in candidates if candidate.startswith("20")]
        candidate = max(preferred or candidates, key=len)
        if len(candidate) == 13 and candidate.startswith("20"):
            return candidate[:12]
        return candidate
    return ""


def _find_date(text: str) -> str:
    for pat in _DATE_RES[:-1]:
        m = pat.search(text)
        if m:
            normalized = _normalize_date_text(m.group(1))
            if normalized:
                return normalized
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


def _normalize_date_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip(" .,:;'\"()[]{}")
    text = re.sub(r"(?i)Noy", "Nov", text)
    text = re.sub(r"(?i)0ct", "Oct", text)
    compact = re.match(r"([0-9ITlO]{1,2})\s*([A-Za-z]{3,9})[\-\s]*(20[0-9OS]{2})", text)
    if compact:
        day, month, year = compact.groups()
        if "O" in day.upper():
            return ""
        day = day.replace("I", "1").replace("l", "1").replace("T", "1")
        year = year.replace("O", "0").replace("S", "5")
        try:
            if not 1 <= int(day) <= 31:
                return ""
        except ValueError:
            return ""
        return f"{int(day):02d}-{month[:3].title()}-{year}"
    return text


def _date_score(value: str) -> int:
    match = re.match(r"([0-9]{1,2})[-\s/][A-Za-z]{3,9}[-\s/](20[0-9]{2})", value or "")
    if not match:
        return 0
    day = int(match.group(1))
    score = 1
    if day > 1:
        score += 3
    if re.search(r"\b20[2-9][0-9]\b", value):
        score += 1
    return score


def _clean_person(value: str) -> str:
    words = re.findall(r"[A-Za-z]+", value or "")
    ignored = {
        "ATTESTATION", "ANESTATION", "SECTION", "OFFICER", "POTION", "PV", "DIVISION",
        "MINISTRY", "EXTERNAL", "AFFAIRS", "BEARS", "SEALSTAMP", "SEAL", "STAMP",
        "GOVERNMENT", "GOVE", "INDIA", "PUNJAB", "CHANDIGARH", "DELHI", "THE",
    }
    kept: list[str] = []
    for word in words:
        upper = word.upper()
        if len(upper) <= 2 or upper in ignored:
            continue
        kept.append(upper)
        if len(kept) >= 4:
            break
    return " ".join(kept) if len(kept) >= 2 else ""


def _find_apostille_sign(text: str) -> str:
    patterns = [
        r"\(([A-Za-z][A-Za-z\s]{3,30}?)\)[\s\S]{0,500}(?:Attestation|Anestation|Section\s*Officer|Potion\s+Otticer|PV\s*Division|Ministry\s+of\s+External)",
        r"([A-Za-z][A-Za-z\s]{3,30}?)\s*[\s\S]{0,160}(?:Section\s*Officer|Attestation|Anestation|PV\s*Division)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            person = _clean_person(match.group(1))
            if person:
                return person
    return ""


def extract_apostille_from_pdf(pdf_bytes: bytes) -> dict[str, str]:
    """
    Main entry point.  Renders page 2, crops to the apostille sticker area,
    applies 5 preprocessing variants, and returns a dict with keys
    'stamp_no', 'apostille_date', 'reference_no', and 'apostille_sign'.
    Empty string = not found.

    Runs at most 10 OCR calls → typically completes in 5–25 seconds.
    Stops early the moment stamp_no and apostille_date are found.
    """
    result: dict[str, str] = {"stamp_no": "", "apostille_date": "", "reference_no": "", "apostille_sign": ""}

    page = _render_page2(pdf_bytes, dpi=350)
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
        date_candidate = _find_date(text)
        if date_candidate and _date_score(date_candidate) >= _date_score(result["apostille_date"]):
            result["apostille_date"] = date_candidate
        if not result["reference_no"]:
            result["reference_no"] = _find_reference_no(text)
        if not result["apostille_sign"]:
            result["apostille_sign"] = _find_apostille_sign(text)
        # Stop as soon as stamp and date are found (reference is best-effort)
        if result["stamp_no"] and result["apostille_date"] and result["apostille_sign"]:
            return result

    return result

