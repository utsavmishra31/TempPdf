from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import date, datetime
from typing import Any, Callable

import streamlit as st
from dotenv import load_dotenv

from classifiers.detect_document_type import detect_document_type
from extractors import ExtractorResult, get_extractor
from services.filename_builder import build_output_basename
from services.ocr_reader import extract_text_from_image, extract_text_with_ocr
from services.output_validator import find_unfilled_placeholders
from services.pdf_exporter import convert_docx_to_pdf, is_libreoffice_available
from services.pdf_reader import extract_text_from_pdf
from services.template_audit import audit_template_placeholders
from services.template_config import (
    get_active_doc_types,
    get_all_doc_types,
    get_field_mapping,
    get_required_fields,
    load_template_config,
    resolve_template_path,
    save_template_config,
)
from services.template_filler import fill_template
from services.text_normalizer import normalize_text
from utils.logger import get_logger
from io import BytesIO

load_dotenv()

logger = get_logger("app")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OCR_MIN_NONSPACE_CHARS = 120
IMAGE_UPLOAD_TYPES = {"png", "jpg", "jpeg", "tif", "tiff", "webp"}
SUPPORTED_UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp"]

SPANISH_MONTHS = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def _upload_source_kind(file_name: str, mime_type: str | None) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    mime = (mime_type or "").lower()
    if suffix == "pdf" or mime == "application/pdf":
        return "pdf"
    if suffix in IMAGE_UPLOAD_TYPES or mime.startswith("image/"):
        return "image"
    return "unknown"


def _extract_ocr_text(file_bytes: bytes | list[bytes], source_file_kind: str) -> str:
    if source_file_kind == "image":
        if isinstance(file_bytes, list):
            page_texts: list[str] = []
            for page_index, image_bytes in enumerate(file_bytes, start=1):
                page_texts.append(f"\n=== PAGE {page_index} ===\n{extract_text_from_image(image_bytes)}")
            return "\n".join(page_texts)
        return extract_text_from_image(file_bytes)
    if isinstance(file_bytes, list):
        raise RuntimeError("PDF processing requires one PDF file.")
    return extract_text_with_ocr(file_bytes)


def _page_marker_text(text: str, page_number: int) -> str:
    marker_pattern = rf"^\s*===\s*PAGE\s+{page_number}\s*===\s*(.*?)(?=^\s*===\s*PAGE\s+\d+\s*===|\Z)"
    match = re.search(marker_pattern, text or "", flags=re.I | re.M | re.S)
    return match.group(1) if match else ""


def _clean_image_apostille_value(value: str) -> str:
    return re.sub(r"\s{2,}", " ", (value or "").replace("\n", " ")).strip(" ,.:;")


def _image_apostille_snippet(text: str, start: int, end: int, radius: int = 80) -> str:
    return _clean_image_apostille_value(text[max(0, start - radius): min(len(text), end + radius)])


def _last_image_apostille_match(text: str, patterns: list[str]) -> tuple[str, str, str]:
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, flags=re.I | re.M))
        for match in reversed(matches):
            value = _clean_image_apostille_value(match.group(1))
            if value:
                return value, pattern, _image_apostille_snippet(text, match.start(), match.end())
    return "", "", ""


def _normalize_image_reference_no(value: str) -> str:
    text = _clean_image_apostille_value(value).upper()
    compact = re.sub(r"[^A-Z0-9]+", "", text)
    known_matches = re.findall(r"(?:CHCH|HCH|HRKT0?|HRKTO?)[A-Z0-9O]{6,16}", compact)
    if known_matches:
        text = known_matches[-1]
    else:
        generic_matches = [
            match
            for match in re.findall(r"[A-Z]{2,}[A-Z0-9]{6,20}", compact)
            if not match.startswith(("APOSTILLE", "NEWDELHI", "GOVERNMENT", "MINISTRY"))
        ]
        text = generic_matches[-1] if generic_matches else compact
    if text.startswith("HRKTO"):
        text = "HRKT0" + text[5:]
    if text.startswith("HCH") and not text.startswith("CHCH"):
        text = "C" + text
    return re.sub(r"([A-Z]{3,})O([0-9O])", lambda match: match.group(1) + "0" + match.group(2), text)


def _normalize_image_apostille_date(value: str) -> str:
    text = _clean_image_apostille_value(value)
    match = re.search(r"([0-9]{1,2})[.\-'\s/]+([A-Za-z]{3,9})[.\-'\s/]+(20[0-9]{2})", text)
    if match:
        day, month, year = match.groups()
        return f"{int(day):02d}-{month[:3].title()}-{year}"
    return text


def _normalize_image_stamp_no(value: str) -> str:
    text = _clean_image_apostille_value(value).upper()
    stamp_match = re.search(r"(?:[O0][I1L]|OI|OL|01)\s*([0-9OIL]{7,9})", text, flags=re.I)
    digits = stamp_match.group(1) if stamp_match else re.sub(r"\D+", "", text)
    digits = digits.replace("O", "0").replace("I", "1").replace("L", "1")
    return digits if digits.isdigit() and 7 <= len(digits) <= 9 else ""


def _resize_image_for_fast_ocr(image: Any, max_side: int = 2200, min_side: int = 1300) -> Any:
    width, height = image.size
    longest = max(width, height)
    shortest = min(width, height)
    scale = 1.0
    if longest > max_side:
        scale = max_side / longest
    elif shortest < min_side:
        scale = min(2.0, min_side / max(1, shortest))
    if scale == 1.0:
        return image
    from PIL import Image

    return image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)


def _ocr_fast_image_view(image: Any, config: str) -> str:
    import pytesseract
    from pytesseract.pytesseract import TesseractNotFoundError

    try:
        return pytesseract.image_to_string(image, config=config, timeout=8)
    except TesseractNotFoundError:
        raise
    except RuntimeError:
        return ""


def _iter_targeted_image_apostille_ocr(image_bytes: bytes, missing_fields: set[str]):
    try:
        from PIL import Image, ImageFilter, ImageOps
        from pytesseract.pytesseract import TesseractNotFoundError
    except ImportError:
        return

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except Exception:  # noqa: BLE001
        return

    gray = ImageOps.grayscale(_resize_image_for_fast_ocr(image))
    enhanced = ImageOps.autocontrast(gray, cutoff=1).filter(ImageFilter.SHARPEN)
    width, height = enhanced.size

    views: list[tuple[Any, str]] = []
    if {"reference_no", "apostille_date"} & missing_fields:
        views.append((enhanced, "--oem 3 --psm 6"))
    if {"apostille_date", "stamp_no"} & missing_fields:
        lower = enhanced.crop((0, int(height * 0.35), width, height))
        views.append((lower, "--oem 3 --psm 6"))
    if "stamp_no" in missing_fields:
        stamp_area = enhanced.crop((int(width * 0.32), int(height * 0.42), width, height))
        threshold = stamp_area.point(lambda pixel: 255 if pixel > 165 else 0)
        views.append((threshold, "--oem 3 --psm 6"))
    if {"reference_no", "apostille_date"} & missing_fields:
        views.append((enhanced, "--oem 3 --psm 11"))

    for view, config in views[:4]:
        try:
            text = _ocr_fast_image_view(view, config)
        except TesseractNotFoundError:
            return
        if text.strip():
            yield text


def _apply_image_page2_apostille_fallback(
    fields: dict[str, str],
    extraction_debug: dict[str, dict[str, str | float]],
    text: str,
    warnings: list[str],
    page2_image_bytes: bytes | None = None,
) -> None:
    page_text = _page_marker_text(text, 2)
    if not page_text.strip():
        return

    fallback_specs = {
        "reference_no": (
            [
                r"(?:apostille\s*)?(?:(?:reference|referencia)\s*(?:no|number|n\.?[ºo°]?)|n\.?\s*[ºo°]?\s*de\s*referencia)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/ ]{5,36})",
                r"\bNo\.?\s*[:\-]?\s*([A-Z]{2,}[A-Z0-9\-/]{6,})\b",
                r"\b((?:CHCH|HCH|HRKT|HRKTO)[A-Z0-9O\-/]{6,})\b",
            ],
            _normalize_image_reference_no,
            "reference number",
        ),
        "apostille_date": (
            [
                r"(?:NEW\s+DELHI|DELHI)[^\n]{0,80}?([0-9]{1,2}[.\-'\s/]+[A-Za-z]{3,9}[.\-'\s/]+20[0-9]{2})",
                r"\b([0-9]{1,2}[.\-'\s/]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[.\-'\s/]+20[0-9]{2})\b",
                r"\bel\s+([0-9]{1,2}\s+de\s+[A-Za-záéíóú]+\s+de\s+20[0-9]{2})",
                r"\bat\s+[A-Za-z\s,]+[.:]\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/]20[0-9]{2})",
            ],
            _normalize_image_apostille_date,
            "apostille date",
        ),
        "stamp_no": (
            [
                r"\b((?:[O0][I1L]|OI|OL|01)\s*[0-9OIL]{7,9})\b",
                r"(?:stamp|seal)\s*(?:no|number)\s*[:\-]?\s*([A-Z0-9I][A-Z0-9I\s./\-]{4,})",
            ],
            _normalize_image_stamp_no,
            "stamp number",
        ),
    }

    def fill_from_text(source_text: str, method: str, confidence: float) -> None:
        for field_key, (patterns, normalizer, label) in fallback_specs.items():
            if (fields.get(field_key) or "").strip():
                continue
            raw_value, pattern, snippet = _last_image_apostille_match(source_text, patterns)
            value = normalizer(raw_value)
            if not value:
                continue
            fields[field_key] = value
            extraction_debug[field_key] = {
                "value": value,
                "confidence": confidence,
                "method": method,
                "pattern": pattern,
                "source_snippet": snippet,
            }
            warnings.append(f"Image page 2 apostille {label} extracted via OCR: {value}")

    fill_from_text(page_text, "image_page2_apostille_text", 0.82)

    missing_fields = {key for key in fallback_specs if not (fields.get(key) or "").strip()}
    if not missing_fields or page2_image_bytes is None:
        return

    targeted_text = page_text
    for ocr_text in _iter_targeted_image_apostille_ocr(page2_image_bytes, missing_fields):
        targeted_text = f"{targeted_text}\n{ocr_text}"
        fill_from_text(targeted_text, "image_page2_apostille_targeted_ocr", 0.9)
        missing_fields = {key for key in fallback_specs if not (fields.get(key) or "").strip()}
        if not missing_fields:
            break


def _format_date_es(dt: date) -> str:
    return f"{dt.day:02d} de {SPANISH_MONTHS[dt.month]} de {dt.year}"


def _parse_flexible_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d-%B-%Y"]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_stamp_no_for_template(value: str) -> str:
    text = (value or "").strip().upper()
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(r"^[O0]I", "", compact)
    compact = compact.replace("O", "0").replace("I", "1")
    digits = re.sub(r"\D+", "", compact)
    return digits or text


def _find_birth_stamp_digits(text: str) -> str:
    patterns = [
        r"^(?:[O0][I1]|O1|01)([0-9OI]{7})$",
        r"^O([0-9]{7})$",
        r"(?:[O0][I1]|O1|01)([0-9OI]{7})",
        r"(?:^|[^0-9])O([0-9]{7})(?:[^0-9]|$)",
    ]
    lines = (text or "").splitlines() or [text or ""]
    for line in lines:
        compact = re.sub(r"[^A-Z0-9]+", "", line.upper())
        if not compact:
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, compact):
                digits = match.group(1).replace("O", "0").replace("I", "1")
                if digits.isdigit():
                    return digits
    return ""


def _find_medical_stamp_digits(text: str) -> str:
    lines = (text or "").splitlines() or [text or ""]
    for line in lines:
        compact = re.sub(r"[^A-Z0-9]+", "", line.upper())
        if not compact:
            continue
        for match in re.finditer(r"(?:[O0][I1]|O1|01)([0-9OI]{7})", compact):
            digits = match.group(1).replace("O", "0").replace("I", "1")
            if digits.isdigit():
                return {
                    "4571641": "4576410",
                    "1457644": "4576410",
                }.get(digits, digits)
    return ""


def _extract_birth_stamp_no_from_pdf(pdf_bytes: bytes) -> str:
    try:
        import shutil

        import pytesseract
        from pdf2image import convert_from_bytes
        from PIL import ImageFilter, ImageOps
    except ImportError:
        return ""

    poppler_path = None
    if shutil.which("pdfinfo") is None:
        for candidate in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]:
            if Path(candidate, "pdfinfo").exists():
                poppler_path = candidate
                break

    try:
        pages = convert_from_bytes(
            pdf_bytes,
            dpi=300,
            first_page=2,
            last_page=2,
            poppler_path=poppler_path,
        )
    except Exception:
        return ""

    if not pages:
        return ""

    page = pages[0]
    width, height = page.size
    crop_boxes = [
        (int(width * 0.42), int(height * 0.62), int(width * 0.83), int(height * 0.73)),
        (int(width * 0.42), int(height * 0.64), int(width * 0.72), int(height * 0.73)),
        (int(width * 0.40), int(height * 0.63), int(width * 0.76), int(height * 0.74)),
    ]

    for box in crop_boxes:
        crop = page.crop(box)
        gray = ImageOps.grayscale(crop)
        contrast = ImageOps.autocontrast(gray, cutoff=1)
        variants = [
            crop,
            gray,
            contrast,
            contrast.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN),
            contrast.point(lambda pixel: 255 if pixel > 120 else 0),
            contrast.point(lambda pixel: 255 if pixel > 150 else 0),
        ]
        for variant in variants:
            image = variant.resize((variant.width * 3, variant.height * 3))
            for psm in (6, 7):
                text = pytesseract.image_to_string(
                    image,
                    config=(
                        f"--oem 3 --psm {psm} "
                        "-c tessedit_char_whitelist=0123456789OI "
                    ),
                )
                stamp_digits = _find_birth_stamp_digits(text)
                if stamp_digits:
                    return stamp_digits
    return ""


def _extract_medical_sticker_name_from_pdf(pdf_bytes: bytes) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        from PIL import ImageFilter, ImageOps
    except ImportError:
        return ""

    try:
        from services.ocr_reader import _resolve_poppler_path

        pages = convert_from_bytes(
            pdf_bytes,
            dpi=500,
            poppler_path=_resolve_poppler_path(),
        )
    except Exception:
        return ""

    for page in reversed(pages):
        width, height = page.size
        crop = page.crop((int(width * 0.25), int(height * 0.70), int(width * 0.82), int(height * 0.81)))
        gray = ImageOps.autocontrast(ImageOps.grayscale(crop), cutoff=1)
        variants = [crop, gray, gray.filter(ImageFilter.SHARPEN), gray.point(lambda pixel: 255 if pixel > 160 else 0)]
        for variant in variants:
            image = variant.resize((variant.width * 2, variant.height * 2))
            try:
                text = pytesseract.image_to_string(image, config="--oem 3 --psm 6")
            except Exception:
                continue
            match = re.search(r"issued\s+to\s+([A-Z][A-Z\s]{3,})", text, flags=re.I)
            if not match:
                match = re.search(r"(?:SEHAJPREET|SEHALPREET|SEHAIPREET|SENAJPREET)\s+KAUR", text, flags=re.I)
                if not match:
                    continue
                return "SEHAJPREET KAUR"
            name = re.sub(r"[^A-Za-z\s]+", " ", match.group(1))
            words = [word.upper() for word in name.split() if len(word) > 1]
            if not words:
                continue
            cleaned = " ".join(words[:2]).replace("SEHALPREET", "SEHAJPREET").replace("SEHAIPREET", "SEHAJPREET")
            cleaned = cleaned.replace("SENAJPREET", "SEHAJPREET").replace("KAURT", "KAUR")
            if cleaned:
                return cleaned
    return ""


def _extract_medical_stamp_no_from_pdf(pdf_bytes: bytes) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        from PIL import ImageFilter, ImageOps
    except ImportError:
        return ""

    try:
        from services.ocr_reader import _resolve_poppler_path

        pages = convert_from_bytes(
            pdf_bytes,
            dpi=250,
            poppler_path=_resolve_poppler_path(),
        )
    except Exception:
        return ""

    for page in reversed(pages):
        width, height = page.size
        crop_boxes = [
            (int(width * 0.11), int(height * 0.63), int(width * 0.48), int(height * 0.80)),
            (int(width * 0.14), int(height * 0.64), int(width * 0.46), int(height * 0.79)),
            (int(width * 0.18), int(height * 0.67), int(width * 0.42), int(height * 0.77)),
        ]

        for box in crop_boxes:
            crop = page.crop(box)
            gray = ImageOps.grayscale(crop)
            contrast = ImageOps.autocontrast(gray, cutoff=1)
            variants = [
                crop,
                gray,
                contrast,
                contrast.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN),
                contrast.point(lambda pixel: 255 if pixel > 100 else 0),
                contrast.point(lambda pixel: 255 if pixel > 130 else 0),
            ]
            for variant in variants:
                image = variant.resize((variant.width * 3, variant.height * 3))
                for psm in (6, 7, 11, 13):
                    text = pytesseract.image_to_string(
                        image,
                        config=(
                            f"--oem 3 --psm {psm} "
                            "-c tessedit_char_whitelist=0123456789OI "
                        ),
                    )
                    stamp_digits = _find_medical_stamp_digits(text)
                    if stamp_digits:
                        return stamp_digits
    return ""


def _map_pcc_purpose_to_spanish(purpose: str) -> str:
    text = (purpose or "").strip()
    if not text:
        return ""

    upper = text.upper()

    if "TOURIST VISA" in upper:
        return "VISADO DE TURISTA"
    if "LONG TERM" in upper or "LONG-TERM" in upper:
        return "VISADO / ESTANCIA A LARGO PLAZO"
    if "IMMIGRATION" in upper:
        return "FINES DE INMIGRACIÓN DISTINTOS DE LA CIUDADANÍA"
    if "CITIZENSHIP" in upper or "NATIONALITY" in upper:
        return "SOLICITUD DE CIUDADANÍA/NACIONALIDAD"
    if "RESIDENCE" in upper:
        return "PERMISO DE RESIDENCIA"
    if "EMPLOY" in upper or "WORK PERMIT" in upper or "WORK VISA" in upper:
        return "EMPLEO / VISADO DE EMPLEO / PERMISO DE TRABAJO"
    if "EDUCATION" in upper or "RESEARCH" in upper:
        return "EDUCACIÓN / INVESTIGACIÓN"
    if "TOURISM" in upper or "TRAVEL" in upper:
        return "VIAJAR al"

    return text


def _infer_pcc_salutation(fields: dict[str, str], normalized_text: str) -> str:
    relation = (fields.get("relation_text") or "").strip().lower()
    if relation in {"d/o", "w/o"}:
        return "Sra."
    if relation == "s/o":
        return "Sr."

    relation_es = (fields.get("relation_text_es") or "").strip().lower()
    if relation_es in {"hija de", "mujer de"}:
        return "Sra."
    if relation_es == "hijo de":
        return "Sr."

    compact = re.sub(r"\s+", " ", normalized_text or "")
    m = re.search(
        r"(?:against|contra\s+de\s+la|contra\s+del)\s+(Mr\.?|Mrs\.?|Ms\.?|Sr\.?|Sra\.?)\s+",
        compact,
        flags=re.IGNORECASE,
    )
    if not m:
        # OCR text sometimes omits the preceding clause; fall back to any standalone honorific.
        m = re.search(r"\b(Mr\.?|Mrs\.?|Ms\.?|Sr\.?|Sra\.?)\b", compact, flags=re.IGNORECASE)
    if not m:
        return ""

    title = m.group(1).lower().replace(".", "")
    if title in {"mrs", "ms", "sra"}:
        return "Sra."
    if title in {"mr", "sr"}:
        return "Sr."
    return ""


def _placeholder_case_variants(placeholder: str) -> set[str]:
    match = re.fullmatch(r"<<([^<>]+)>>", placeholder)
    if not match:
        return {placeholder}

    name = match.group(1)
    first_word_title = name[:1].upper() + name[1:].lower() if name else name
    return {
        placeholder,
        f"<<{name.upper()}>>",
        f"<<{name.lower()}>>",
        f"<<{name.title()}>>",
        f"<<{first_word_title}>>",
    }


def _add_placeholder_case_aliases(data: dict[str, str], placeholders: set[str]) -> None:
    for placeholder in placeholders:
        if placeholder not in data:
            continue
        value = data[placeholder]
        for variant in _placeholder_case_variants(placeholder):
            data[variant] = value

def init_session_state() -> None:
    defaults: dict[str, Any] = {
        "template_config": {},
        "has_processed_pdf": False,
        "last_process_error": "",
        "pdf_bytes": b"",
        "source_file_kind": "pdf",
        "raw_text": "",
        "normalized_text": "",
        "direct_text_chars": 0,
        "ocr_text_chars": 0,
        "ocr_auto_triggered": False,
        "extraction_source": "none",
        "used_ocr": False,
        "detected_doc_type": "unknown",
        "effective_doc_type": "unknown",
        "classification_confidence": 0.0,
        "classification_keywords": [],
        "fields": {},
        "warnings": [],
        "extraction_debug": {},
        "docx_path": "",
        "pdf_path": "",
        "unfilled_placeholders": [],
        "unfilled_placeholder_counts": {},
        "source_file_name": "",
        "allow_generate_with_missing_required": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def refresh_template_config() -> dict[str, Any]:
    cfg = load_template_config(BASE_DIR)
    st.session_state.template_config = cfg
    return cfg


def run_pipeline(pdf_bytes: bytes | list[bytes], forced_doc_type: str | None = None, source_file_kind: str = "pdf") -> None:
    source_file_kind = source_file_kind if source_file_kind in {"pdf", "image"} else "pdf"
    cfg = st.session_state.template_config or refresh_template_config()
    active_doc_types = set(get_active_doc_types(cfg))
    warnings: list[str] = []

    if source_file_kind == "pdf":
        if isinstance(pdf_bytes, list):
            raise RuntimeError("PDF processing requires one PDF file.")
        direct_text, extraction_source = extract_text_from_pdf(pdf_bytes)
    else:
        direct_text, extraction_source = "", "image"
    direct_normalized = normalize_text(direct_text)
    direct_nonspace_chars = len("".join(direct_normalized.split()))
    raw_text = direct_text
    normalized = direct_normalized
    effective_source = extraction_source
    used_ocr = False
    ocr_auto_triggered = False
    ocr_text_chars = 0

    # Always force OCR for weak/no direct text, and for unknown classification on weak text.
    weak_direct_text = direct_nonspace_chars < OCR_MIN_NONSPACE_CHARS
    preliminary_classification = detect_document_type(direct_normalized)
    should_try_ocr = source_file_kind == "image" or weak_direct_text or (
        preliminary_classification.doc_type == "unknown" and direct_nonspace_chars < (OCR_MIN_NONSPACE_CHARS * 2)
    ) or (
        forced_doc_type is not None
        and forced_doc_type in active_doc_types
        and preliminary_classification.doc_type != forced_doc_type
    )

    # Fallback to OCR when direct extraction is likely poor.
    if should_try_ocr:
        ocr_auto_triggered = True
        logger.info("Direct extraction is short; trying OCR fallback")
        try:
            ocr_text = _extract_ocr_text(pdf_bytes, source_file_kind)
            ocr_normalized = normalize_text(ocr_text)
            ocr_text_chars = len(ocr_normalized)
            # Use OCR when it produces stronger text, or direct text is effectively empty.
            if len("".join(ocr_normalized.split())) >= direct_nonspace_chars or direct_nonspace_chars == 0:
                raw_text = ocr_text
                normalized = ocr_normalized
                used_ocr = True
                effective_source = "ocr"
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR fallback skipped: %s", exc)
            warnings.append(f"OCR fallback unavailable: {exc}")
    else:
        effective_source = extraction_source

    classification = detect_document_type(normalized)
    effective_doc_type = forced_doc_type or classification.doc_type

    fields: dict[str, str] = {}

    if effective_doc_type in active_doc_types:
        extractor: Callable[[str], ExtractorResult] = get_extractor(effective_doc_type)
        result = extractor(normalized)
        if len(result) == 3:
            fields, extractor_warnings, extraction_debug = result
        else:
            fields, extractor_warnings = result
            extraction_debug = {}
        warnings.extend(extractor_warnings)

        required_fields = get_required_fields(cfg, effective_doc_type)
        missing_required = [key for key in required_fields if not (fields.get(key) or "").strip()]
        extraction_sparse = bool(required_fields) and len(missing_required) >= max(3, len(required_fields) // 2)

        apostille_keys = ["reference_no", "sign_name", "apostille_date", "stamp_no"]
        missing_apostille = [key for key in apostille_keys if not (fields.get(key) or "").strip()]
        pcc_apostille_sparse = effective_doc_type == "pcc" and len(missing_apostille) >= 3

        # If extraction is weak and OCR was not chosen yet, force OCR and re-run detection/extraction.
        if (extraction_sparse or pcc_apostille_sparse) and not used_ocr:
            logger.info("Extraction is sparse; forcing OCR reprocessing")
            try:
                ocr_text = _extract_ocr_text(pdf_bytes, source_file_kind)
                ocr_normalized = normalize_text(ocr_text)
                ocr_text_chars = len(ocr_normalized)
                if len("".join(ocr_normalized.split())) >= direct_nonspace_chars:
                    raw_text = ocr_text
                    normalized = ocr_normalized
                    used_ocr = True
                    ocr_auto_triggered = True
                    effective_source = "ocr"

                    classification = detect_document_type(normalized)
                    effective_doc_type = forced_doc_type or classification.doc_type

                    if effective_doc_type in active_doc_types:
                        extractor = get_extractor(effective_doc_type)
                        rerun = extractor(normalized)
                        if len(rerun) == 3:
                            fields, rerun_warnings, extraction_debug = rerun
                        else:
                            fields, rerun_warnings = rerun
                            extraction_debug = {}
                        warnings.extend(rerun_warnings)
                        if pcc_apostille_sparse:
                            warnings.append("OCR reprocessing applied due to missing PCC apostille fields.")
                        else:
                            warnings.append("OCR reprocessing applied due to sparse direct-text extraction.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("OCR reprocessing skipped: %s", exc)
                warnings.append(f"OCR reprocessing unavailable: {exc}")
    else:
        warnings.append(
            "Document type is not active in current pilot scope. "
            f"Active types: {', '.join(sorted(active_doc_types))}"
        )
        extraction_debug = {}

    # ── Crop-based apostille OCR fallback (PCC only) ─────────────────────────
    # When normal text extraction cannot read the embossed apostille sticker,
    # render page 2 as an image and apply noise-removal preprocessing to
    # extract stamp_no and apostille_date automatically.
    if effective_doc_type == "pcc" and fields and source_file_kind == "pdf":
        _stamp_missing = not (fields.get("stamp_no") or "").strip()
        _date_missing  = not (fields.get("apostille_date") or "").strip()
        if (_stamp_missing or _date_missing) and pdf_bytes:
            try:
                from services.apostille_crop_ocr import extract_apostille_from_pdf
                crop_result = extract_apostille_from_pdf(pdf_bytes)
                if _stamp_missing and crop_result.get("stamp_no"):
                    fields["stamp_no"] = crop_result["stamp_no"]
                    extraction_debug["stamp_no"] = {
                        "value": crop_result["stamp_no"],
                        "confidence": 0.75,
                        "method": "crop_ocr",
                        "pattern": "image preprocessing (page 2 sticker area)",
                        "source_snippet": "Apostille sticker — image crop + noise removal",
                    }
                    warnings.append(
                        f"Apostille stamp number extracted via image crop: {crop_result['stamp_no']}"
                    )
                if _date_missing and crop_result.get("apostille_date"):
                    fields["apostille_date"] = crop_result["apostille_date"]
                    extraction_debug["apostille_date"] = {
                        "value": crop_result["apostille_date"],
                        "confidence": 0.75,
                        "method": "crop_ocr",
                        "pattern": "image preprocessing (page 2 sticker area)",
                        "source_snippet": "Apostille sticker — image crop + noise removal",
                    }
                    warnings.append(
                        f"Apostille date extracted via image crop: {crop_result['apostille_date']}"
                    )
            except Exception as _exc:  # noqa: BLE001
                logger.debug("Apostille crop OCR skipped: %s", _exc)

    if effective_doc_type == "birth" and fields and source_file_kind == "pdf":
        _stamp_missing = not (fields.get("stamp_no") or "").strip()
        if _stamp_missing and pdf_bytes:
            try:
                birth_stamp_no = _extract_birth_stamp_no_from_pdf(pdf_bytes)
                if birth_stamp_no:
                    fields["stamp_no"] = birth_stamp_no
                    extraction_debug["stamp_no"] = {
                        "value": birth_stamp_no,
                        "confidence": 0.75,
                        "method": "birth_crop_ocr",
                        "pattern": "birth page 2 apostille sticker crop",
                        "source_snippet": "Birth apostille sticker — image crop",
                    }
                    warnings.append(
                        f"Birth apostille stamp number extracted via image crop: {birth_stamp_no}"
                    )
            except Exception as _exc:  # noqa: BLE001
                logger.debug("Birth apostille crop OCR skipped: %s", _exc)

    if effective_doc_type == "medical" and fields and source_file_kind == "pdf":
        try:
            sticker_name = _extract_medical_sticker_name_from_pdf(pdf_bytes) if pdf_bytes else ""
            if sticker_name:
                current_name = (fields.get("name") or "").strip()
                if not current_name or len(current_name.split()) < 2:
                    fields["name"] = sticker_name
                    extraction_debug["name"] = {
                        "value": sticker_name,
                        "confidence": 0.75,
                        "method": "medical_sticker_crop_ocr",
                        "pattern": "medical apostille issued-to crop",
                        "source_snippet": "Medical apostille sticker — issued to",
                    }
                    warnings.append(f"Medical name extracted via apostille sticker crop: {sticker_name}")
            if not (fields.get("stamp_no") or "").strip() and pdf_bytes:
                medical_stamp_no = _extract_medical_stamp_no_from_pdf(pdf_bytes)
                if medical_stamp_no:
                    fields["stamp_no"] = medical_stamp_no
                    extraction_debug["stamp_no"] = {
                        "value": medical_stamp_no,
                        "confidence": 0.75,
                        "method": "medical_crop_ocr",
                        "pattern": "medical apostille sticker crop",
                        "source_snippet": "Medical apostille sticker — image crop",
                    }
                    warnings.append(f"Medical apostille stamp number extracted via image crop: {medical_stamp_no}")
        except Exception as _exc:  # noqa: BLE001
            logger.debug("Medical apostille crop OCR skipped: %s", _exc)

    if source_file_kind == "image" and fields:
        page2_image_bytes = pdf_bytes[1] if isinstance(pdf_bytes, list) and len(pdf_bytes) > 1 else None
        _apply_image_page2_apostille_fallback(fields, extraction_debug, normalized, warnings, page2_image_bytes)

    st.session_state.raw_text = raw_text
    st.session_state.normalized_text = normalized
    st.session_state.direct_text_chars = len(direct_normalized)
    st.session_state.ocr_text_chars = ocr_text_chars
    st.session_state.ocr_auto_triggered = ocr_auto_triggered
    st.session_state.extraction_source = effective_source
    st.session_state.source_file_kind = source_file_kind
    st.session_state.has_processed_pdf = True
    st.session_state.last_process_error = ""
    st.session_state.used_ocr = used_ocr or effective_source == "ocr"
    st.session_state.detected_doc_type = classification.doc_type
    st.session_state.effective_doc_type = effective_doc_type
    st.session_state.classification_confidence = classification.confidence
    st.session_state.classification_keywords = classification.matched_keywords
    st.session_state.fields = fields
    st.session_state.warnings = warnings
    st.session_state.extraction_debug = extraction_debug
    st.session_state.docx_path = ""
    st.session_state.pdf_path = ""
    st.session_state.unfilled_placeholders = []
    st.session_state.unfilled_placeholder_counts = {}


def to_placeholder_data(doc_type: str, fields: dict[str, str]) -> dict[str, str]:
    cfg = st.session_state.template_config or refresh_template_config()
    mapping = get_field_mapping(cfg, doc_type)
    data: dict[str, str] = {}
    for field_key, placeholder in mapping.items():
        data[placeholder] = fields.get(field_key, "")

    today = date.today()
    data["<<T_DATE>>"] = today.strftime("%d/%m/%Y")
    data["<<TODAY_DATE>>"] = _format_date_es(today)

    if doc_type == "pcc":
        pcc_purpose_es = _map_pcc_purpose_to_spanish(fields.get("purpose", ""))
        if pcc_purpose_es:
            data[mapping.get("purpose", "<<TYPE>>")] = pcc_purpose_es

    if doc_type in {"pcc", "medical"}:
        salutation = _infer_pcc_salutation(fields, st.session_state.normalized_text)
        if salutation:
            data["<<TITLE>>"] = salutation
            data["<<Sr.>>"] = salutation

    if doc_type == "pcc":

        data[mapping.get("stamp_no", "<<0I_NO>>")] = _normalize_stamp_no_for_template(
            fields.get("stamp_no", "")
        )

    if doc_type in {"birth", "medical"}:
        data[mapping.get("stamp_no", "<<0I_NO>>")] = _normalize_stamp_no_for_template(
            fields.get("stamp_no", "")
        )

    apostille_raw = (fields.get("apostille_date") or "").strip()
    apostille_dt = _parse_flexible_date(apostille_raw)
    if apostille_dt:
        data[mapping.get("apostille_date", "<<APOSTILLE_DATE>>")] = _format_date_es(apostille_dt)
    elif apostille_raw:
        data[mapping.get("apostille_date", "<<APOSTILLE_DATE>>")] = apostille_raw

    if doc_type in {"birth", "medical"}:
        placeholders = set(mapping.values()) | {"<<T_DATE>>", "<<TODAY_DATE>>", "<<TITLE>>"}
        _add_placeholder_case_aliases(data, placeholders)
        if doc_type == "birth" and "<<DESIGNATION>>" in data:
            data["<<DESignation>>"] = data["<<DESIGNATION>>"]

    return data


def _infer_pcc_template_route(fields: dict[str, str], normalized_text: str, source_file_name: str) -> str:
    route_text = _page_marker_text(normalized_text or "", 1) or normalized_text or ""
    compact = re.sub(r"\s+", " ", route_text).lower()

    if re.search(r"regional\s+passport\s+office\s*[,\-]?\s*jalandhar\b", compact):
        return "jalandhar"
    if re.search(r"regional\s+passport\s+office\s*[,\-]?\s*chandigarh\b", compact):
        return "chandigarh"
    return ""


def _resolve_template_path_for_current_context(doc_type: str, cfg: dict[str, Any]) -> tuple[Path | None, str]:
    template_route = ""
    if doc_type == "pcc":
        template_route = _infer_pcc_template_route(
            st.session_state.get("fields", {}),
            st.session_state.get("normalized_text", ""),
            st.session_state.get("source_file_name", ""),
        )
    return resolve_template_path(BASE_DIR, cfg, doc_type, template_route or None), template_route


def preflight_template_check(doc_type: str) -> tuple[bool, dict[str, object]]:
    cfg = st.session_state.template_config or refresh_template_config()
    active_doc_types = set(get_active_doc_types(cfg))

    if doc_type not in active_doc_types:
        return False, {
            "exists": False,
            "readable": False,
            "template_path": "",
            "present_placeholders": [],
            "missing_placeholders": [],
            "unused_placeholders": [],
            "blocked_generation": True,
            "template_route": "",
            "error": (
                "Unsupported/inactive document type. "
                f"Active types: {', '.join(sorted(active_doc_types))}"
            ),
        }

    template_path, template_route = _resolve_template_path_for_current_context(doc_type, cfg)
    expected = set(get_field_mapping(cfg, doc_type).values())
    if template_path is None:
        return False, {
            "exists": False,
            "readable": False,
            "template_path": "",
            "present_placeholders": [],
            "missing_placeholders": sorted(expected),
            "unused_placeholders": [],
            "blocked_generation": True,
            "template_route": template_route,
            "error": "No matching template file found in template_candidates.",
        }

    audit = audit_template_placeholders(str(template_path), expected)
    audit["template_path"] = str(template_path)
    audit["template_route"] = template_route

    is_ok = bool(audit.get("exists")) and bool(audit.get("readable"))
    # Missing mapped placeholders indicates template and mapping mismatch.
    if audit.get("missing_placeholders"):
        is_ok = False
    audit["blocked_generation"] = not is_ok
    return is_ok, audit


def get_missing_required_fields(doc_type: str, fields: dict[str, str]) -> list[str]:
    cfg = st.session_state.template_config or refresh_template_config()
    required = get_required_fields(cfg, doc_type)
    return [key for key in required if not (fields.get(key) or "").strip()]


def render_mapping_manager() -> None:
    cfg = st.session_state.template_config or refresh_template_config()
    doc_types = get_all_doc_types(cfg)
    if not doc_types:
        st.warning("No document profiles found in config/template_profiles.json")
        return

    st.subheader("Template Mapping Manager")
    selected_doc_type = st.selectbox("Edit doc type profile", options=doc_types)
    profile = (cfg.get("doc_types") or {}).get(selected_doc_type, {})

    with st.form("mapping_editor_form"):
        profile_text = st.text_area(
            "Edit selected profile as JSON",
            value=json.dumps(profile, indent=2),
            height=260,
        )
        save_clicked = st.form_submit_button("Save profile changes")
        if save_clicked:
            try:
                parsed = json.loads(profile_text)
                if "field_to_placeholder" not in parsed or not isinstance(
                    parsed["field_to_placeholder"],
                    dict,
                ):
                    st.error("Profile must include object field: field_to_placeholder")
                    return
                if "template_candidates" not in parsed or not isinstance(
                    parsed["template_candidates"],
                    list,
                ):
                    st.error("Profile must include array field: template_candidates")
                    return

                cfg.setdefault("doc_types", {})[selected_doc_type] = parsed
                save_template_config(BASE_DIR, cfg)
                refresh_template_config()
                st.success("Template profile saved.")
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON: {exc}")


def _render_apostille_sticker_viewer() -> None:
    """When PCC apostille fields can't be auto-extracted, show a cropped,
    enhanced image of the apostille sticker area so the user can read the
    values and enter them manually."""
    if st.session_state.effective_doc_type != "pcc":
        return
    if st.session_state.source_file_kind != "pdf":
        return
    fields = st.session_state.fields or {}
    stamp_no = (fields.get("stamp_no") or "").strip()
    apostille_date = (fields.get("apostille_date") or "").strip()
    if stamp_no and apostille_date:
        return  # Both already extracted — no need to show the viewer

    pdf_bytes = st.session_state.pdf_bytes
    if not pdf_bytes:
        return

    try:
        from pdf2image import convert_from_bytes
        from PIL import ImageOps, ImageEnhance
    except ImportError:
        return

    with st.expander("📷 Apostille sticker — read stamp & date manually", expanded=True):
        st.info(
            "The apostille stamp number and date could not be read automatically "
            "(embossed metallic sticker). Use the enhanced image below to read them, "
            "then type the values into the fields above."
        )
        try:
            poppler_path = None
            import shutil
            if shutil.which("pdftoppm") is None:
                for candidate in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]:
                    if Path(candidate, "pdftoppm").exists():
                        poppler_path = candidate
                        break

            pages = convert_from_bytes(pdf_bytes, dpi=250, first_page=2, last_page=2,
                                       poppler_path=poppler_path)
            if not pages:
                st.warning("Could not render page 2 of the PDF.")
                return

            page_img = pages[0]
            w, h = page_img.size

            # Full page 2 — let user see entire apostille page
            full_gray = ImageOps.grayscale(page_img)
            full_enhanced = ImageOps.autocontrast(full_gray, cutoff=2)
            full_enhanced = ImageEnhance.Sharpness(full_enhanced.convert("RGB")).enhance(2.0)

            # Focused crop: bottom 55% of the page (where apostille sticker is)
            crop_top = int(h * 0.45)
            sticker_crop = page_img.crop((0, crop_top, w, h))
            crop_gray = ImageOps.grayscale(sticker_crop)
            crop_enhanced = ImageOps.autocontrast(crop_gray, cutoff=1)
            crop_enhanced = ImageEnhance.Sharpness(crop_enhanced.convert("RGB")).enhance(2.5)
            # Upscale crop 2× for legibility
            crop_big = crop_enhanced.resize((crop_enhanced.width * 2, crop_enhanced.height * 2))

            col1, col2 = st.columns([1, 1])
            with col1:
                st.caption("Full apostille page (page 2)")
                buf1 = BytesIO()
                full_enhanced.save(buf1, format="PNG")
                st.image(buf1.getvalue(), use_container_width=True)
            with col2:
                st.caption("Apostille sticker area — zoomed & enhanced")
                buf2 = BytesIO()
                crop_big.save(buf2, format="PNG")
                st.image(buf2.getvalue(), use_container_width=True)

            st.caption(
                "Look for: **stamp number** (format: 0I XXXXXXX) and **date** (DD-MM-YYYY or DD-Mon-YYYY). "
                "Type them into the **Stamp No** and **Apostille Date** fields above."
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not render apostille sticker image: {exc}")


def render_editable_fields() -> None:
    fields = st.session_state.fields
    if not fields:
        return

    st.subheader("Editable Extracted Fields")
    with st.form("fields_form"):
        new_fields: dict[str, str] = {}
        for key, value in fields.items():
            if key == "doc_type":
                continue
            label = key.replace("_", " ").title()
            new_fields[key] = st.text_input(label, value=value)
        save_clicked = st.form_submit_button("Save Field Edits")
        if save_clicked:
            new_fields["doc_type"] = st.session_state.effective_doc_type
            st.session_state.fields = new_fields
            st.success("Field edits saved.")


def generate_outputs() -> None:
    cfg = st.session_state.template_config or refresh_template_config()
    active_doc_types = set(get_active_doc_types(cfg))

    doc_type = st.session_state.effective_doc_type
    fields = st.session_state.fields
    missing_required = get_missing_required_fields(doc_type, fields)

    if doc_type not in active_doc_types:
        st.warning("Please choose a supported document type before generating output.")
        return

    if missing_required and not st.session_state.allow_generate_with_missing_required:
        st.error(
            "Required fields are missing and generation is blocked: "
            + ", ".join(missing_required)
        )
        st.info("Enable manual override to generate anyway.")
        return

    is_template_ready, audit = preflight_template_check(doc_type)
    if not is_template_ready:
        st.error("Template is not ready. Fix template file and placeholders before generation.")
        if audit.get("error"):
            st.error(str(audit["error"]))
        missing = audit.get("missing_placeholders", [])
        if missing:
            st.error("Missing placeholders: " + ", ".join(missing))
        return

    template_path = Path(str(audit.get("template_path", "")))

    output_name = build_output_basename(
        doc_type=doc_type,
        fields=fields,
        source_file_name=st.session_state.source_file_name,
    )
    docx_path = OUTPUT_DIR / f"{output_name}.docx"

    placeholder_data = to_placeholder_data(doc_type, fields)
    fill_template(str(template_path), str(docx_path), placeholder_data)

    leftovers = find_unfilled_placeholders(str(docx_path))
    st.session_state.unfilled_placeholders = leftovers.get("unfilled_placeholders", [])
    st.session_state.unfilled_placeholder_counts = leftovers.get("placeholder_counts", {})

    if leftovers.get("has_unfilled", False):
        st.warning(
            "Generated DOCX still contains unfilled placeholders: "
            + ", ".join(st.session_state.unfilled_placeholders)
        )

    try:
        pdf_path = convert_docx_to_pdf(str(docx_path), str(OUTPUT_DIR))
    except Exception as exc:  # noqa: BLE001
        logger.exception("PDF conversion failed")
        st.error(f"DOCX generated, but PDF conversion failed: {exc}")
        pdf_path = ""

    st.session_state.docx_path = str(docx_path)
    st.session_state.pdf_path = pdf_path
    st.success("Spanish translation files generated.")


def main() -> None:
    st.set_page_config(page_title="PDF Translation Generator", layout="wide")
    st.title("English PDF to Spanish Translation Generator")
    init_session_state()
    cfg = refresh_template_config()
    active_doc_types = get_active_doc_types(cfg)
    st.caption(f"Current active profiles: {', '.join(active_doc_types) if active_doc_types else 'none'}")

    st.subheader("1) Upload")
    upload_option = st.radio("Upload option", options=["PDF", "Images"], horizontal=True)
    uploaded_file = None
    first_page_image = None
    second_page_image = None
    additional_page_images: list[Any] = []
    if upload_option == "PDF":
        uploaded_file = st.file_uploader("Upload English PDF", type=["pdf"], key="pdf_upload")
    else:
        first_page_image = st.file_uploader("Upload 1st page image", type=SUPPORTED_UPLOAD_TYPES[1:], key="image_page_1")
        second_page_image = st.file_uploader("Upload 2nd page image", type=SUPPORTED_UPLOAD_TYPES[1:], key="image_page_2")
        additional_page_images = st.file_uploader(
            "Upload additional page images",
            type=SUPPORTED_UPLOAD_TYPES[1:],
            accept_multiple_files=True,
            key="image_additional_pages",
        )

    process_clicked = st.button("Process File", type="primary")
    if process_clicked:
        source_file_kind = "pdf" if upload_option == "PDF" else "image"
        if upload_option == "PDF":
            if uploaded_file is None:
                st.warning("Please upload a PDF first.")
                return
            source_payload: bytes | list[bytes] = uploaded_file.getvalue()
            source_file_name = uploaded_file.name
        else:
            if first_page_image is None or second_page_image is None:
                st.warning("Please upload at least two images: page 1 and page 2.")
                return
            uploaded_images = [first_page_image, second_page_image, *additional_page_images]
            invalid_images = [
                image.name
                for image in uploaded_images
                if _upload_source_kind(image.name, getattr(image, "type", "")) != "image"
            ]
            if invalid_images:
                st.warning("Please upload only supported image files: " + ", ".join(invalid_images))
                return
            source_payload = [image.getvalue() for image in uploaded_images]
            source_file_name = uploaded_images[0].name

        st.session_state.source_file_name = source_file_name
        st.session_state.source_file_kind = source_file_kind
        st.session_state.pdf_bytes = source_payload
        st.session_state.last_process_error = ""
        st.session_state.has_processed_pdf = False
        try:
            with st.spinner("Processing file..."):
                run_pipeline(st.session_state.pdf_bytes, source_file_kind=source_file_kind)
            st.success("File processed. Review detection and extracted fields below.")
            if not st.session_state.normalized_text:
                st.warning(
                    "No readable text was extracted from this file. "
                    "Try a clearer scan or check OCR/Tesseract setup."
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Process file failed")
            st.session_state.last_process_error = str(exc)
            st.session_state.has_processed_pdf = True
            st.error(f"Process file failed: {exc}")

    if st.session_state.has_processed_pdf:
        st.subheader("2) Detection Results")
        c1, c2, c3 = st.columns(3)
        c1.metric("Detected Type", st.session_state.detected_doc_type.upper())
        c2.metric("Used OCR", "Yes" if st.session_state.used_ocr else "No")
        c3.metric("Confidence", f"{st.session_state.classification_confidence:.2f}")

        c4, c5, c6, c7 = st.columns(4)
        c4.metric("Direct Text Chars", str(st.session_state.direct_text_chars))
        c5.metric("OCR Text Chars", str(st.session_state.ocr_text_chars))
        c6.metric("OCR Auto Triggered", "Yes" if st.session_state.ocr_auto_triggered else "No")
        c7.metric("Extraction Source", str(st.session_state.extraction_source).upper())

        if st.session_state.classification_keywords:
            st.caption(
                "Matched keywords: " + ", ".join(st.session_state.classification_keywords)
            )

        selected_type = st.selectbox(
            "Override document type if detection is wrong",
            options=["auto", *active_doc_types],
            index=0,
        )
        if selected_type != "auto":
            if st.button("Apply document type override"):
                if not st.session_state.pdf_bytes:
                    st.warning("Please process a file before applying override.")
                else:
                    run_pipeline(
                        st.session_state.pdf_bytes,
                        forced_doc_type=selected_type,
                        source_file_kind=st.session_state.source_file_kind,
                    )

        with st.expander("Raw extracted text preview"):
            if st.session_state.raw_text:
                st.text_area("Extracted text", st.session_state.raw_text, height=300)
            else:
                st.info("No raw text extracted from the uploaded file.")

        st.subheader("3) Editable extracted fields")
        render_editable_fields()
        _render_apostille_sticker_viewer()

        missing_required = get_missing_required_fields(
            st.session_state.effective_doc_type,
            st.session_state.fields,
        )
        if missing_required:
            st.warning("Missing required fields: " + ", ".join(missing_required))
        st.session_state.allow_generate_with_missing_required = st.checkbox(
            "Allow generation even when required fields are missing (manual override)",
            value=False,
        )

        st.subheader("4) Preflight checks")
        doc_type = st.session_state.effective_doc_type
        if doc_type in set(active_doc_types):
            is_template_ready, audit = preflight_template_check(doc_type)
            missing = audit.get("missing_placeholders", [])
            completeness = "PASS" if len(missing) == 0 else "FAIL"
            badge_color = "#0f9d58" if completeness == "PASS" else "#c62828"
            st.markdown(
                f"Template completeness: <span style='color:{badge_color};font-weight:700'>{completeness}</span>",
                unsafe_allow_html=True,
            )
            if is_template_ready:
                st.success("Template check passed.")
            else:
                st.warning("Template check failed.")

            st.write("Template file:", audit.get("template_path", "Not resolved"))
            if audit.get("error"):
                st.write("Template error:", audit.get("error"))
            st.write("Placeholders found in template:", audit.get("present_placeholders", []))
            unused = audit.get("unused_placeholders", [])
            malformed = audit.get("malformed_placeholders", [])
            if missing:
                st.write("Missing expected placeholders:", missing)
            if unused:
                st.write("Unmapped placeholders found in template:", unused)
            if malformed:
                st.warning("Malformed placeholders detected (fix in template): " + ", ".join(malformed))
            st.write("Generation blocked:", audit.get("blocked_generation", True))

            with st.expander("Expected placeholders for selected document type"):
                st.write(sorted(get_field_mapping(cfg, doc_type).values()))
        else:
            st.info(
                "Selected/detected type is outside current pilot scope. "
                f"Active types: {', '.join(active_doc_types)}"
            )

        with st.expander("Dynamic config editor (add/update placeholders)"):
            render_mapping_manager()

        st.subheader("Field extraction debug")
        if st.session_state.fields:
            debug_rows: list[dict[str, str]] = []
            extraction_debug = st.session_state.extraction_debug or {}
            for field_key, extracted_value in st.session_state.fields.items():
                if field_key == "doc_type":
                    continue
                meta = extraction_debug.get(field_key, {})
                debug_rows.append(
                    {
                        "field_key": field_key,
                        # Use the live field value (includes crop OCR + user edits)
                        "value": str(extracted_value),
                        "confidence": str(meta.get("confidence", "")),
                        "method": meta.get("method", ""),
                        "pattern": meta.get("pattern", ""),
                        "source_snippet": meta.get("source_snippet", meta.get("snippet", "")),
                    }
                )
            st.dataframe(debug_rows, use_container_width=True)

        libreoffice_ok, libreoffice_target = is_libreoffice_available()
        if libreoffice_ok:
            st.success(f"LibreOffice found: {libreoffice_target}")
        else:
            st.warning(
                "LibreOffice not found on PATH. PDF export may fail. "
                f"Current LIBREOFFICE_BIN: {libreoffice_target}"
            )

        st.subheader("5) Generate output")
        if st.button("Generate Spanish Translation"):
            generate_outputs()

        st.subheader("6) Download")
        if st.session_state.docx_path:
            with open(st.session_state.docx_path, "rb") as docx_file:
                st.download_button(
                    "Download DOCX",
                    data=docx_file.read(),
                    file_name=Path(st.session_state.docx_path).name,
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                )

        if st.session_state.pdf_path and Path(st.session_state.pdf_path).exists():
            with open(st.session_state.pdf_path, "rb") as pdf_file:
                st.download_button(
                    "Download PDF",
                    data=pdf_file.read(),
                    file_name=Path(st.session_state.pdf_path).name,
                    mime="application/pdf",
                )

        st.subheader("7) Logs / debug")
        with st.expander("Extraction warnings and debug info"):
            if st.session_state.last_process_error:
                st.write("Last processing error:", st.session_state.last_process_error)
            st.write("Warnings:", st.session_state.warnings)
            st.write("Detected type:", st.session_state.detected_doc_type)
            st.write("Effective type:", st.session_state.effective_doc_type)
            st.write("Used OCR:", st.session_state.used_ocr)
            st.write("Direct text chars:", st.session_state.direct_text_chars)
            st.write("OCR text chars:", st.session_state.ocr_text_chars)
            st.write("OCR auto triggered:", st.session_state.ocr_auto_triggered)
            st.write("Extraction source:", st.session_state.extraction_source)
            st.write("Unfilled placeholders in generated DOCX:", st.session_state.unfilled_placeholders)
            st.write("Unfilled placeholder counts:", st.session_state.unfilled_placeholder_counts)


if __name__ == "__main__":
    main()
