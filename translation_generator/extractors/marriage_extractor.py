from __future__ import annotations

import re

from schemas.marriage_schema import MarriageSchema

DATE_TEXT = r"[0-9OS]{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Noy|Dec)[a-z]*\s+(?:19|20)[0-9OS]{2}"
PERSON_STOPWORDS = {
    "BRIDE",
    "BRIDEGROOM",
    "PARTICULARS",
    "TITLE",
    "NAME",
    "FATHER",
    "MOTHER",
    "DATE",
    "FORM",
    "OF",
    "DISTRICT",
    "PUNJAB",
    "SET",
    "THE",
    "CAPACITY",
    "DIVISION",
    "OFFICER",
    "MINISTRY",
    "EXTERNAL",
    "ATLAS",
    "WLC",
    "WD",
    "EH",
    "OH",
    "DZ",
}


def _meta(value: str, method: str, pattern: str, snippet: str, confidence: float) -> dict[str, str | float]:
    return {
        "value": value,
        "confidence": confidence,
        "method": method,
        "pattern": pattern,
        "source_snippet": snippet,
    }


def _fallback_meta(value: str = "") -> dict[str, str | float]:
    return _meta(value, "fallback", "", "", 0.0 if not value else 0.4)


def _clean_text(value: str) -> str:
    cleaned = re.sub(r"\s{2,}", " ", (value or "").replace("\n", " "))
    return cleaned.strip(" ,.:;_-'\"{}[]()")


def _snippet(text: str, start: int, end: int, radius: int = 80) -> str:
    return _clean_text(text[max(0, start - radius): min(len(text), end + radius)])


def _extract_with_meta(
    text: str,
    patterns: list[str],
    method: str = "regex",
    confidence: float = 0.9,
) -> tuple[str, dict[str, str | float]]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        value = _clean_text(match.group(1))
        return value, _meta(value, method, pattern, _snippet(text, match.start(), match.end()), confidence)
    return "", _fallback_meta("")


def _pick_last_with_meta(text: str, patterns: list[str], method: str = "regex") -> tuple[str, dict[str, str | float]]:
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL))
        for match in reversed(matches):
            value = _clean_text(match.group(1))
            if value:
                return value, _meta(value, method, pattern, _snippet(text, match.start(), match.end()), 0.85)
    return "", _fallback_meta("")


def _normalize_date(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.sub(r"^0S\b", "05", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^OS\b", "05", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bNoy\b", "Nov", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b0ct\b", "Oct", cleaned, flags=re.IGNORECASE)
    return cleaned


def _clean_serial_no(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]+", "", _clean_text(value).upper())
    if compact.startswith("ES") and compact.endswith("G"):
        compact = compact[:-1] + "6"
    match = re.search(r"ES([0-9]{6,})", compact)
    if match:
        return "ES" + match.group(1)
    return compact


def _clean_person_name(value: str) -> str:
    words = re.findall(r"[A-Za-z]+", _clean_text(value))
    cleaned_words: list[str] = []
    for word in words:
        upper = word.upper()
        if len(upper) <= 2 or upper in PERSON_STOPWORDS:
            continue
        cleaned_words.append(upper)
        if len(cleaned_words) >= 4:
            break
    return " ".join(cleaned_words)


def _is_person_name(value: str) -> bool:
    return len(_clean_person_name(value).split()) >= 2


def _clean_address(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = cleaned.replace("!", "I").replace("’", " ")
    cleaned = re.sub(r"\s*:\s*\d+\s*$", "", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"\s+([,.])", r"\1", cleaned)
    return _clean_text(cleaned)


def _clean_address_side(value: str) -> str:
    cleaned = _clean_address(value)
    slash_parts = [part for part in re.split(r"\s*/\s*", cleaned) if _clean_text(part)]
    if len(slash_parts) > 1:
        cleaned = slash_parts[-1]
    starts = [
        r"\bV\s*P\s*O\b",
        r"\bVPO\b",
        r"\bC\s+[A-Z0-9]",
        r"\b[A-Z0-9][A-Z0-9\s./\-]{3,}\b(?:SPAIN|CANADA|USA|UNITED\s+KINGDOM|UK|ITALY|GERMANY|FRANCE|AUSTRALIA|NEW\s+ZEALAND)\b",
    ]
    for start_pattern in starts:
        match = re.search(start_pattern, cleaned, flags=re.IGNORECASE)
        if match:
            cleaned = cleaned[match.start():]
            break
    if re.match(r"\bV\s*P\s*O\b|\bVPO\b", cleaned, flags=re.IGNORECASE):
        cleaned = re.sub(r"\b(?:fs|fila|flr|fete|free|det|fifa|yarel|veers|shits|feba|waua|Ure)\b.*$", "", cleaned, flags=re.IGNORECASE)
    else:
        cleaned = re.sub(r"[’']?\s*(?:feta\s+fer\s+\d+|aded\s+fry\s+rena)\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:Abs|Ht|fs|fila|flr|fete|free|det|fifa|yarel|veers|shits|feba|waua|Ure|Wea|Waeug|wedug|vsnet|wares|geet|sete|feta|fer|wana|aded|fry|rena)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = _clean_address(cleaned)
    village_match = re.match(r"(VILLAGE\s+[A-Z0-9]+)\b.*?\b(MUTSADI\b.*)$", cleaned, flags=re.IGNORECASE)
    if village_match:
        cleaned = _clean_address(f"{village_match.group(1)} {village_match.group(2)}")
    cleaned = re.sub(r"\b[a-z]\s+(?=DISTT\b)", "", cleaned)
    return _clean_address(cleaned)


def _address_segments_between(text: str, start_pattern: str, end_pattern: str) -> list[str]:
    pattern = start_pattern + r"(.*?)" + end_pattern
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL))
    segments = [_clean_text(match.group(1)) for match in matches if _clean_text(match.group(1))]
    return sorted(
        segments,
        key=lambda segment: (
            bool(re.search(r"\b(?:VILLAGE|MUTSADI|CHUHEK|DISTT|SPAIN|CANADA|USA|UNITED|ITALY|GERMANY|FRANCE)\b", segment, flags=re.IGNORECASE)),
            len(segment),
        ),
        reverse=True,
    )


def _clean_marriage_place(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.sub(r"[^A-Za-z0-9,./\-\s]+", " ", cleaned)
    cleaned = re.sub(r"\s+\.\s*(?:[0-9]\s*)+", " ", cleaned)
    match = re.search(r"(.*?\bDISTT\s+[A-Za-z]+)", cleaned, flags=re.IGNORECASE)
    if match:
        cleaned = match.group(1)
    return _clean_text(cleaned)


def _segment_between(text: str, start_pattern: str, end_pattern: str) -> str:
    pattern = start_pattern + r"(.*?)" + end_pattern
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL))
    if not matches:
        return ""
    return _clean_text(min((match.group(1) for match in matches), key=len))


def _person_candidates(segment: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"\b[A-Z][A-Z]+(?:\s+[A-Z][A-Z]+){0,3}\b", segment):
        candidate = _clean_person_name(match.group(0))
        if not candidate or candidate in candidates:
            continue
        candidates.append(candidate)
    return candidates


def _apply_pair(
    values: dict[str, str],
    debug: dict[str, dict[str, str | float]],
    left_key: str,
    right_key: str,
    segment: str,
    pattern: str,
) -> None:
    candidates = _person_candidates(segment)
    if candidates:
        values[left_key] = candidates[0]
        debug[left_key] = _meta(candidates[0], "ocr_table", pattern, segment, 0.88)
    if len(candidates) > 1:
        values[right_key] = candidates[1]
        debug[right_key] = _meta(candidates[1], "ocr_table", pattern, segment, 0.88)


def _apply_address_pair(
    values: dict[str, str],
    debug: dict[str, dict[str, str | float]],
    left_key: str,
    right_key: str,
    segment: str,
    pattern: str,
) -> None:
    if not segment:
        return
    cleaned = _clean_text(segment)
    split_match = re.search(r"\b(VILLAGE\s+[A-Za-z0-9].*)$", cleaned, flags=re.IGNORECASE)
    if split_match:
        left_value = _clean_address_side(cleaned[: split_match.start()])
        right_value = _clean_address_side(split_match.group(1))
    else:
        left_value = _clean_address_side(cleaned)
        right_value = ""
    if left_value:
        values[left_key] = left_value
        debug[left_key] = _meta(left_value, "ocr_table", pattern, segment, 0.65)
    if right_value:
        values[right_key] = right_value
        debug[right_key] = _meta(right_value, "ocr_table", pattern, segment, 0.65)


def _apply_best_address_pair(
    values: dict[str, str],
    debug: dict[str, dict[str, str | float]],
    left_key: str,
    right_key: str,
    segments: list[str],
    pattern: str,
) -> None:
    for segment in segments:
        before = (values.get(left_key, ""), values.get(right_key, ""))
        _apply_address_pair(values, debug, left_key, right_key, segment, pattern)
        if values.get(left_key) and values.get(right_key):
            debug[left_key]["confidence"] = 0.8
            debug[right_key]["confidence"] = 0.8
            return
        if before != (values.get(left_key, ""), values.get(right_key, "")) and values.get(left_key):
            continue


def _apply_date_age_status(values: dict[str, str], debug: dict[str, dict[str, str | float]], compact_text: str) -> None:
    date_pair = re.search(
        r"Date\s+Of\s+Birth\s*/?\s*(" + DATE_TEXT + r")\s+(" + DATE_TEXT + r")",
        compact_text,
        flags=re.IGNORECASE,
    )
    if date_pair:
        values["novio_birth_date"] = _normalize_date(date_pair.group(1))
        values["novia_birth_date"] = _normalize_date(date_pair.group(2))
        debug["novio_birth_date"] = _meta(values["novio_birth_date"], "ocr_table", "Date Of Birth pair", date_pair.group(0), 0.9)
        debug["novia_birth_date"] = _meta(values["novia_birth_date"], "ocr_table", "Date Of Birth pair", date_pair.group(0), 0.9)

    age_pair = re.search(
        r"Age\s+at\s+the\s+time\s+of\s+Marriage\s+(About\s+[0-9]+\s+Years?\s+[0-9]+\s+months?)\s+(About\s+[0-9]+\s+Years?\s+[0-9]+\s+months?)",
        compact_text,
        flags=re.IGNORECASE,
    )
    if age_pair:
        values["novio_marriage_age"] = _clean_text(age_pair.group(1))
        values["novia_marriage_age"] = _clean_text(age_pair.group(2))
        debug["novio_marriage_age"] = _meta(values["novio_marriage_age"], "ocr_table", "Age pair", age_pair.group(0), 0.9)
        debug["novia_marriage_age"] = _meta(values["novia_marriage_age"], "ocr_table", "Age pair", age_pair.group(0), 0.9)

    status_pair = re.search(
        r"Civil\s+condition\s+at\s+the\s+time\s+of\s+Marriage\s+(Unmarried|Married|Divorced|Widowed)\s+(Unmarried|Married|Divorced|Widowed)",
        compact_text,
        flags=re.IGNORECASE,
    )
    if status_pair:
        values["marriage_status"] = _clean_text(status_pair.group(1)).title()
        values["novio_marriage_status"] = _clean_text(status_pair.group(1)).title()
        values["novia_marriage_status"] = _clean_text(status_pair.group(2)).title()
        debug["marriage_status"] = _meta(values["marriage_status"], "ocr_table", "Civil condition pair", status_pair.group(0), 0.9)
        debug["novio_marriage_status"] = _meta(values["novio_marriage_status"], "ocr_table", "Civil condition pair", status_pair.group(0), 0.9)
        debug["novia_marriage_status"] = _meta(values["novia_marriage_status"], "ocr_table", "Civil condition pair", status_pair.group(0), 0.9)

    date_segment = _segment_between(
        compact_text,
        r"\b6\.?\s*Date\s+Of\s+Birth\s*/?",
        r"\b7[A.]?\s*Civil\s+condition",
    )
    dates = [_normalize_date(match.group(0)) for match in re.finditer(DATE_TEXT, date_segment, flags=re.IGNORECASE)]
    if dates and not values.get("novio_birth_date"):
        values["novio_birth_date"] = dates[0]
        debug["novio_birth_date"] = _meta(dates[0], "ocr_table", DATE_TEXT, date_segment, 0.88)
    if len(dates) > 1 and not values.get("novia_birth_date"):
        values["novia_birth_date"] = dates[1]
        debug["novia_birth_date"] = _meta(dates[1], "ocr_table", DATE_TEXT, date_segment, 0.88)

    ages = re.findall(r"About\s+[0-9]+\s+Years?\s+[0-9]+\s+months?", date_segment, flags=re.IGNORECASE)
    if ages and not values.get("novio_marriage_age"):
        values["novio_marriage_age"] = _clean_text(ages[0])
        debug["novio_marriage_age"] = _meta(values["novio_marriage_age"], "ocr_table", "age at the time of Marriage", date_segment, 0.85)
    if len(ages) > 1 and not values.get("novia_marriage_age"):
        values["novia_marriage_age"] = _clean_text(ages[1])
        debug["novia_marriage_age"] = _meta(values["novia_marriage_age"], "ocr_table", "age at the time of Marriage", date_segment, 0.85)

    status_segment = _segment_between(
        compact_text,
        r"\b7[A.]?\s*Civil\s+condition\s+at\s+the\s+time\s+of\s+Marriage",
        r"\bRegistered\s+at\s+No\.",
    )
    statuses = re.findall(r"\b(?:Unmarried|Married|Divorced|Widowed)\b", status_segment, flags=re.IGNORECASE)
    if statuses and not values.get("marriage_status"):
        status = _clean_text(statuses[0]).title()
        values["marriage_status"] = status
        values["novio_marriage_status"] = status
        values["novia_marriage_status"] = status
        debug["marriage_status"] = _meta(status, "ocr_table", "Civil condition", status_segment, 0.9)
        debug["novio_marriage_status"] = _meta(status, "ocr_table", "Civil condition", status_segment, 0.9)
        debug["novia_marriage_status"] = _meta(status, "ocr_table", "Civil condition", status_segment, 0.9)


def _normalize_reference(value: str) -> str:
    return re.sub(r"[^A-Z0-9\-/]+", "", _clean_text(value).upper())


def _normalize_stamp_no(value: str) -> str:
    text = _clean_text(value).upper()
    match = re.search(r"(?:[O0]I|OI|01)\s*([0-9OI]{7})", text)
    if match:
        return match.group(1).replace("O", "0").replace("I", "1")
    return re.sub(r"\D+", "", text)


def extract_fields(text: str) -> tuple[dict[str, str], list[str], dict[str, dict[str, str | float]]]:
    normalized = (text or "").replace("|", " ")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    compact = re.sub(r"\s+", " ", normalized)

    keys = [key for key in MarriageSchema.model_fields if key != "doc_type"]
    values = {key: "" for key in keys}
    debug = {key: _fallback_meta("") for key in keys}

    patterns: dict[str, list[str]] = {
        "serial_no": [r"Document\s+Sr\.?\s*No\s*[:;\-]?\s*([A-Z0-9\-/ ]{6,})"],
        "application_date": [r"Date\s+of\s+Application\s*[:;\-]?\s*(" + DATE_TEXT + r")"],
        "marriage_date": [r"Date\s+of\s+Solemnization\s+of\s+Marriage\s*[:;\-]?\s*(" + DATE_TEXT + r")"],
        "marriage_place": [r"Place\s+of\s+Marriage\s*[:;\-]?\s*(.*?)(?=\s+District\s*[:;\-]|\s+S\.\s*No\.)"],
        "district": [r"District\s*[:;\-]?\s*[^/\n]{0,40}/\s*([A-Z][A-Za-z]+)", r"District\s*[:;\-]?\s*([A-Z][A-Za-z]+)"],
        "register_no": [r"Registered\s+at\s+No\.?\s*([A-Z0-9\-/]+)\s+on\s+" + DATE_TEXT],
        "register_date": [r"Registered\s+at\s+No\.?\s*[A-Z0-9\-/]+\s+on\s+(" + DATE_TEXT + r")"],
        "name": [r"Name\s+of\s+Applicant\s*[:;\-]?\s*(?:[^/\n]{0,80}/\s*)?([A-Za-z][A-Za-z\s]{2,}?)(?=\s*[:;\n]|\s+Date\s+of\s+Application)"],
        "sign_name": [r"Digitally\s+Signed\s+by\s*[:;\-]?\s*([A-Za-z][A-Za-z\s]{2,}?)(?=\s+UID|\s+Designation|\n)"],
        "uid": [r"UID\s*/\s*EID\s*[:;\-]?\s*(Not\s+Provided|[A-Z0-9\-/]+)"],
        "designation": [r"Designation\s*[:;\-]?\s*([A-Za-z][A-Za-z\s]{2,}?)(?=\s+Date\s*[:;\-]|\n)"],
        "approv_date": [r"Designation\s*[:;\-]?\s*[A-Za-z][A-Za-z\s]{2,}?\s+Date\s*[:;\-]?\s*(" + DATE_TEXT + r")"],
        "location": [r"Location\s*[:;\-]?\s*([A-Za-z]+)"],
        "reference_no": [
            r"(?:apostille\s*)?reference\s*(?:no|number|n[°º.])\s*[:;\-]?\s*([A-Z0-9\-/]+)",
            r"N[°º.]\s*([0-9]{8,15})",
            r"\bno\s+([0-9]{10,})\b",
        ],
        "apostille_sign": [
            r"\(([A-Za-z][A-Za-z\s]{3,30}?)\)[\s\S]{0,500}(?:Attestation|Anestation|Section\s*Officer|Potion\s+Otticer|PV\s*Division|Ministry\s+of\s+External)",
            r"([A-Za-z][A-Za-z\s]{3,30}?)\s*[\s\S]{0,160}(?:Section\s*Officer|Attestation|Anestation|PV\s*Division)",
        ],
        "signed_by": [
            r"[hm]as\s+[^A-Za-z\n]{0,10}(?:been|oon)[^A-Za-z\n]{0,10}signed\s+by[^A-Za-z\n]{0,10}([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,2})",
            r"signed\s+by[^A-Za-z\n]{0,10}([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,2})",
        ],
        "apostille_date": [r"\bthe\s+([0-9OS]{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Noy|Dec)[a-z]*\s*20[0-9OS]{2})\b", r"\b([0-9OS]{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Noy|Dec)[a-z]*\s+20[0-9OS]{2})\b"],
        "stamp_no": [r"\b((?:[O0]I|OI|01)\s*[0-9OI]{7})\b"],
    }

    for key, key_patterns in patterns.items():
        if key in {"reference_no", "apostille_date", "stamp_no"}:
            value, meta = _pick_last_with_meta(normalized, key_patterns)
        else:
            value, meta = _extract_with_meta(normalized, key_patterns)
        if not value:
            continue
        if key in {"application_date", "marriage_date", "register_date", "approv_date", "apostille_date"}:
            value = _normalize_date(value)
        if key == "serial_no":
            value = _clean_serial_no(value)
        if key == "marriage_place":
            value = _clean_marriage_place(value)
        if key in {"name", "sign_name", "apostille_sign", "signed_by"}:
            value = _clean_person_name(value)
        if key == "apostille_sign" and not _is_person_name(value):
            continue
        if key == "reference_no":
            value = _normalize_reference(value)
        if key == "stamp_no":
            value = _normalize_stamp_no(value)
        values[key] = value
        debug[key] = {**meta, "value": value}

    name_segment = _segment_between(compact, r"\b1\.?\s*Name\b", r"\b2\.?\s*Father'?s\s+Name\b")
    father_segment = _segment_between(compact, r"\b2\.?\s*Father'?s\s+Name\b", r"\b3\.?\s*Mother'?s\s+Name\b")
    mother_segment = _segment_between(compact, r"\b3\.?\s*Mother'?s\s+Name\b", r"\b4[.,]?\s*Usual\s+place")
    residence_segment = _segment_between(compact, r"\b4[.,]?\s*Usual\s+place\s+of\s+residence\b", r"\b5\.?\s*Full\s*/\s*Foreign\s+Address\b")
    foreign_segment = _segment_between(compact, r"\b5\.?\s*Full\s*/\s*Foreign\s+Address\b", r"\b6\.?\s*Date\s+Of\s+Birth")
    residence_segments = _address_segments_between(compact, r"\b4[.,]?\s*Usual\s+place\s+of\s+residence\b", r"\b5\.?\s*Full\s*/\s*Foreign\s+Address\b")
    foreign_segments = _address_segments_between(compact, r"\b5\.?\s*Full\s*/\s*Foreign\s+Address\b", r"\b6\.?\s*Date\s+Of\s+Birth")

    _apply_pair(values, debug, "novio_name", "novia_name", name_segment, "Name row")
    _apply_pair(values, debug, "novio_father", "novia_father", father_segment, "Father row")
    _apply_pair(values, debug, "novio_mother", "novia_mother", mother_segment, "Mother row")
    _apply_address_pair(values, debug, "novio_place_of_residence", "novia_place_of_residence", residence_segment, "Usual place of residence row")
    _apply_address_pair(values, debug, "novio_foreign_address", "novia_foreign_address", foreign_segment, "Full/Foreign Address row")
    _apply_best_address_pair(values, debug, "novio_place_of_residence", "novia_place_of_residence", residence_segments, "Usual place of residence row")
    _apply_best_address_pair(values, debug, "novio_foreign_address", "novia_foreign_address", foreign_segments, "Full/Foreign Address row")
    _apply_date_age_status(values, debug, compact)

    if not values.get("novia_father"):
        novia_father, novia_father_meta = _extract_with_meta(normalized, [r"Fates\s+dz\s*/\s*([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+){0,3})"])
        novia_father = _clean_person_name(novia_father)
        if novia_father:
            values["novia_father"] = novia_father
            debug["novia_father"] = {**novia_father_meta, "value": novia_father, "confidence": 0.75}

    if not values.get("novio_foreign_address"):
        foreign_address, foreign_meta = _extract_with_meta(
            foreign_segment or normalized,
            [r"/\s*([A-Z0-9][A-Z0-9\s./\-]{8,}?)(?=\s+(?:" + DATE_TEXT + r"|VILLAGE\b|DISTT\b)|$)"],
        )
        if foreign_address and not re.fullmatch(DATE_TEXT, foreign_address, flags=re.IGNORECASE):
            values["novio_foreign_address"] = _clean_address(foreign_address)
            debug["novio_foreign_address"] = {**foreign_meta, "value": values["novio_foreign_address"], "confidence": 0.75}

    if not values.get("apostille_sign"):
        for match in re.finditer(r"\(([A-Za-z][A-Za-z\s]{3,30}?)\)", normalized):
            window = normalized[match.end(): match.end() + 500]
            if not re.search(r"Attestation|Anestation|Section\s*Officer|Potion\s+Otticer|PV\s*Division|Ministry\s+of\s+External", window, flags=re.IGNORECASE):
                continue
            person = _clean_person_name(match.group(1))
            if _is_person_name(person):
                values["apostille_sign"] = person
                debug["apostille_sign"] = _meta(person, "ocr_apostille", "parenthesized signer near officer block", match.group(0) + " " + _clean_text(window[:160]), 0.82)
                break

    if values.get("apostille_date") == values.get("approv_date"):
        values["apostille_date"] = ""
        debug["apostille_date"] = _fallback_meta("")

    if values.get("novia_name") and not values.get("name"):
        values["name"] = values["novia_name"]
        debug["name"] = _meta(values["name"], "fallback", "novia_name", values["novia_name"], 0.7)

    data = MarriageSchema(**values)
    values = data.model_dump()
    warnings = [f"Missing field: {key}" for key, value in values.items() if key != "doc_type" and not value]

    for key in values:
        if key == "doc_type":
            continue
        meta = debug.get(key)
        if not meta:
            debug[key] = _fallback_meta(values[key])
            continue
        if not meta.get("value"):
            meta["value"] = values[key]

    return values, warnings, debug
