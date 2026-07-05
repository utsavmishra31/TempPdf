from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: float
    matched_keywords: list[str]


KEYWORDS: dict[str, list[str]] = {
    "pcc": [
        "police clearance certificate",
        "pcc issuance date",
        "file number",
        "passport no",
        "apostille",
        "certificado de antecedentes policiales",
        "n.° de referencia",
        "n. de referencia",
        "ha sido firmado por",
    ],
    "birth": [
        "birth certificate",
        "date of birth",
        "father name",
        "mother name",
        "registration no",
        "certificado de nacimiento",
        "fecha de nacimiento",
        "nombre del padre",
        "nombre de la madre",
    ],
    "marriage": [
        "marriage certificate",
        "husband",
        "wife",
        "place of marriage",
        "registrar",
    ],
    "medical": [
        "medical certificate",
        "doctor",
        "hospital",
        "diagnosis",
        "patient",
    ],
}


def detect_document_type(text: str) -> ClassificationResult:
    lowered = text.lower()
    best_type = "unknown"
    best_score = 0
    best_matches: list[str] = []

    for doc_type, keywords in KEYWORDS.items():
        matches = [kw for kw in keywords if kw in lowered]
        score = len(matches)
        if score > best_score:
            best_score = score
            best_type = doc_type
            best_matches = matches

    if best_score == 0:
        return ClassificationResult(
            doc_type="unknown",
            confidence=0.0,
            matched_keywords=[],
        )

    confidence = min(1.0, best_score / 3.0)
    return ClassificationResult(
        doc_type=best_type,
        confidence=confidence,
        matched_keywords=best_matches,
    )
