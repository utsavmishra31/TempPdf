from __future__ import annotations

import re


def _normalize_value(value: str) -> str:
    value = value.strip()
    return re.sub(r"\s{2,}", " ", value)


def _build_snippet(text: str, start: int, end: int, radius: int = 45) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right]
    snippet = snippet.replace("\n", " ")
    snippet = re.sub(r"\s{2,}", " ", snippet)
    return snippet.strip()


def find_first(text: str, patterns: list[str], flags: int = re.IGNORECASE) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=flags)
        if match:
            return _normalize_value(match.group(1))
    return ""


def find_first_with_meta(
    text: str,
    patterns: list[str],
    flags: int = re.IGNORECASE,
) -> tuple[str, dict[str, str]]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=flags)
        if not match:
            continue

        value = _normalize_value(match.group(1))
        meta = {
            "method": "regex",
            "pattern": pattern,
            "snippet": _build_snippet(text, match.start(), match.end()),
        }
        return value, meta

    return "", {"method": "regex", "pattern": "", "snippet": ""}
