from __future__ import annotations

import re
import zipfile
from xml.sax.saxutils import escape, unescape


TEXT_NODE_PATTERN = re.compile(r"(<w:t\b[^>]*>)(.*?)(</w:t>)", re.DOTALL)


def _replace_split_text_token(xml_text: str, placeholder: str, value: str) -> str:
    text_nodes = []
    cursor = 0
    joined_parts: list[str] = []

    for match in TEXT_NODE_PATTERN.finditer(xml_text):
        node_text = unescape(match.group(2))
        start = cursor
        end = start + len(node_text)
        text_nodes.append(
            {
                "content_start": match.start(2),
                "content_end": match.end(2),
                "text_start": start,
                "text_end": end,
                "text": node_text,
            }
        )
        joined_parts.append(node_text)
        cursor = end

    joined_text = "".join(joined_parts)
    token_start = joined_text.lower().find(placeholder.lower())
    if token_start < 0:
        return xml_text

    token_end = token_start + len(placeholder)
    replacements: list[tuple[int, int, str]] = []
    wrote_value = False

    for node in text_nodes:
        node_start = node["text_start"]
        node_end = node["text_end"]
        if node_end <= token_start or node_start >= token_end:
            continue

        node_text = str(node["text"])
        prefix = node_text[: max(token_start - node_start, 0)] if token_start > node_start else ""
        suffix = node_text[token_end - node_start :] if token_end < node_end else ""

        if not wrote_value:
            replacement_text = prefix + value + suffix
            wrote_value = True
        else:
            replacement_text = suffix

        replacements.append(
            (
                int(node["content_start"]),
                int(node["content_end"]),
                escape(replacement_text),
            )
        )

    updated = xml_text
    for start, end, replacement_text in reversed(replacements):
        updated = updated[:start] + replacement_text + updated[end:]
    return updated


def _replace_all_split_text_tokens(xml_text: str, placeholder: str, value: str) -> str:
    updated = xml_text
    for _ in range(100):
        next_updated = _replace_split_text_token(updated, placeholder, value)
        if next_updated == updated:
            return updated
        updated = next_updated
    return updated


def _replace_xml_tokens(xml_text: str, replacements: dict[str, str]) -> str:
    updated = xml_text
    for placeholder, value in replacements.items():
        safe_value = escape(value or "")
        escaped_placeholder = escape(placeholder)
        malformed_placeholder = placeholder[:-1] if placeholder.endswith(">>") else placeholder
        missing_open_placeholder = placeholder[1:] if placeholder.startswith("<<") else placeholder
        escaped_malformed_placeholder = escape(malformed_placeholder)
        escaped_missing_open_placeholder = escape(missing_open_placeholder)
        updated = updated.replace(placeholder, safe_value)
        updated = updated.replace(escaped_placeholder, safe_value)
        updated = _replace_all_split_text_tokens(updated, placeholder, value or "")
        updated = updated.replace(malformed_placeholder, safe_value)
        updated = updated.replace(escaped_malformed_placeholder, safe_value)
        if malformed_placeholder != placeholder:
            updated = _replace_all_split_text_tokens(updated, malformed_placeholder, value or "")
        if missing_open_placeholder != placeholder:
            updated = _replace_all_split_text_tokens(updated, missing_open_placeholder, value or "")
        updated = updated.replace(missing_open_placeholder, safe_value)
        updated = updated.replace(escaped_missing_open_placeholder, safe_value)
    return updated


def fill_template(template_path: str, output_path: str, data: dict[str, str]) -> str:
    with zipfile.ZipFile(template_path, "r") as src, zipfile.ZipFile(output_path, "w") as dst:
        for info in src.infolist():
            raw = src.read(info.filename)
            if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                text = raw.decode("utf-8", errors="ignore")
                text = _replace_xml_tokens(text, data)
                raw = text.encode("utf-8")
            dst.writestr(info, raw)
    return output_path
