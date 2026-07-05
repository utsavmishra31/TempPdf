from __future__ import annotations

from services.template_audit import extract_template_placeholders


def find_unfilled_placeholders(docx_path: str) -> dict[str, object]:
    counts = extract_template_placeholders(docx_path)
    placeholders = sorted(counts.keys())
    return {
        "unfilled_placeholders": placeholders,
        "placeholder_counts": dict(sorted(counts.items(), key=lambda kv: kv[0])),
        "has_unfilled": bool(placeholders),
    }
