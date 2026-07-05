from __future__ import annotations

from schemas.marriage_schema import MarriageSchema
from utils.regex_helpers import find_first


def extract_fields(text: str) -> tuple[dict[str, str], list[str]]:
    data = MarriageSchema(
        husband_name=find_first(text, [r"husband\s*name\s*[:\-]?\s*([A-Za-z\s]+)"]),
        wife_name=find_first(text, [r"wife\s*name\s*[:\-]?\s*([A-Za-z\s]+)"]),
        marriage_date=find_first(text, [r"marriage\s*date\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"]),
        marriage_place=find_first(text, [r"(?:place\s*of\s*marriage|marriage\s*place)\s*[:\-]?\s*([A-Za-z0-9,\s]+)"]),
        registration_no=find_first(text, [r"registration\s*(?:no|number)\s*[:\-]?\s*([A-Z0-9\-/]+)"]),
        registration_date=find_first(text, [r"registration\s*date\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"]),
        husband_father_name=find_first(text, [r"husband\s*father\s*name\s*[:\-]?\s*([A-Za-z\s]+)"]),
        wife_father_name=find_first(text, [r"wife\s*father\s*name\s*[:\-]?\s*([A-Za-z\s]+)"]),
        issuing_authority=find_first(text, [r"(?:issuing\s*authority|registrar)\s*[:\-]?\s*([A-Za-z\s]+)"]),
        certificate_date=find_first(text, [r"(?:certificate\s*date|issue\s*date)\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"]),
        country_name=find_first(text, [r"country\s*[:\-]?\s*([A-Za-z\s]+)"]),
    )

    values = data.model_dump()
    warnings = [f"Missing field: {key}" for key, value in values.items() if key != "doc_type" and not value]
    return values, warnings
