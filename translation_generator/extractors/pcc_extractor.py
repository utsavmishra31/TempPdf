from __future__ import annotations

import re

from schemas.pcc_schema import PCCSchema
from utils.regex_helpers import find_first_with_meta

RELATION_ES_MAP = {
    "S/o": "hijo de",
    "D/o": "hija de",
    "W/o": "mujer de",
}


def _clean_value(value: str) -> str:
    return re.sub(r"\s{2,}", " ", (value or "").strip(" ,."))


def _normalize_doc_number(value: str) -> str:
    text = _clean_value(value)
    # Remove lone lowercase letters sandwiched between uppercase letters — a
    # common OCR insertion artifact (e.g. 'ClH' → 'CH', 'CHaNDIGARH' stays).
    text = re.sub(r"(?<=[A-Z])[a-z](?=[A-Z0-9])", "", text)
    text = text.upper()
    # OCR sometimes inserts spaces inside alphanumeric document numbers.
    text = re.sub(r"\s+", "", text)
    # OCR often substitutes letter-O for digit-0 inside document codes after a
    # 3+-letter alpha prefix (e.g. CHCHO005 → CHCH0005).
    # Use capture group instead of lookbehind to stay Python 3.9 compatible.
    text = re.sub(r"([A-Z]{3,})O([0-9O])", lambda m: m.group(1) + "0" + m.group(2), text)
    return text


def _fallback_meta(value: str = "") -> dict[str, str | float]:
    return {
        "value": value,
        "confidence": 0.0 if not value else 0.5,
        "method": "fallback",
        "pattern": "",
        "source_snippet": "",
    }


def _meta_from_find(pattern: str, value: str, snippet: str, confidence: float = 0.92) -> dict[str, str | float]:
    return {
        "value": value,
        "confidence": confidence,
        "method": "regex",
        "pattern": pattern,
        "source_snippet": snippet,
    }


def _snippet(text: str, start: int, end: int, radius: int = 70) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - radius): min(len(text), end + radius)]).strip()


def _pick_last_match(text: str, pattern: str) -> tuple[str, dict[str, str | float]]:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL))
    if not matches:
        return "", _fallback_meta("")

    m = matches[-1]
    value = _clean_value(m.group(1))
    snippet = _snippet(text, m.start(), m.end())
    return value, _meta_from_find(pattern, value, snippet)


def _is_jalandhar_pcc(text: str) -> bool:
    compact = re.sub(r"\s+", " ", text or "")
    return bool(
        re.search(r"regional\s+passport\s+office\s*[,\-]?\s*jalandhar\b", compact, flags=re.IGNORECASE)
        or re.search(r"\bRPO\s*,?\s*JALANDHAR\b", compact, flags=re.IGNORECASE)
    )


def _extract_jalandhar_apostille_officer_name(text: str) -> tuple[str, dict[str, str | float]]:
    pattern = r"\((Suresh\s+Kum(?:ar|a)?)\b[^)]{0,80}\((?:Attestation|Atrestation|Aliestatio)"
    match = re.search(pattern, text or "", flags=re.IGNORECASE)
    if not match:
        return "", _fallback_meta("")

    sign_name = _clean_value(match.group(1)).upper()
    if re.match(r"^SURESH\s+KUM", sign_name):
        sign_name = "SURESH KUMAR"
    return sign_name, _meta_from_find(
        pattern,
        sign_name,
        _snippet(text, match.start(), match.end()),
        0.9,
    )


def _extract_main_pcc_record(text: str) -> dict[str, str | dict[str, dict[str, str | float]]]:
    compact = re.sub(r"\s+", " ", text)
    pattern = (
        r"there is no adverse information against\s+(?:Mr\.?|Ms\.?|Mrs\.?)?\s*"
        r"([A-Za-z\s]+?)\s+(S/o|D/o|W/o)\s+([A-Za-z\s]+?),\s*holder of Indian Passport No\s*([A-Z0-9]+),"
        r"\s*issued at\s*[A-Za-z\s]+,\s*on\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"
        r".*?ineligible for\s*([A-Za-z/\-\s]+?)\s+for"
    )
    matches = list(re.finditer(pattern, compact, flags=re.IGNORECASE | re.DOTALL))
    if not matches:
        return {
            "name": "",
            "relation_text": "",
            "father_name": "",
            "passport_no": "",
            "passport_issue_or_sentence_date": "",
            "purpose": "",
            "debug": {},
        }

    m = matches[-1]
    name = _clean_value(m.group(1)).upper()
    relation = _clean_value(m.group(2))
    father = _clean_value(m.group(3)).upper()
    passport_no = _clean_value(m.group(4)).upper()
    issue_date = _clean_value(m.group(5))
    purpose = _clean_value(m.group(6)).upper()
    snippet = _snippet(compact, m.start(), m.end())

    debug = {
        "name": {
            "value": name,
            "confidence": 0.95,
            "method": "regex",
            "pattern": pattern,
            "source_snippet": snippet,
        },
        "relation_text": {
            "value": relation,
            "confidence": 0.95,
            "method": "regex",
            "pattern": pattern,
            "source_snippet": snippet,
        },
        "father_name": {
            "value": father,
            "confidence": 0.95,
            "method": "regex",
            "pattern": pattern,
            "source_snippet": snippet,
        },
        "passport_no": {
            "value": passport_no,
            "confidence": 0.95,
            "method": "regex",
            "pattern": pattern,
            "source_snippet": snippet,
        },
        "passport_issue_or_sentence_date": {
            "value": issue_date,
            "confidence": 0.95,
            "method": "regex",
            "pattern": pattern,
            "source_snippet": snippet,
        },
        "purpose": {
            "value": purpose,
            "confidence": 0.95,
            "method": "regex",
            "pattern": pattern,
            "source_snippet": snippet,
        },
    }

    return {
        "name": name,
        "relation_text": relation,
        "father_name": father,
        "passport_no": passport_no,
        "passport_issue_or_sentence_date": issue_date,
        "purpose": purpose,
        "debug": debug,
    }


def _extract_jalandhar_main_pcc_record(text: str) -> dict[str, str | dict[str, dict[str, str | float]]]:
    compact = re.sub(r"\s+", " ", text)
    pattern = (
        r"there is no adverse information against\s+(?:Mr\.?|Ms\.?|Mrs\.?)?\s*"
        r"([A-Za-z\s]+?)\s+(S/o|D/o|W/o)\s+([A-Za-z\s]+?),\s*holder of Indian Passport No\s*([A-Z0-9][A-Z0-9\s]{4,20}),"
        r"\s*issued at\s*JALANDHAR\s*,\s*on\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"
        r".*?ineligible\s*(?:\|\s*)?for\s*([A-Za-z/\-\s]+?)\s+for"
    )
    matches = list(re.finditer(pattern, compact, flags=re.IGNORECASE | re.DOTALL))
    if not matches:
        return {
            "name": "",
            "relation_text": "",
            "father_name": "",
            "passport_no": "",
            "passport_issue_or_sentence_date": "",
            "purpose": "",
            "debug": {},
        }

    match = matches[-1]
    name = _clean_value(match.group(1)).upper()
    relation = _clean_value(match.group(2))
    father = _clean_value(match.group(3)).upper()
    passport_no = _normalize_doc_number(match.group(4))
    issue_date = _clean_value(match.group(5))
    purpose = _clean_value(match.group(6)).upper()
    snippet = _snippet(compact, match.start(), match.end())

    debug = {}
    for key, value in {
        "name": name,
        "relation_text": relation,
        "father_name": father,
        "passport_no": passport_no,
        "passport_issue_or_sentence_date": issue_date,
        "purpose": purpose,
    }.items():
        debug[key] = {
            "value": value,
            "confidence": 0.9,
            "method": "jalandhar_ocr_regex",
            "pattern": pattern,
            "source_snippet": snippet,
        }

    return {
        "name": name,
        "relation_text": relation,
        "father_name": father,
        "passport_no": passport_no,
        "passport_issue_or_sentence_date": issue_date,
        "purpose": purpose,
        "debug": debug,
    }


def _extract_apostille_fields(text: str) -> tuple[str, str, str, dict[str, dict[str, str | float]]]:
    # Labelled reference patterns (Spanish/English)
    reference_no, ref_meta = _pick_last_match(
        text,
        r"(?:apostille\s*)?(?:(?:reference|referencia)\s*(?:no|number|n\.?[ºo°]?)|n\.?\s*[ºo°]?\s*de\s*referencia)\s*[:\-]?\s*([A-Z0-9\-/]+)",
    )
    # Fallback: standalone apostille reference code (e.g. CHCH0005380826 or HCH/CHCHO OCR variants)
    if not reference_no:
        # Allow O (letter) for 0 (digit) substitution common in OCR
        m = re.search(r"\b([HC]{1,2}CH[O0][0-9O]{8,11})\b", text)
        if m:
            reference_no = m.group(1)
            # OCR sometimes drops the leading 'C' → fix HCHNNNN → CHCH...
            if reference_no.startswith("HCH") and not reference_no.startswith("CHCH"):
                reference_no = "C" + reference_no
            ref_meta = _meta_from_find("standalone_ref_code", reference_no, m.group(0), 0.80)

    if not reference_no and _is_jalandhar_pcc(text):
        reference_pattern = r"\bN\s*[°ºoO]?\s*([A-Z]{2,5}[A-Z0-9O]{8,12})\b"
        reference_match = re.search(reference_pattern, text, flags=re.IGNORECASE)
        if reference_match:
            reference_no = reference_match.group(1)
            ref_meta = _meta_from_find(
                reference_pattern,
                reference_no,
                _snippet(text, reference_match.start(), reference_match.end()),
                0.88,
            )

    sign_patterns = [
        # Name in parentheses immediately before/after 'Section Officer' or 'Attestation'
        # Require two-word minimum to avoid matching single words like INDIA, CARDIOLOGY
        r"\(([A-Z][A-Z.]{2,}\s+[A-Z.][A-Z\s.]{2,})\)\s*\n?\s*[Ss]ection\s+[Oo]fficer",
        r"[Ss]ection\s+[Oo]fficer[^\n]{0,60}\n\s*\(([A-Z][A-Z.]{2,}\s+[A-Z.][A-Z\s.]{2,})\)",
        r"\(([A-Z][A-Z.]{2,}\s+[A-Z.][A-Z\s.]{2,})\)[^\n]{0,60}(?:Attestation|Section)",
        # Two-word name in parens near apostille block (two-word guard prevents INDIA, CARDIOLOGY)
        r"\(([A-Z][A-Z.]{2,}\s+[A-Z.][A-Z\s.]{2,})\)",
        r"\b(PRADIP\s+DAS)\b",
        r"firmado\s+por\s+([A-Za-z][A-Za-z\s.]{2,}?)\s*(?=\b(?:actuando|con\s+el\s+sello|$))",
        r"signed\s*by\s*[:\-]?\s*([A-Za-z][A-Za-z\s.]{2,}?)\s+acting\s+in\s+the\s+capacity",
        r"\bby\s+([A-Za-z][A-Za-z\s.]{2,}?)\s+acting\s+in\s+the\s+capacity",
        r"firma\s+y\s+sello\s*[:\-]?\s*([A-Za-z][A-Za-z\s.]{4,})",
    ]

    sign_name = ""
    sign_meta = _fallback_meta("")
    # Words that commonly appear in parentheses on Indian documents but are NOT officer names.
    _SIGN_NAME_BLOCKLIST = {
        "CODIGO", "BARRAS", "REPUBLIC", "INDIA", "MINISTRY", "EXTERNAL",
        "AFFAIRS", "GOVERNMENT", "CHANDIGARH", "CARDIOLOGY", "MEDICINE",
        "CLEARANCE", "PASSPORT", "REGIONAL", "OFFICE", "DELHI",
    }
    for pattern in sign_patterns:
        val, meta = _pick_last_match(text, pattern)
        if val:
            candidate = _clean_value(val).upper()
            # Reject if any word is in the blocklist
            words = candidate.split()
            if any(w in _SIGN_NAME_BLOCKLIST for w in words):
                continue
            sign_name = candidate
            sign_meta = {**meta, "value": sign_name, "confidence": 0.9}
            break

    stamp_patterns = [
        r"(?:stamp\s*(?:no|number)|seal\s*(?:no|number))\s*[:\-]?\s*([A-Z0-9I][A-Z0-9I\s./\-]{4,})",
        # Match apostille stamp codes: OCR may render '0I' (zero-I) as 'OI' (letter O + I)
        r"\b([O0]I\s*[0-9]{6,9})\b",
    ]
    stamp_no = ""
    stamp_meta = _fallback_meta("")
    for pattern in stamp_patterns:
        val, meta = _pick_last_match(text, pattern)
        if val:
            raw = re.sub(r"\s+", "", _clean_value(val).upper())
            # Strip OI/0I prefix — the template has '0I ' hardcoded before <<0I_NO>>
            # so we store only the digit portion (e.g. 'OI 4853487' → '4853487')
            digits = re.sub(r"^[O0]I", "", raw)
            if digits.isdigit():
                stamp_no = digits
                stamp_meta = {**meta, "value": stamp_no, "confidence": 0.9}
                break

    if not stamp_no and _is_jalandhar_pcc(text):
        stamp_match = re.search(r"\b([0-9]{7})\b", text)
        if stamp_match:
            stamp_no = stamp_match.group(1)
            stamp_meta = _meta_from_find(
                "jalandhar_standalone_stamp_digits",
                stamp_no,
                _snippet(text, stamp_match.start(), stamp_match.end()),
                0.78,
            )

    signed_by = ""
    signed_by_meta = _fallback_meta("")
    signed_by_patterns = [
        r"has\s+been\s+signed\s+by\s+([A-Za-z][A-Za-z\s.]{2,}?)\s*(?=\b(?:acting|$))",
        r"ha\s+sido\s+firmado\s+por\s+([A-Za-z][A-Za-z\s.]{2,}?)\s*(?=\b(?:actuando|con\s+el\s+sello|$))",
        r"signed\s+by\s+([A-Za-z][A-Za-z\s.]{2,}?)\s+acting\s+in\s+the\s+capacity",
        # Looser: 'signed by <noise chars> <NAME>' — handles OCR noise between label and name
        r"signed\s+by\s+[^A-Za-z]{0,10}([A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})+)",
    ]
    for pattern in signed_by_patterns:
        val, meta = _pick_last_match(text, pattern)
        if val:
            signed_by = _clean_value(val).upper()
            signed_by = re.split(r"\b(?:ACTUANDO|ACTING)\b", signed_by, maxsplit=1)[0].strip()
            signed_by_meta = {**meta, "value": signed_by, "confidence": 0.9}
            break

    if _is_jalandhar_pcc(text):
        jalandhar_sign_name, jalandhar_sign_meta = _extract_jalandhar_apostille_officer_name(text)
        if jalandhar_sign_name:
            sign_name = jalandhar_sign_name
            sign_meta = jalandhar_sign_meta

    apostille_date = ""
    apostille_date_meta = _fallback_meta("")
    date_patterns = [
        r"at\s+[A-Za-z\s,]+[.:]\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
        r"at\s+[A-Za-z\s,]+[.:]\s*([0-9]{1,2}-[A-Za-z]{3,9}-[0-9]{4})",
        r"\bel\s+([0-9]{1,2}\s+de\s+[A-Za-záéíóú]+\s+de\s+[0-9]{4})",
        # Apostille date on its own line after 'NEW DELHI' or 'DELHI' (OCR noise tolerance)
        r"(?:NEW\s+DELHI|DELHI)[^\n]{0,30}\n\s*([0-9]{1,2}[.\-'\s]+[A-Za-z]{3,9}[.\-'\s]+20[0-9]{2})",
        # Standalone DD-Mon-YYYY anywhere in apostille text
        r"([0-9]{1,2}[.\-'\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[.\-'\s]+20[0-9]{2})",
    ]
    for pattern in date_patterns:
        val, meta = _pick_last_match(text, pattern)
        if val:
            apostille_date = _clean_value(val)
            apostille_date_meta = {**meta, "value": apostille_date, "confidence": 0.88}
            break

    ref_value = _normalize_doc_number(reference_no)
    return ref_value, sign_name, signed_by, apostille_date, stamp_no, {
        "reference_no": {**ref_meta, "value": ref_value},
        "sign_name": sign_meta,
        "signed_by": signed_by_meta,
        "apostille_date": apostille_date_meta,
        "stamp_no": stamp_meta,
    }


def _build_last_valid_record_pair(text: str) -> tuple[str, str]:
    compact = re.sub(r"\s+", " ", text)
    main_blocks = list(
        re.finditer(
            r"POLICE\s+CLEARANCE\s+CERTIFICATE.*?(?=(?:POLICE\s+CLEARANCE\s+CERTIFICATE|APOSTILLE|$))",
            compact,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    apostille_blocks = list(
        re.finditer(
            r"APOSTILLE.*?(?=(?:POLICE\s+CLEARANCE\s+CERTIFICATE|APOSTILLE|$))",
            compact,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )

    if not main_blocks:
        return compact, compact

    pairs: list[tuple[str, str]] = []
    for main_match in main_blocks:
        main_text = main_match.group(0)
        apostille_text = ""
        for apo_match in apostille_blocks:
            if apo_match.start() > main_match.end():
                apostille_text = apo_match.group(0)
                break
        pairs.append((main_text, apostille_text))

    def score_main(candidate: str) -> int:
        score = 0
        if re.search(r"File\s*Number", candidate, re.IGNORECASE):
            score += 1
        if re.search(r"PCC\s*Issuance\s*Date", candidate, re.IGNORECASE):
            score += 1
        if re.search(r"Passport\s*No", candidate, re.IGNORECASE):
            score += 1
        if re.search(r"ineligible\s*for", candidate, re.IGNORECASE):
            score += 1
        return score

    valid_pairs = [pair for pair in pairs if score_main(pair[0]) >= 2]
    if valid_pairs:
        return valid_pairs[-1]
    return pairs[-1]


def extract_fields(text: str) -> tuple[dict[str, str], list[str], dict[str, dict[str, str | float]]]:
    values: dict[str, str] = {
        "cert_no": "",
        "cert_date": "",
        "name": "",
        "relation_text": "",
        "relation_text_es": "",
        "father_name": "",
        "passport_no": "",
        "passport_issue_or_sentence_date": "",
        "purpose": "",
        "reference_no": "",
        "sign_name": "",
        "apostille_date": "",
        "stamp_no": "",
    }
    debug: dict[str, dict[str, str | float]] = {key: _fallback_meta("") for key in values}

    main_text, apostille_text = _build_last_valid_record_pair(text)

    cert_no, cert_no_meta = _pick_last_match(
        main_text,
        # Match 'File Number', 'hale Number', 'sle Number', 'lite Number' etc.
        # (OCR frequently misreads 'F' as 's' or 'l' in the decorative header)
        r"(?:File|hale|sle|lite|\w+le)\s*(?:Number|No|N\.?[ºo°]?)\s*[:\-]?\s*([A-Z0-9\-/\s]+)",
    )
    cert_date, cert_date_meta = _pick_last_match(
        main_text,
        r"(?:PCC\s*Issuance\s*Date|certificate\s*date|fecha\s*de\s*emi(?:s|si)on)\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
    )
    values["cert_no"] = _normalize_doc_number(cert_no)
    values["cert_date"] = cert_date
    debug["cert_no"] = {**cert_no_meta, "value": values["cert_no"]}
    debug["cert_date"] = cert_date_meta

    if not values["cert_no"]:
        cert_no_fallback_patterns = [
            # OCR noise-tolerant label variants
            r"(?:File|hale|sle|lite|\w+le)\s*Number\s*[:\-]?\s*([A-Z]{2,6}\s*[0-9\s]{8,16})",
            r"N\.?\s*[ºo°]?\s*de\s*Expediente\s*[:\-]?\s*([A-Z]{2,6}\s*[0-9\s]{8,16})",
            # Direct: CH/PB/etc. + 13 digits adjacent to PCC Issuance Date
            r"([A-Z]{2}[0-9]{13,15})\s+PCC\s+Issuance\s+Date",
            r"([A-Z]{2}[0-9]{13,15})",
        ]
        for pattern in cert_no_fallback_patterns:
            val, meta = _pick_last_match(text, pattern)
            normalized = _normalize_doc_number(val)
            if normalized and re.match(r"^[A-Z]{2}[0-9]{10,15}$", normalized):
                values["cert_no"] = normalized
                debug["cert_no"] = {**meta, "value": normalized, "confidence": 0.9}
                break

    if not values["cert_date"]:
        cert_date_fallback_patterns = [
            r"PCC\s*Issuance\s*Date\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
            r"Fecha\s*de\s*Emi(?:s|si)on\s*del\s*Certificado\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})",
        ]
        for pattern in cert_date_fallback_patterns:
            val, meta = _pick_last_match(text, pattern)
            if val:
                values["cert_date"] = _clean_value(val)
                debug["cert_date"] = {**meta, "value": values["cert_date"], "confidence": 0.9}
                break

    main_record = _extract_main_pcc_record(main_text)
    if _is_jalandhar_pcc(text) and not str(main_record.get("name", "")).strip():
        main_record = _extract_jalandhar_main_pcc_record(text)
    for key in [
        "name",
        "relation_text",
        "father_name",
        "passport_no",
        "passport_issue_or_sentence_date",
        "purpose",
    ]:
        values[key] = str(main_record.get(key, ""))
        if key in (main_record.get("debug") or {}):
            debug[key] = (main_record.get("debug") or {}).get(key, debug[key])

    values["relation_text_es"] = RELATION_ES_MAP.get(values["relation_text"], "")
    debug["relation_text_es"] = {
        "value": values["relation_text_es"],
        "confidence": 0.99 if values["relation_text_es"] else 0.0,
        "method": "label_match",
        "pattern": "RELATION_ES_MAP",
        "source_snippet": values["relation_text"],
    }

    reference_no, sign_name, signed_by, apostille_date, stamp_no, apostille_debug = _extract_apostille_fields(apostille_text or text)
    values["reference_no"] = reference_no
    values["sign_name"] = sign_name
    values["apostille_date"] = apostille_date
    values["stamp_no"] = stamp_no
    debug["reference_no"] = apostille_debug["reference_no"]
    debug["sign_name"] = apostille_debug["sign_name"]
    debug["apostille_date"] = apostille_debug["apostille_date"]
    debug["stamp_no"] = apostille_debug["stamp_no"]

    if _is_jalandhar_pcc(text):
        jalandhar_sign_name, jalandhar_sign_meta = _extract_jalandhar_apostille_officer_name(text)
        if jalandhar_sign_name:
            values["sign_name"] = jalandhar_sign_name
            debug["sign_name"] = jalandhar_sign_meta

    # Avoid false-positive stamp_no when OCR captures passport number.
    if values["stamp_no"] and values["passport_no"] and values["stamp_no"].replace(" ", "") == values["passport_no"].replace(" ", ""):
        values["stamp_no"] = ""
        debug["stamp_no"] = _fallback_meta("")

    # OCR digital signature blocks can inject tax IDs; they are not office stamp numbers.
    if values["stamp_no"] and "NIF" in values["stamp_no"].upper():
        values["stamp_no"] = ""
        debug["stamp_no"] = _fallback_meta("")

    if not values["sign_name"]:
        fallback_sign, fallback_meta = find_first_with_meta(
            apostille_text or text,
            [r"\bby\s+([A-Z][A-Z\s]{4,})\s+acting\s+in\s+the\s+capacity\b"],
        )
        values["sign_name"] = _clean_value(fallback_sign).upper()
        debug["sign_name"] = {
            "value": values["sign_name"],
            "confidence": 0.85 if values["sign_name"] else 0.0,
            "method": "regex" if values["sign_name"] else "fallback",
            "pattern": fallback_meta.get("pattern", ""),
            "source_snippet": fallback_meta.get("snippet", ""),
        }

    for key in values:
        meta = debug.get(key, {})
        if not meta.get("value"):
            meta["value"] = values[key]
        if "confidence" not in meta:
            meta["confidence"] = 0.0 if not values[key] else 0.5
        if "source_snippet" not in meta and "snippet" in meta:
            meta["source_snippet"] = meta.get("snippet", "")
        if "method" not in meta:
            meta["method"] = "fallback"
        if "pattern" not in meta:
            meta["pattern"] = ""
        meta.pop("snippet", None)
        debug[key] = meta

    data = PCCSchema(**values)

    values = data.model_dump()
    warnings = [f"Missing field: {key}" for key, value in values.items() if key != "doc_type" and not value]
    return values, warnings, debug
