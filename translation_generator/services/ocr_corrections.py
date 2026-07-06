"""
OCR Correction Dictionary
=========================
Provides:
  - A static dictionary of common OCR errors on Indian government documents
  - Learned corrections: user edits are persisted and applied automatically

Items implemented:
  #10  Learn OCR corrections from user field edits
  #11  Static OCR correction dictionary
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_CORRECTIONS_FILE = Path(__file__).resolve().parent.parent / "config" / "learned_corrections.json"

# ---------------------------------------------------------------------------
# Static correction dictionary (#11)
# Common OCR mis-reads on scanned government documents.
# Keys and values are case-sensitive whole-word replacements.
# ---------------------------------------------------------------------------
OCR_CORRECTIONS: dict[str, str] = {
    # Registration / government document labels
    "Reglswation": "Registration",
    "Reglstration": "Registration",
    "Registation": "Registration",
    # Marriage certificate labels
    "Memiage": "Marriage",
    "Mamnage": "Marriage",
    "Marirage": "Marriage",
    "Memiage": "Marriage",
    "Applicaton": "Application",
    "Solemization": "Solemnization",
    "Govemement": "Government",
    "Governement": "Government",
    "govemment": "government",
    "Certifieate": "Certificate",
    "Certifi cate": "Certificate",
    "Certlficate": "Certificate",
    "Certficate": "Certificate",
    "CERTIFCATE": "CERTIFICATE",
    "CERIIFICATE": "CERTIFICATE",
    "Reglstrar": "Registrar",
    "Registar": "Registrar",
    "REGLSTRAR": "REGISTRAR",
    "Passporl": "Passport",
    "PASSPORL": "PASSPORT",
    "POLLCE": "POLICE",
    "POUCE": "POLICE",
    "Poliee": "Police",
    # Address / location
    "ADDHESS": "ADDRESS",
    "ADDRES": "ADDRESS",
    "NATIONALTY": "NATIONALITY",
    "NATIONALIY": "NATIONALITY",
    "IDENTIFICATON": "IDENTIFICATION",
    "REGISIRATION": "REGISTRATION",
    "REGISTERATION": "REGISTRATION",
    # Titles / salutations
    "SHRl": "SHRI",
    "SHRi": "SHRI",
    "Shrl": "Shri",
    # Month names
    "Janaury": "January",
    "Feburary": "February",
    "Agust": "August",
    "Septmber": "September",
    "Ocober": "October",
    "Novembar": "November",
    "Decmber": "December",
    # Common OCR digit/letter swaps in context
    "l/o": "s/o",   # relation code: lowercase L → s
    "D/o": "D/O",
    "W/o": "W/O",
    "S/o": "S/O",
    # Apostille / stamp related
    "Apostile": "Apostille",
    "APOSTILE": "APOSTILLE",
    # Misc well-known institutions
    "Chandigarn": "Chandigarh",
    "Jalandher": "Jalandhar",
    "Ludhina": "Ludhiana",
    "Amritsar": "Amritsar",   # keep for whitelist
}


# Pre-compile patterns once at import time for performance.
_compiled_patterns: list[tuple[re.Pattern[str], str]] = []


def _compile() -> None:
    global _compiled_patterns  # noqa: PLW0603
    _compiled_patterns = []
    for wrong, correct in OCR_CORRECTIONS.items():
        try:
            pattern = re.compile(r"\b" + re.escape(wrong) + r"\b")
            _compiled_patterns.append((pattern, correct))
        except re.error:
            pass


_compile()


# ---------------------------------------------------------------------------
# Static corrections (#11)
# ---------------------------------------------------------------------------

def apply_corrections(text: str) -> str:
    """Apply the static OCR correction dictionary to *text*."""
    for pattern, replacement in _compiled_patterns:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Learned corrections (#10)
# ---------------------------------------------------------------------------

def load_learned_corrections() -> dict[str, str]:
    """Load user-taught corrections from ``config/learned_corrections.json``."""
    if not _CORRECTIONS_FILE.exists():
        return {}
    try:
        raw = _CORRECTIONS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    except Exception:  # noqa: BLE001
        return {}


def save_learned_correction(wrong: str, correct: str) -> None:
    """
    Persist a new learned correction.

    Skips if *wrong* equals *correct*, either is empty, or the wrong value is
    shorter than 4 characters (too generic to be a safe replacement).
    """
    wrong = wrong.strip()
    correct = correct.strip()
    if not wrong or not correct or wrong == correct or len(wrong) < 4:
        return

    current = load_learned_corrections()
    if current.get(wrong) == correct:
        return  # Already stored

    current[wrong] = correct
    _CORRECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CORRECTIONS_FILE.write_text(
        json.dumps(current, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def apply_learned_corrections(text: str) -> str:
    """Apply corrections learned from previous user field edits."""
    corrections = load_learned_corrections()
    for wrong, correct in corrections.items():
        if wrong and correct and wrong != correct:
            text = text.replace(wrong, correct)
    return text


def apply_all_corrections(text: str) -> str:
    """Apply both static dictionary and learned corrections."""
    text = apply_corrections(text)
    text = apply_learned_corrections(text)
    return text
