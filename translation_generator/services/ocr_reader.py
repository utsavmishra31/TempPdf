from __future__ import annotations

import os
import shutil
from io import BytesIO
from pathlib import Path

import pytesseract
from pdf2image import convert_from_bytes
from pdf2image.exceptions import PDFInfoNotInstalledError
from PIL import Image, ImageFilter, ImageSequence
from pytesseract.pytesseract import TesseractNotFoundError

from .ocr_enhancer import best_variant_ocr, multi_psm_ocr, score_ocr_text, assess_image_quality
from .ocr_corrections import apply_all_corrections


def _resolve_poppler_path() -> str | None:
    """Resolve poppler binary directory for pdf2image.

    Returns None when poppler tools are already on PATH.
    Returns a directory path when found in common macOS Homebrew locations.
    """
    # If pdfinfo is globally available, no explicit path is needed.
    if shutil.which("pdfinfo"):
        return None

    env_path = os.getenv("POPPLER_PATH", "").strip()
    if env_path:
        env_dir = Path(env_path)
        # Allow either a directory path or direct pdfinfo binary path.
        if env_dir.is_dir() and (env_dir / "pdfinfo").exists():
            return str(env_dir)
        if env_dir.is_file() and env_dir.name == "pdfinfo":
            return str(env_dir.parent)

    for candidate in [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]:
        if (candidate / "pdfinfo").exists():
            return str(candidate)

    return None


def _configure_tesseract() -> None:
    tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def _extract_text_from_images(
    images: list[Image.Image],
    doc_type: str = "unknown",
) -> tuple[str, list[str]]:
    """
    Extract text from a list of page images using the multi-variant OCR pipeline.

    Returns (merged_text, quality_warnings).

    Pipeline per page:
      1. Assess image quality and emit a warning if quality is poor (#9).
      2. Run best_variant_ocr — tries 5 preprocessing variants, picks highest
         score (#1, #4, #5).
      3. If score is still weak, fall back to multi_psm_ocr (#6).
      4. Apply static + learned OCR corrections to the result (#10, #11).
    """
    text_parts: list[str] = []
    quality_warnings: list[str] = []

    try:
        for page_idx, image in enumerate(images, start=1):
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")

            # --- Quality check (#9) ----------------------------------------
            quality = assess_image_quality(image)
            if quality.get("warning"):
                quality_warnings.append(f"Page {page_idx}: {quality['warning']}")

            # --- Best-variant OCR (#1, #4, #5) --------------------------------
            page_text, _variant = best_variant_ocr(image, doc_type=doc_type, psm=6)

            # --- Multi-PSM fallback when result is weak (#6) ------------------
            if score_ocr_text(page_text, doc_type) < 1.5:
                fallback = multi_psm_ocr(
                    image,
                    doc_type=doc_type,
                    psm_sequence=(4, 11, 3),
                    min_score=1.5,
                )
                if score_ocr_text(fallback, doc_type) > score_ocr_text(page_text, doc_type):
                    page_text = fallback

            # --- OCR corrections (#10, #11) -----------------------------------
            page_text = apply_all_corrections(page_text)

            text_parts.append(page_text)

    except TesseractNotFoundError as exc:
        raise RuntimeError(
            "Tesseract OCR engine is required but was not found. Install it with "
            "'brew install tesseract'. If already installed, set TESSERACT_CMD to "
            "the full binary path (e.g. /opt/homebrew/bin/tesseract)."
        ) from exc

    return "\n".join(text_parts), quality_warnings


def extract_text_with_ocr(pdf_bytes: bytes, doc_type: str = "unknown") -> tuple[str, list[str]]:
    """Run OCR on all PDF pages and return (merged_text, quality_warnings)."""
    _configure_tesseract()
    poppler_path = _resolve_poppler_path()

    try:
        # 200 DPI is sufficient for cleanly printed A4 text and is ~4× faster
        # to render and process than 400 DPI, with no meaningful accuracy loss.
        images = convert_from_bytes(pdf_bytes, dpi=200, poppler_path=poppler_path)
    except PDFInfoNotInstalledError as exc:
        raise RuntimeError(
            "Poppler is required for OCR but was not found. Install it with 'brew install poppler'. "
            "If already installed, set POPPLER_PATH to the directory containing pdfinfo "
            "(for example /opt/homebrew/bin or /usr/local/bin)."
        ) from exc

    return _extract_text_from_images(images, doc_type=doc_type)


def extract_text_from_image(image_bytes: bytes, doc_type: str = "unknown") -> tuple[str, list[str]]:
    """Run OCR on an uploaded image and return (extracted_text, quality_warnings)."""
    _configure_tesseract()

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            images = [frame.copy() for frame in ImageSequence.Iterator(source)]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Uploaded image could not be opened for OCR.") from exc

    return _extract_text_from_images(images, doc_type=doc_type)
