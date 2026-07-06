"""
OCR Enhancement Pipeline
========================
Provides image preprocessing variants, quality scoring, deskewing, denoising,
multi-PSM fallback, and confidence-filtered OCR.

Items implemented:
  #1  Auto-select best preprocessing variant
  #3  Confidence-filtered OCR via image_to_data()
  #4  Deskew pages
  #5  Remove scanner noise
  #6  Multi-PSM fallback
  #9  Document quality scoring
  #12 Region-specific OCR whitelists
"""
from __future__ import annotations

import os
import re
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat

# Set OCR_DESKEW=1 in .env to enable deskew (adds ~0.5s/page via numpy projections).
_DESKEW_ENABLED: bool = os.getenv("OCR_DESKEW", "").strip().lower() in {"1", "true", "yes"}

# ---------------------------------------------------------------------------
# Keyword sets for scoring OCR text quality per document type
# ---------------------------------------------------------------------------
_DOC_KEYWORDS: dict[str, list[str]] = {
    "birth": [
        "birth", "certificate", "name", "father", "mother",
        "date", "registrar", "registration", "born",
    ],
    "marriage": [
        "marriage", "certificate", "husband", "wife",
        "registrar", "date", "bride", "groom", "union",
    ],
    "pcc": [
        "police", "clearance", "certificate", "passport",
        "criminal", "issued", "file", "clearance",
    ],
    "medical": [
        "medical", "certificate", "fitness", "doctor",
        "patient", "issued", "health", "examination",
    ],
    "unknown": ["certificate", "issued", "date", "name", "government"],
}

_DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"
)
_PASSPORT_PATTERN = re.compile(r"\b[A-Z][0-9]{7}\b")
_STAMP_PATTERN = re.compile(r"\b0?I\s*[0-9]{7}\b")

# Whitelists per field type for region-specific OCR (#12)
FIELD_WHITELISTS: dict[str, str] = {
    "passport_no": "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "date": "-c tessedit_char_whitelist=0123456789-/. ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "stamp_no": "-c tessedit_char_whitelist=0123456789OI ",
    "reference_no": "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/. ",
    "uid": "-c tessedit_char_whitelist=0123456789 ",
}


# ---------------------------------------------------------------------------
# Quality assessment (#9)
# ---------------------------------------------------------------------------

def assess_image_quality(image: Image.Image) -> dict[str, Any]:
    """
    Assess image quality: blur, brightness, contrast.

    Returns a dict with numeric scores and an optional 'warning' string.
    """
    result: dict[str, Any] = {
        "blur_score": 0.0,
        "brightness": 0.0,
        "contrast": 0.0,
        "warning": "",
    }

    try:
        gray = image.convert("L") if image.mode != "L" else image
        stat = ImageStat.Stat(gray)

        brightness = stat.mean[0]
        contrast = stat.stddev[0]
        result["brightness"] = round(brightness, 1)
        result["contrast"] = round(contrast, 1)

        # Blur proxy: variance of edge-detected image (higher variance = sharper)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        blur_score = edge_stat.var[0]
        result["blur_score"] = round(blur_score, 2)

        issues: list[str] = []
        if brightness < 50:
            issues.append("image is very dark")
        elif brightness > 220:
            issues.append("overexposed / too bright")
        if contrast < 20:
            issues.append("low contrast")
        if blur_score < 8:
            issues.append("image appears blurry")

        if issues:
            result["warning"] = (
                "Image quality is low (" + ", ".join(issues) + "). "
                "OCR accuracy may be reduced — consider rescanning."
            )
    except Exception:  # noqa: BLE001
        pass

    return result


# ---------------------------------------------------------------------------
# Deskew (#4)
# ---------------------------------------------------------------------------

def deskew_image(image: Image.Image) -> Image.Image:
    """
    Correct minor scan skew (±10°) using horizontal projection variance.
    Falls back silently if numpy is unavailable.
    """
    try:
        import numpy as np
    except ImportError:
        return image

    try:
        gray = image.convert("L") if image.mode != "L" else image
        arr = np.array(gray)
        binary = (arr < 128).astype(np.uint8) * 255

        best_angle = 0.0
        best_score = -1.0

        # Test angles from -10° to +10° in 0.5° steps
        for tenth in range(-20, 21):
            angle = tenth * 0.5
            rotated = Image.fromarray(binary).rotate(angle, expand=False, fillcolor=0)
            row_sums = np.array(rotated).sum(axis=1).astype(float)
            score = float(row_sums.var())
            if score > best_score:
                best_score = score
                best_angle = angle

        if abs(best_angle) >= 0.5:
            return image.rotate(best_angle, expand=True, fillcolor=255)
        return image
    except Exception:  # noqa: BLE001
        return image


# ---------------------------------------------------------------------------
# Denoising (#5)
# ---------------------------------------------------------------------------

def denoise_image(image: Image.Image) -> Image.Image:
    """
    Remove scanner speckle noise via median filter (3×3).
    Approximates morphological opening with a min→max filter pass.
    """
    try:
        denoised = image.filter(ImageFilter.MedianFilter(size=3))
        # Morphological opening approximation: erode then dilate
        opened = denoised.filter(ImageFilter.MinFilter(size=3)).filter(ImageFilter.MaxFilter(size=3))
        return opened
    except Exception:  # noqa: BLE001
        return image


# ---------------------------------------------------------------------------
# Scoring (#1)
# ---------------------------------------------------------------------------

def score_ocr_text(text: str, doc_type: str = "unknown") -> float:
    """
    Score OCR output quality on a 0–10 scale.
    Higher = better. Used to select the best preprocessing variant.
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0
    lower = text.lower()

    # Word count contribution (capped)
    words = [w for w in text.split() if len(w) > 1]
    score += min(len(words) / 40.0, 2.0)

    # Keyword matches
    keywords = _DOC_KEYWORDS.get(doc_type, _DOC_KEYWORDS["unknown"])
    hits = sum(1 for kw in keywords if kw in lower)
    score += hits * 0.5

    # Valid date patterns
    dates = _DATE_PATTERN.findall(text)
    score += min(len(dates), 3) * 0.4

    # Passport number found
    if _PASSPORT_PATTERN.search(text):
        score += 0.8

    # Stamp number pattern
    if _STAMP_PATTERN.search(text):
        score += 0.5

    # Penalise garbage: very low alphanumeric ratio
    total_chars = len(text)
    if total_chars > 0:
        alnum_ratio = sum(1 for c in text if c.isalnum()) / total_chars
        if alnum_ratio < 0.15:
            score -= 2.0
        elif alnum_ratio < 0.25:
            score -= 0.5

    return max(score, 0.0)


# ---------------------------------------------------------------------------
# Image variant generation (#1)
# ---------------------------------------------------------------------------

def generate_image_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    """
    Generate preprocessing variants ordered best-first so callers stop early.

    Returns list of (name, image) pairs.
    """
    variants: list[tuple[str, Image.Image]] = []

    try:
        base = image.convert("RGB") if image.mode not in {"RGB", "L"} else image
        gray = ImageOps.grayscale(base)
        auto = ImageOps.autocontrast(gray, cutoff=1)

        # 1. Autocontrast — winner for most scanned government documents
        variants.append(("autocontrast", auto))

        # 2. Original — good fallback for already-clean scans
        variants.append(("original", base))

        # 3. Adaptive threshold — effective for high-contrast/stamp regions
        try:
            pixels = list(gray.getdata())
            mean_brightness = sum(pixels) / len(pixels)
            threshold_val = int(min(max(mean_brightness * 1.05, 80), 210))
            adaptive = auto.point(lambda p: 255 if p > threshold_val else 0)
            variants.append(("adaptive_threshold", adaptive))
        except Exception:  # noqa: BLE001
            pass

        # 4. Sharpen — helps blurry scans (heavier, tried last)
        sharp = auto.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
        variants.append(("sharpen", sharp))

    except Exception:  # noqa: BLE001
        if not variants:
            variants.append(("original", image))

    return variants


# ---------------------------------------------------------------------------
# Best-variant OCR (#1)
# ---------------------------------------------------------------------------

def best_variant_ocr(
    image: Image.Image,
    doc_type: str = "unknown",
    psm: int = 6,
    extra_config: str = "",
    early_stop_score: float = 3.0,
) -> tuple[str, str]:
    """
    Run OCR across preprocessing variants and return (best_text, variant_name).

    Stops as soon as a variant scores >= *early_stop_score* (default 3.0).
    Applies denoise first. Deskew is opt-in via the OCR_DESKEW env variable
    (disabled by default — it costs ~0.5 s/page on numpy rotations).
    """
    import pytesseract

    # Denoise is cheap (PIL C-level median filter). Deskew is expensive.
    processed = denoise_image(image)
    if _DESKEW_ENABLED:
        processed = deskew_image(processed)

    base_config = f"--oem 3 --psm {psm}"
    if extra_config:
        base_config = f"{base_config} {extra_config}"

    variants = generate_image_variants(processed)
    best_text = ""
    best_name = "original"
    best_score = -1.0

    for name, variant in variants:
        try:
            text = pytesseract.image_to_string(variant, config=base_config)
        except Exception:  # noqa: BLE001
            continue
        score = score_ocr_text(text, doc_type)
        if score > best_score:
            best_score = score
            best_text = text
            best_name = name
        if best_score >= early_stop_score:
            break

    return best_text, best_name


# ---------------------------------------------------------------------------
# Confidence-filtered OCR (#3)
# ---------------------------------------------------------------------------

def ocr_with_confidence_filter(
    image: Image.Image,
    config: str = "--oem 3 --psm 6",
    min_conf: int = 45,
) -> str:
    """
    Use image_to_data() and discard words with confidence < min_conf.
    Falls back to image_to_string() on failure.
    """
    import pytesseract

    try:
        data = pytesseract.image_to_data(
            image,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except Exception:  # noqa: BLE001
        return pytesseract.image_to_string(image, config=config)

    lines: list[str] = []
    current_line: list[str] = []
    prev_line_num = -1

    n = len(data["text"])
    for i in range(n):
        word: str = data["text"][i]
        conf: int = int(data["conf"][i])
        line_num: int = int(data["line_num"][i])

        if line_num != prev_line_num:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = []
            prev_line_num = line_num

        if word.strip() and conf >= min_conf:
            current_line.append(word)

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-PSM fallback (#6)
# ---------------------------------------------------------------------------

def multi_psm_ocr(
    image: Image.Image,
    doc_type: str = "unknown",
    psm_sequence: tuple[int, ...] = (6, 4, 11),
    min_score: float = 1.5,
) -> str:
    """
    Try PSM modes in order; return the first result that exceeds min_score.
    Falls back to the best result across all tried modes.
    """
    import pytesseract

    best_text = ""
    best_score = -1.0

    for psm in psm_sequence:
        try:
            text = pytesseract.image_to_string(image, config=f"--oem 3 --psm {psm}")
        except Exception:  # noqa: BLE001
            continue
        score = score_ocr_text(text, doc_type)
        if score > best_score:
            best_score = score
            best_text = text
        if best_score >= min_score:
            break

    return best_text


# ---------------------------------------------------------------------------
# Region-specific OCR (#12)
# ---------------------------------------------------------------------------

def targeted_field_ocr(
    image: Image.Image,
    field_type: str,
    psm: int = 7,
) -> str:
    """
    Run OCR on a pre-cropped image with a field-specific character whitelist.

    *field_type* must be one of: 'passport_no', 'date', 'stamp_no',
    'reference_no', 'uid'.
    """
    import pytesseract

    whitelist = FIELD_WHITELISTS.get(field_type, "")
    config = f"--oem 3 --psm {psm} {whitelist}".strip()

    try:
        return pytesseract.image_to_string(image, config=config).strip()
    except Exception:  # noqa: BLE001
        return ""
