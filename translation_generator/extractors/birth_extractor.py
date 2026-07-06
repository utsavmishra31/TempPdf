from __future__ import annotations

import re

from schemas.birth_schema import BirthSchema
from utils.regex_helpers import find_first_with_meta

SEX_MAP = {
    "male": "HOMBRE",
    "m": "HOMBRE",
    "female": "MUJER",
    "f": "MUJER",
    "other": "OTRO",
}


def _meta(value: str, method: str, pattern: str, snippet: str, confidence: float) -> dict[str, str | float]:
    return {
        "value": value,
        "confidence": confidence,
        "method": method,
        "pattern": pattern,
        "source_snippet": snippet,
    }


def _extract_with_meta(text: str, patterns: list[str], method: str = "regex") -> tuple[str, dict[str, str | float]]:
    value, info = find_first_with_meta(text, patterns)
    if value:
        return value.strip(), _meta(value.strip(), method, info.get("pattern", ""), info.get("snippet", ""), 0.9)
    return "", _meta("", "fallback", "", "", 0.0)


def _normalize_sex(raw: str) -> tuple[str, dict[str, str | float]]:
    key = (raw or "").strip().lower()
    if key in SEX_MAP:
        val = SEX_MAP[key]
        return val, _meta(val, "label_match", "SEX_MAP", raw, 0.95)
    return raw, _meta(raw, "fallback", "", raw, 0.3 if raw else 0.0)


def _clean_text(value: str) -> str:
    return re.sub(r"\s{2,}", " ", (value or "").replace("\n", " ")).strip(" ,.")


def _clean_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9\-/]+", "", _clean_text(value).upper())


def _clean_birth_serial_no(value: str) -> str:
    raw = _clean_text(value).upper()
    folded = raw.replace("€", "E").replace("§", "S").replace("$", "S")
    compact = re.sub(r"[^A-Z0-9]+", "", folded)

    match = re.search(r"ES([0-9]{6,})", compact)
    if match:
        return "ES" + match.group(1)

    match = re.search(r"E[5S]([0-9]{6,})", compact)
    if match:
        return "ES" + match.group(1)

    # OCR frequently misreads digit 5 as letter S in the numeric portion.
    # Normalise S→5 (and O→0, I→1) within the digit run after the ES prefix.
    if compact.startswith(("ES", "E5")):
        prefix = "ES"
        rest = compact[2:].replace("S", "5").replace("O", "0").replace("I", "1")
        match = re.search(r"ES([0-9]{6,})", prefix + rest)
        if match:
            return "ES" + match.group(1)

    digits = re.sub(r"\D+", "", compact)
    if len(digits) == 8 and re.search(r"[^0-9]\s*[0-9]", raw):
        return "ES" + digits
    if len(digits) == 9 and digits.startswith("5"):
        return "ES" + digits[1:]

    return _clean_identifier(value)


def _clean_birth_address(value: str, tehsil: str, district: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.sub(r"^\S+\s*/\s*", "", cleaned)
    cleaned = re.sub(r"\bP\.\s*O\b", "P.O", cleaned, flags=re.I)
    cleaned = re.sub(r"\bTeh\.\s+Teh\.", "Teh.", cleaned, flags=re.I)
    cleaned = _clean_text(cleaned)

    if tehsil and district:
        tail = f"Teh. {tehsil} Distt. {district}"
        tail_pattern = rf"\bTeh\.\s*{re.escape(tehsil)}\s+Distt\.\s*{re.escape(district)}\b.*$"
        prefix = _clean_text(re.sub(tail_pattern, "", cleaned, flags=re.I))
        if prefix and ("teh" not in prefix.lower() or "dist" not in prefix.lower()):
            cleaned = f"{prefix} {tail}"
    return cleaned


def _clean_person_name(value: str) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    # Keep only alpha words and return the most likely trailing proper-name chunk.
    words = re.findall(r"[A-Za-z]+", raw)
    words = [w for w in words if len(w) > 2 or w.isupper()]
    if not words:
        return ""
    # Prefer trailing 2-4 title-case/all-caps words.
    candidates: list[str] = []
    for size in (4, 3, 2):
        if len(words) < size:
            continue
        chunk = words[-size:]
        if all(len(w) >= 2 for w in chunk):
            candidates.append(" ".join(chunk))
    cleaned = candidates[-1] if candidates else " ".join(words[-2:])
    # Guard against OCR/template artifacts like trailing angle brackets.
    cleaned = re.sub(r"[<>]+", "", cleaned).strip()
    return cleaned


def extract_fields(text: str) -> tuple[dict[str, str], list[str], dict[str, dict[str, str | float]]]:
    normalized = (text or "").replace("|", " ")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    patterns: dict[str, list[str]] = {
        "register_no": [
            r"(?:register(?:ed)?\s*no|registration\s*(?:no|number)|reg(?:istration)?\s*no|Regls?w?ation\s+[Nn]o)"
            r"\s*[:\-]?\s*([A-Z0-9\-/]+)",
            r"(BU/[A-Z]{1,3}/\d{2}/\d{8,})",
        ],
        "serial_no": [
            r"document\s*s(?:r|erial)\.?\s*(?:no|number)\s*[:\-]\s*([^\n|]+)",
            r"[Dd]ocument\s+[^A-Za-z\n]{0,12}[Nn]o\.?\s*[:\-]?\s*([A-Z]{2}[0-9A-Z]{7,})",
            r"(?:serial\s*(?:no|number)|document\s*serial\s*(?:no|number)|n\.?\s*de\s*serie\s*del\s*documento)\s*[:\-]?\s*([A-Z0-9\-/]+)",
            r"(?:certificate\s*no|cert\s*no)\s*[:\-]?\s*([A-Z0-9\-/]+)",
            # Bare ES-prefixed serial number as last resort
            r"\b(ES[0-9]{7,})\b",
        ],
        "place": [
            r"\blocation\s*[:\-]\s*([A-Za-z][A-Za-z ]+)",
            r"(?:office\s*place|place\s*of\s*registration)\s*[:\-]?\s*([A-Za-z0-9,\s]+)",
        ],
        "tehsil": [r"tehsil\s*[:\-]?\s*([A-Za-z\s]+)"],
        "district": [r"district\s*[:\-]?\s*([A-Za-z\s]+?)(?:\s+of\b|[,\.\n]|$)"],
        "year": [r"(?:for\s*the\s*year|year)\s*[:\-]?\s*([0-9]{4})"],
        "child_name": [
            r"(?:name\s*of\s*child|child\s*name|name\s*of\s*the\s*child)\s*[:\-]?\s*(?:[^\n/]+/)?\s*([A-Za-z][A-Za-z ]{2,})",
            r"\b/name\s*[:\-]?\s*(?:[^\n/]+/)?\s*([A-Za-z][A-Za-z ]{2,})",
        ],
        "sex": [
            r"\bsex\b\s*[:\-]?\s*(?:[^\n]*?\b)?(male|female|other)\b",
            r"\bgender\b\s*[:\-]?\s*(?:[^\n]*?\b)?(male|female|other)\b",
            r"\bgender\s*of\s*child\b\s*[:\-]?\s*(?:[^\n]*?\b)?(male|female|other)\b",
        ],
        "father_name": [
            r"father'?s?\s*name\s*[:\-]?\s*(?:[^\n/]+/)?\s*([A-Za-z][A-Za-z ]{2,})",
            r"\bS\/O\b\s*([A-Za-z ]{3,})",
        ],
        "grandfather_name": [
            r"grand\s*father'?s?\s*name\s*[:\-]?\s*(?:[^\n/]+/)?\s*([A-Za-z][A-Za-z ]{2,})",
            r"(?:grand\s*father|grandfather)\s*[:\-]?\s*([A-Za-z ]{3,})",
        ],
        "mother_name": [
            r"mother'?s?\s*name\s*[:\-]?\s*(?:[^\n/]+/)?\s*([A-Za-z][A-Za-z ]{2,})",
            r"\bW\/O\b\s*([A-Za-z ]{3,})",
        ],
        "birth_date": [
            r"(?:birth\s*date|date\s*of\s*birth)\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
            # OCR sometimes merges DD and MM: "1903/2024" → treat as DDMM/YYYY
            r"(?:birth\s*date|date\s*of\s*birth)\s*[:\-]?\s*([0-9]{4}/[0-9]{4})",
        ],
        "birth_place": [
            r"(Tagore\s+Hospital\s+Sha\s*h?kot)",
            r"(?:birth\s*place|place\s*of\s*birth|hospital\s*name)\s*[:\-]?\s*([A-Za-z0-9,()\-\s]{3,})",
        ],
        "reg_date": [
            r"registration\s*(?:date)?\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
            r"\breg(?:istration)?\s*date\b\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
        ],
        "address": [r"address\s*[:\-]?\s*([A-Za-z0-9,\-\s]+)"],
        "permanent_address": [r"permanent\s*address\s*[:\-]?\s*([A-Za-z0-9,\-\s]+)"],
        "issue_date": [
            r"(?:issue\s*date|print\s*date|date\s*of\s*issue|date\s*of\s*issuance)\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
            r"\b([0-9]{1,2}/[0-9]{1,2}/20[0-9]{2})\b",
        ],
        "print_date": [
            r"print\s*(?:date|data)\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
        ],
        "signature_name": [
            r"signed\s*by\s*[:\-]?\s*([A-Za-z\s.]+)",
        ],
        "signature_date": [r"(?:sign\s*date|signature\s*date|date)\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"],
        "location": [
            r"location\s*[:\-]?\s*([A-Za-z\s]+)",
            r"\b(Mc\s+Shahkot)\b",
        ],
        "designation": [
            r"designation\s*[:\-]?\s*[^A-Za-z\n]{0,12}([A-Za-z][A-Za-z() ]+)",
            r"(Local\s+Registrar\s*\(EOMC\))",
        ],
        "reference_no": [
            r"(?:apostille\s*)?reference\s*(?:no|number)\s*[:\-]?\s*([A-Z0-9\-/]+)",
            r"\bNo\.\s*([A-Z]{3,}[A-Z0-9\-/]+)\b",
        ],
        "apostille_sign": [
            r"(?:signatory|signed\s*by)\s*[:\-]?\s*([A-Za-z\s.]+)",
            r"has\s+been\s+signed\s+by\s+([A-Za-z\s.]+)",
        ],
        "signed_by": [
            r"[fh]as\s+been\s+signed\s+by\s*[^A-Za-z\n]{0,20}([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)",
            r"has\s+been\s+signed\s+by\s+([A-Za-z\s.]+)",
        ],
        "apostille_date": [
            r"NEW\s+DELHI,\s*INDIA[^\n]{0,45}?([0-9]{1,2}-[A-Za-z]{3,9}-20[0-9]{2})",
            r"at\s+[A-Za-z\s,]+[.:]\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
            r"at\s+[A-Za-z\s,]+[.:]\s*([0-9]{1,2}-[A-Za-z]{3,9}-[0-9]{4})",
        ],
        "stamp_no": [
            r"(?:stamp|seal)\s*(?:no|number)\s*[:\-]?\s*([A-Z0-9\-/ ]+)",
            r"\b(0I\s*[0-9]{7})\b",
        ],
    }

    values: dict[str, str] = {}
    debug: dict[str, dict[str, str | float]] = {}
    for key, key_patterns in patterns.items():
        value, meta = _extract_with_meta(normalized, key_patterns)
        values[key] = _clean_text(value)
        debug[key] = meta

    def _override_value(key: str, value: str, method: str, pattern: str, snippet: str, confidence: float) -> None:
        cleaned = _clean_text(value)
        if cleaned:
            values[key] = cleaned
            debug[key] = _meta(cleaned, method, pattern, snippet, confidence)

    compact_normalized = re.sub(r"\s+", " ", normalized)

    if values.get("serial_no"):
        serial_no = _clean_birth_serial_no(values["serial_no"])
        if serial_no:
            _override_value("serial_no", serial_no, "regex", "_clean_birth_serial_no", values["serial_no"], 0.9)

    # Repair OCR-merged birth date "DDMM/YYYY" → "DD/MM/YYYY"
    if values.get("birth_date") and re.fullmatch(r"[0-9]{4}/[0-9]{4}", values["birth_date"]):
        raw = values["birth_date"]  # e.g. "1903/2024"
        dd, mm, yyyy = raw[:2], raw[2:4], raw[5:]
        try:
            from datetime import date
            date(int(yyyy), int(mm), int(dd))  # validate
            fixed = f"{dd}/{mm}/{yyyy}"
            _override_value("birth_date", fixed, "repair", "DDMM/YYYY→DD/MM/YYYY", raw, 0.8)
        except (ValueError, IndexError):
            pass

    # serial_no line-level override: search each line for "Document" + ES number.
    # More robust than full-text regex because it's confined to a single line,
    # preventing cross-line false matches (e.g. from footer text).
    for _line in text.splitlines():
        _es_m = re.search(r"[Dd]ocument[^\n]{0,30}(ES[0-9A-Z]{7,})", _line, re.IGNORECASE)
        if _es_m:
            _cleaned_serial = _clean_birth_serial_no(_es_m.group(1))
            if _cleaned_serial and _cleaned_serial.startswith("ES"):
                _override_value("serial_no", _cleaned_serial, "ocr_line", "Document+ES", _es_m.group(0), 0.92)
            break

    if values.get("district"):
        district = re.sub(r"\s+of\b.*$", "", values["district"], flags=re.I).strip(" ,.")
        _override_value("district", district, "regex", "district_trim", values["district"], 0.9)

    hospital_pattern = r"\b(Tagore\s+Hospital\s+Sha\s*h?kot)\b"
    hospital_match = re.search(hospital_pattern, normalized, flags=re.I)
    if hospital_match:
        birth_place = re.sub(r"Sha\s*h?kot", "Shahkot", _clean_text(hospital_match.group(1)), flags=re.I)
        _override_value("birth_place", birth_place, "ocr_line", hospital_pattern, hospital_match.group(0), 0.95)

    issue_pattern = r"Date\s+of\s+Issuance\s*[:\-]\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"
    issue_match = re.search(issue_pattern, normalized, flags=re.I)
    if issue_match:
        _override_value("issue_date", issue_match.group(1), "ocr_line", issue_pattern, issue_match.group(0), 0.95)

    apostille_date_pattern = r"NEW\s+DELHI,\s*INDIA[^\n]{0,45}?([0-9]{1,2}-[A-Za-z]{3,9}-20[0-9]{2})"
    apostille_date_match = re.search(apostille_date_pattern, normalized, flags=re.I)
    if apostille_date_match:
        _override_value("apostille_date", apostille_date_match.group(1), "ocr_line", apostille_date_pattern, apostille_date_match.group(0), 0.95)

    signed_by_pattern = r"[fh]as\s+been\s+signed\s+by\s*[^A-Za-z\n]{0,20}([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)"
    signed_by_match = re.search(signed_by_pattern, normalized, flags=re.I)
    if signed_by_match:
        _override_value("signed_by", _clean_person_name(signed_by_match.group(1)), "ocr_line", signed_by_pattern, signed_by_match.group(0), 0.9)

    designation_pattern = r"Designation\s*[:\-]?\s*[^A-Za-z\n]{0,12}(Local\s+Registrar\s*\(EOMC\))"
    designation_match = re.search(designation_pattern, normalized, flags=re.I)
    if designation_match:
        _override_value("designation", designation_match.group(1), "ocr_line", designation_pattern, designation_match.group(0), 0.95)

    address_pattern = r"Address of Parents.*?Permanent Address of Parent\s*s\s*(.*?)\s*Date of Issuance"
    address_match = re.search(address_pattern, compact_normalized, flags=re.I)
    if address_match:
        address_body = address_match.group(1)
        address_parts = re.split(r"\s+\+\s*#?\S+\s*/\s*", address_body, maxsplit=1)
        birth_address = _clean_birth_address(address_parts[0], values.get("tehsil", ""), values.get("district", ""))
        permanent_address = _clean_birth_address(
            address_parts[1] if len(address_parts) > 1 else address_parts[0],
            values.get("tehsil", ""),
            values.get("district", ""),
        )
        _override_value("address", birth_address, "ocr_block", address_pattern, address_body, 0.9)
        _override_value("permanent_address", permanent_address, "ocr_block", address_pattern, address_body, 0.9)

    def _line_value(line_pattern: str, value_pattern: str) -> str:
        for line in (text or "").splitlines():
            if re.search(line_pattern, line, flags=re.I):
                m = re.search(value_pattern, line, flags=re.I)
                if m:
                    return _clean_text(m.group(1))
        return ""

    # Prefer exact line parsing for key person fields in OCR-heavy certificates.
    line_child = _line_value(r"\b/name\b|name\s*:", r"(?:/\s*)?([A-Za-z][A-Za-z\s]{2,})\s*$")
    line_father = _line_value(r"father'?s?\s*name", r"(?:/\s*)?([A-Za-z][A-Za-z\s]{2,})\s*$")
    line_grandfather = _line_value(r"grand\s*father'?s?\s*name", r"(?:/\s*)?([A-Za-z][A-Za-z\s]{2,})\s*$")
    line_mother = _line_value(r"mother'?s?\s*name", r"(?:/\s*)?([A-Za-z][A-Za-z\s]{2,})\s*$")
    line_sign = _line_value(r"signed\s*by", r"signed\s*by\s*[:\-]?\s*([A-Za-z][A-Za-z\s.]{2,})")
    line_apostille_sign = _line_value(r"has\s+been\s+signed\s+by", r"has\s+been\s+signed\s+by\s+([A-Za-z][A-Za-z\s.]{2,})")
    line_signed_by = _line_value(r"has\s+been\s+signed\s+by", r"has\s+been\s+signed\s+by\s+([A-Za-z][A-Za-z\s.]{2,})")

    if line_child:
        values["child_name"] = line_child
    if line_father:
        values["father_name"] = line_father
    if line_grandfather:
        values["grandfather_name"] = line_grandfather
    if line_mother:
        values["mother_name"] = line_mother
    if line_sign:
        values["signature_name"] = line_sign
    if line_apostille_sign:
        values["apostille_sign"] = line_apostille_sign
    if line_signed_by:
        values["signed_by"] = line_signed_by

    values["sex"], debug["sex"] = _normalize_sex(values.get("sex", ""))

    for name_key in ("child_name", "father_name", "grandfather_name", "mother_name", "signature_name", "apostille_sign", "signed_by"):
        cleaned_name = _clean_person_name(values.get(name_key, ""))
        if cleaned_name:
            values[name_key] = cleaned_name
            debug[name_key]["value"] = cleaned_name

    # Trim spillover when OCR keeps adjacent labels on same line.
    if values.get("place"):
        values["place"] = re.sub(r"\bRemark\b.*$", "", values["place"], flags=re.I).strip(" ,.")
        debug["place"]["value"] = values["place"]

    if values.get("designation"):
        values["designation"] = re.sub(r"\bLocation\b.*$", "", values["designation"], flags=re.I).strip(" ,.")
        debug["designation"]["value"] = values["designation"]

    if values.get("location"):
        values["location"] = re.sub(r"\bRemark\b.*$", "", values["location"], flags=re.I).strip(" ,.")
        debug["location"]["value"] = values["location"]

    # Enforce name-only fallbacks for sign fields if label-like values slipped through.
    if values.get("signature_name", "").strip().lower() in {"signed by", "signed"}:
        signer_match = re.search(
            r"Signed\s*By\s*[:\-]?\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)",
            text,
            flags=re.I,
        )
        if signer_match:
            sign_name = _clean_person_name(signer_match.group(1))
            if sign_name:
                values["signature_name"] = sign_name
                debug["signature_name"]["value"] = sign_name

    if values.get("apostille_sign", "").strip().lower() in {"signed by", "of sdm", "sdm"}:
        apostille_match = re.search(
            r"has\s+been\s+signed\s+by\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)",
            text,
            flags=re.I,
        )
        if apostille_match:
            apostille_sign = _clean_person_name(apostille_match.group(1))
            if apostille_sign:
                values["apostille_sign"] = apostille_sign
                debug["apostille_sign"]["value"] = apostille_sign

    # Try OCR-line style fallback for signature block when direct labels are missing.
    if not values.get("signature_name"):
        value, meta = _extract_with_meta(
            normalized,
            [r"signed\s*by\s*[:\-]?\s*([A-Za-z\s.]+)", r"signature\s*[:\-]?\s*([A-Za-z\s.]+)"],
            method="ocr_line",
        )
        values["signature_name"] = _clean_text(value)
        debug["signature_name"] = meta

    # Template typo tolerance: if template has <<MOTHER> instead of <<MOTHER>> we still extract mother_name normally.

    data = BirthSchema(**values)

    values = data.model_dump()
    warnings = [f"Missing field: {key}" for key, value in values.items() if key != "doc_type" and not value]

    for key in values:
        meta = debug.get(key)
        if not meta:
            debug[key] = _meta(values[key], "fallback", "", "", 0.0 if not values[key] else 0.4)
            continue
        if not meta.get("value"):
            meta["value"] = values[key]
        if "source_snippet" not in meta and "snippet" in meta:
            meta["source_snippet"] = meta.get("snippet", "")
        meta.pop("snippet", None)

    return values, warnings, debug
