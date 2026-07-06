"""
OCR Field Validator
===================
Validates extracted field values using format rules and cross-checks
values against each other for obvious inconsistencies.

Items implemented:
  #7  Validate extracted values (passport, dates, UID, reference, stamp)
  #8  Cross-check values (name consistency, date chronology)
"""
from __future__ import annotations

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Individual field validators (#7)
# Each returns (is_valid, corrected_value, note).
# ---------------------------------------------------------------------------

def validate_passport_no(value: str) -> tuple[bool, str, str]:
    """Indian passport: one letter followed by exactly 7 digits."""
    text = (value or "").strip().upper()
    clean = re.sub(r"[^A-Z0-9]", "", text)

    if re.fullmatch(r"[A-Z][0-9]{7}", clean):
        return True, clean, ""

    # Try auto-correcting common OCR swaps: O→0, I/l→1 in the numeric part
    if len(clean) == 8 and clean[0].isalpha():
        fixed_digits = (
            clean[1:]
            .replace("O", "0")
            .replace("I", "1")
            .replace("L", "1")
            .replace("S", "5")
            .replace("B", "8")
        )
        candidate = clean[0] + fixed_digits
        if re.fullmatch(r"[A-Z][0-9]{7}", candidate):
            return True, candidate, f"Auto-corrected OCR swap from '{text}'"

    if clean:
        return False, text, f"Expected letter + 7 digits, got '{text}'"
    return True, text, ""  # Empty is allowed (optional field)


def validate_date(value: str) -> tuple[bool, str, str]:
    """
    Accept common date formats; normalise to DD/MM/YYYY.
    Returns (True, normalised, "") on success.
    """
    text = (value or "").strip()
    if not text:
        return True, text, ""

    formats = [
        "%d/%m/%Y", "%d-%m-%Y",
        "%d/%m/%y", "%d-%m-%y",
        "%d-%b-%Y", "%d-%B-%Y",
        "%d %b %Y", "%d %B %Y",
        "%d.%m.%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if 1900 <= dt.year <= 2100:
                return True, dt.strftime("%d/%m/%Y"), ""
        except ValueError:
            continue

    return False, text, f"Unrecognised date format: '{text}'"


def validate_uid(value: str) -> tuple[bool, str, str]:
    """Aadhaar UID must be exactly 12 digits."""
    digits = re.sub(r"\D", "", (value or "").strip())
    if not digits:
        return True, digits, ""
    if len(digits) == 12:
        return True, digits, ""
    return False, digits, f"UID should be 12 digits, got {len(digits)}: '{value}'"


def validate_reference_no(value: str) -> tuple[bool, str, str]:
    """Apostille reference number: at least 8 alphanumeric characters."""
    text = (value or "").strip().upper()
    clean = re.sub(r"\s+", "", text)
    if not clean:
        return True, clean, ""
    alnum = re.sub(r"[^A-Z0-9]", "", clean)
    if len(alnum) >= 8:
        return True, alnum, ""
    return False, text, f"Reference number seems too short (got '{text}')"


def validate_stamp_no(value: str) -> tuple[bool, str, str]:
    """Apostille stamp number: 7–9 digits after stripping the OI prefix."""
    text = (value or "").strip().upper()
    if not text:
        return True, text, ""
    # Normalise O→0, I→1 after stripping the OI prefix
    clean = re.sub(r"^0?I\s*", "", text)  # remove leading OI / 0I
    digits = re.sub(r"\D", "", clean.replace("O", "0").replace("I", "1"))
    if 7 <= len(digits) <= 9 and digits.isdigit():
        return True, digits, ""
    if digits:
        return False, digits, f"Stamp number should be 7–9 digits, got {len(digits)}: '{value}'"
    return False, text, f"Could not parse stamp number from '{value}'"


def validate_file_number(value: str) -> tuple[bool, str, str]:
    """PCC file number: alphanumeric, at least 4 chars."""
    text = (value or "").strip()
    if not text:
        return True, text, ""
    clean = re.sub(r"\s+", "", text)
    if len(clean) >= 4:
        return True, clean, ""
    return False, text, f"File number seems too short: '{text}'"


# ---------------------------------------------------------------------------
# Field-to-validator mapping
# ---------------------------------------------------------------------------
_DATE_FIELDS = {
    "apostille_date", "date_of_birth", "marriage_date",
    "application_date", "register_date", "approv_date",
    "novio_birth_date", "novia_birth_date", "pcc_issuance_date",
}

_VALIDATORS: dict[str, object] = {
    "passport_no": validate_passport_no,
    "uid": validate_uid,
    "reference_no": validate_reference_no,
    "stamp_no": validate_stamp_no,
    "file_number": validate_file_number,
}
for _df in _DATE_FIELDS:
    _VALIDATORS[_df] = validate_date


# ---------------------------------------------------------------------------
# validate_fields (#7)
# ---------------------------------------------------------------------------

def validate_fields(
    fields: dict[str, str],
    doc_type: str,  # noqa: ARG001 — reserved for future doc-type-specific rules
) -> list[dict[str, str]]:
    """
    Validate all extracted fields.

    Returns a list of issue dicts::

        {"field": str, "value": str, "issue": str, "suggestion": str}
    """
    issues: list[dict[str, str]] = []

    for field_key, value in fields.items():
        if field_key == "doc_type" or not (value or "").strip():
            continue

        validator = _VALIDATORS.get(field_key)
        if validator is None:
            continue

        is_valid, corrected, note = validator(value)  # type: ignore[operator]
        if not is_valid:
            issues.append(
                {
                    "field": field_key,
                    "value": value,
                    "issue": note,
                    "suggestion": corrected if corrected and corrected != value else "",
                }
            )

    return issues


# ---------------------------------------------------------------------------
# cross_check_fields (#8)
# ---------------------------------------------------------------------------

def cross_check_fields(
    fields: dict[str, str],
    doc_type: str,
) -> list[str]:
    """
    Cross-check field values for obvious inconsistencies.

    Returns a list of human-readable warning strings.
    """
    warnings: list[str] = []

    def _similarity(a: str, b: str) -> float:
        """Character-set overlap similarity in [0, 1]."""
        a_set = set(a.upper().replace(" ", ""))
        b_set = set(b.upper().replace(" ", ""))
        if not a_set or not b_set:
            return 1.0
        return len(a_set & b_set) / max(len(a_set), len(b_set))

    # ── Name consistency ────────────────────────────────────────────────────
    # For PCC/birth/medical: a single "name" field; nothing to cross-check.
    # For marriage: novio_name and novia_name are different people — skip.
    if doc_type in {"pcc", "birth", "medical"}:
        name_fields = [
            k for k in ("name", "applicant_name", "patient_name")
            if (fields.get(k) or "").strip()
        ]
        if len(name_fields) >= 2:
            a_key, b_key = name_fields[0], name_fields[1]
            a_val, b_val = fields[a_key], fields[b_key]
            if len(a_val) > 3 and len(b_val) > 3 and _similarity(a_val, b_val) < 0.5:
                warnings.append(
                    f"Name mismatch: '{a_key}' is {a_val!r} but '{b_key}' is {b_val!r}. "
                    "Please verify — possible OCR error."
                )

    # ── Passport number format ──────────────────────────────────────────────
    passport = (fields.get("passport_no") or "").strip()
    if passport:
        is_valid, _, note = validate_passport_no(passport)
        if not is_valid:
            warnings.append(f"Passport number may be incorrect: {note}")

    # ── Date chronology ─────────────────────────────────────────────────────
    def _parse(raw: str) -> datetime | None:
        _, normalised, _ = validate_date(raw)
        try:
            return datetime.strptime(normalised, "%d/%m/%Y")
        except ValueError:
            return None

    dob_raw = (fields.get("date_of_birth") or "").strip()
    apostille_raw = (fields.get("apostille_date") or "").strip()

    if dob_raw and apostille_raw:
        dob = _parse(dob_raw)
        apostille_dt = _parse(apostille_raw)
        if dob and apostille_dt and dob > apostille_dt:
            warnings.append(
                f"Date of birth ({dob_raw}) is after the apostille date ({apostille_raw}). "
                "This is likely an OCR error."
            )

    marriage_raw = (fields.get("marriage_date") or "").strip()
    if dob_raw and marriage_raw:
        dob = _parse(dob_raw)
        marriage_dt = _parse(marriage_raw)
        if dob and marriage_dt and dob > marriage_dt:
            warnings.append(
                f"Date of birth ({dob_raw}) is after the marriage date ({marriage_raw}). "
                "Please verify."
            )

    # ── Stamp number length ─────────────────────────────────────────────────
    stamp = (fields.get("stamp_no") or "").strip()
    if stamp:
        is_valid, _, note = validate_stamp_no(stamp)
        if not is_valid:
            warnings.append(f"Stamp number may be incorrect: {note}")

    return warnings
