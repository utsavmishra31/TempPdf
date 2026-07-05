from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytesseract
from pdf2image import convert_from_bytes
from pdf2image.exceptions import PDFInfoNotInstalledError
from PIL import ImageFilter
from pytesseract.pytesseract import TesseractNotFoundError


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


def extract_text_with_ocr(pdf_bytes: bytes) -> str:
    """Run OCR on all PDF pages and return merged text."""
    tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
    poppler_path = _resolve_poppler_path()

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        images = convert_from_bytes(pdf_bytes, dpi=400, poppler_path=poppler_path)
    except PDFInfoNotInstalledError as exc:
        raise RuntimeError(
            "Poppler is required for OCR but was not found. Install it with 'brew install poppler'. "
            "If already installed, set POPPLER_PATH to the directory containing pdfinfo "
            "(for example /opt/homebrew/bin or /usr/local/bin)."
        ) from exc

    text_parts: list[str] = []
    try:
        for image in images:
            # Run two passes: auto-layout raw and sharpened uniform-block.
            # For decorative apostille pages the raw pass captures reference codes
            # that sharpening loses; for regular text pages sharpening wins.
            raw_text = pytesseract.image_to_string(image, config="--oem 3 --psm 3")
            sharp_text = pytesseract.image_to_string(
                image.filter(ImageFilter.SHARPEN), config="--oem 3 --psm 6"
            )
            # Keep the pass that yielded more non-whitespace characters, then
            # append the other pass below it so all tokens are searchable.
            raw_nws = len("".join(raw_text.split()))
            sharp_nws = len("".join(sharp_text.split()))
            if raw_nws >= sharp_nws:
                page_text = raw_text + "\n" + sharp_text
            else:
                page_text = sharp_text + "\n" + raw_text
            text_parts.append(page_text)
    except TesseractNotFoundError as exc:
        raise RuntimeError(
            "Tesseract OCR engine is required but was not found. Install it with 'brew install tesseract'. "
            "If already installed, set TESSERACT_CMD to the full binary path "
            "(for example /opt/homebrew/bin/tesseract)."
        ) from exc
    return "\n".join(text_parts)
