from __future__ import annotations

import io

import fitz
import pdfplumber


def _extract_with_pymupdf(pdf_bytes: bytes) -> str:
    text_parts: list[str] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text_parts.append(page.get_text("text"))
    return "\n".join(text_parts)


def _extract_with_pdfplumber(pdf_bytes: bytes) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    """Extract text from PDF using PyMuPDF first, then fallback to pdfplumber."""
    try:
        text = _extract_with_pymupdf(pdf_bytes)
        if text and len(text.strip()) > 20:
            return text, "pymupdf"
    except Exception:  # noqa: BLE001
        pass

    try:
        text = _extract_with_pdfplumber(pdf_bytes)
        return text, "pdfplumber"
    except Exception:  # noqa: BLE001
        return "", "none"
