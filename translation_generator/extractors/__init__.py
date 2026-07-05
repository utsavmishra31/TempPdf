from __future__ import annotations

from typing import Callable, Union

from .birth_extractor import extract_fields as extract_birth
from .marriage_extractor import extract_fields as extract_marriage
from .medical_extractor import extract_fields as extract_medical
from .pcc_extractor import extract_fields as extract_pcc


ExtractorResult = Union[
    tuple[dict[str, str], list[str]],
    tuple[dict[str, str], list[str], dict[str, dict[str, str]]],
]


def get_extractor(doc_type: str) -> Callable[[str], ExtractorResult]:
    mapping: dict[str, Callable[[str], ExtractorResult]] = {
        "pcc": extract_pcc,
        "birth": extract_birth,
        "marriage": extract_marriage,
        "medical": extract_medical,
    }
    if doc_type not in mapping:
        raise ValueError(f"Unsupported document type for extractor: {doc_type}")
    return mapping[doc_type]
