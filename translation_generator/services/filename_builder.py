from __future__ import annotations

import re
from pathlib import Path


def _clean(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def build_output_basename(doc_type: str, fields: dict[str, str], source_file_name: str = "") -> str:
    candidate_name = (
        fields.get("name")
        or fields.get("child_name")
        or fields.get("husband_name")
        or fields.get("patient_name")
        or Path(source_file_name).stem
        or "DOCUMENT"
    )

    clean_name = _clean(candidate_name).upper() or "DOCUMENT"
    return f"{clean_name}_{doc_type.upper()}_TRANSLATION"
