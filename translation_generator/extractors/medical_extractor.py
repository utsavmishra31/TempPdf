from __future__ import annotations

from schemas.medical_schema import MedicalSchema
from utils.regex_helpers import find_first


def extract_fields(text: str) -> tuple[dict[str, str], list[str]]:
    data = MedicalSchema(
        patient_name=find_first(text, [r"patient\s*name\s*[:\-]?\s*([A-Za-z\s]+)"]),
        patient_age=find_first(text, [r"(?:age|patient\s*age)\s*[:\-]?\s*([0-9]{1,3})"]),
        patient_sex=find_first(text, [r"(?:sex|gender)\s*[:\-]?\s*(male|female|other)"]),
        certificate_date=find_first(text, [r"(?:certificate\s*date|date)\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"]),
        doctor_name=find_first(text, [r"doctor\s*name\s*[:\-]?\s*([A-Za-z\s.]+)", r"dr\.?\s*([A-Za-z\s.]+)"]),
        doctor_registration_no=find_first(text, [r"(?:doctor\s*registration\s*no|reg(?:istration)?\s*no)\s*[:\-]?\s*([A-Z0-9\-/]+)"]),
        hospital_name=find_first(text, [r"hospital\s*name\s*[:\-]?\s*([A-Za-z0-9\s]+)", r"hospital\s*[:\-]?\s*([A-Za-z0-9\s]+)"]),
        diagnosis=find_first(text, [r"diagnosis\s*[:\-]?\s*([A-Za-z0-9,\-\s]+)"]),
        medical_statement=find_first(text, [r"(?:medical\s*statement|certified\s*that)\s*[:\-]?\s*([A-Za-z0-9,\-\s]+)"]),
        admission_date=find_first(text, [r"admission\s*date\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"]),
        discharge_date=find_first(text, [r"discharge\s*date\s*[:\-]?\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4})"]),
        country_name=find_first(text, [r"country\s*[:\-]?\s*([A-Za-z\s]+)"]),
    )

    values = data.model_dump()
    warnings = [f"Missing field: {key}" for key, value in values.items() if key != "doc_type" and not value]
    return values, warnings
