from __future__ import annotations

import zipfile
from collections import Counter
import re
from pathlib import Path
from xml.sax.saxutils import unescape

PLACEHOLDER_PATTERN = re.compile(r"<<[A-Z0-9_]+>>?|&lt;&lt;[A-Z0-9_]+&gt;&gt;?|<<[A-Z0-9_]+&gt;&gt;?")


def _normalize_placeholder(token: str) -> str:
    raw = unescape(token)
    if raw.startswith("<<") and raw.endswith(">>"):
        return raw
    if raw.startswith("<<") and raw.endswith(">"):
        return raw + ">"
    return raw


def extract_template_placeholders(template_path: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    with zipfile.ZipFile(template_path, "r") as archive:
        xml_files = [
            name
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ]

        for name in xml_files:
            content = archive.read(name).decode("utf-8", errors="ignore")
            tokens = PLACEHOLDER_PATTERN.findall(content)
            normalized = [_normalize_placeholder(token) for token in tokens]
            counts.update(normalized)
    return counts


def audit_template_placeholders(
    template_path: str,
    expected_placeholders: set[str],
) -> dict[str, object]:
    path = Path(template_path)
    result: dict[str, object] = {
        "exists": path.exists(),
        "readable": False,
        "template_path": str(path),
        "present_placeholders": [],
        "placeholder_counts": {},
        "malformed_placeholders": [],
        "missing_placeholders": [],
        "unused_placeholders": [],
        "error": "",
    }

    if not path.exists():
        result["error"] = f"Template not found: {path}"
        return result

    try:
        counts = extract_template_placeholders(str(path))
        present = set(counts.keys())
        result["readable"] = True
        result["present_placeholders"] = sorted(present)
        result["placeholder_counts"] = dict(sorted(counts.items(), key=lambda kv: kv[0]))
        result["malformed_placeholders"] = sorted(
            [token for token in present if token.startswith("<<") and not token.endswith(">>")]
        )
        result["missing_placeholders"] = sorted(expected_placeholders - present)
        result["unused_placeholders"] = sorted(present - expected_placeholders)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"Template could not be read as DOCX: {exc}"
        return result
