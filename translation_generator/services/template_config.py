from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def config_path(base_dir: Path) -> Path:
    return base_dir / "config" / "template_profiles.json"


def load_template_config(base_dir: Path) -> dict[str, Any]:
    path = config_path(base_dir)
    if not path.exists():
        return {"doc_types": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_template_config(base_dir: Path, config: dict[str, Any]) -> None:
    path = config_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_all_doc_types(config: dict[str, Any]) -> list[str]:
    return sorted((config.get("doc_types") or {}).keys())


def get_active_doc_types(config: dict[str, Any]) -> list[str]:
    doc_types = config.get("doc_types") or {}
    return sorted([key for key, profile in doc_types.items() if profile.get("active", False)])


def get_field_mapping(config: dict[str, Any], doc_type: str) -> dict[str, str]:
    doc_types = config.get("doc_types") or {}
    profile = doc_types.get(doc_type, {})
    return dict(profile.get("field_to_placeholder") or {})


def get_required_fields(config: dict[str, Any], doc_type: str) -> list[str]:
    doc_types = config.get("doc_types") or {}
    profile = doc_types.get(doc_type, {})
    return list(profile.get("required_fields") or [])


def _first_existing_template(base_dir: Path, candidates: list[str]) -> Path | None:
    for rel_path in candidates:
        candidate = base_dir / rel_path
        if candidate.exists():
            return candidate
    return None


def resolve_template_path(base_dir: Path, config: dict[str, Any], doc_type: str, template_route: str | None = None) -> Path | None:
    doc_types = config.get("doc_types") or {}
    profile = doc_types.get(doc_type, {})
    if template_route:
        routes = profile.get("template_routes") or {}
        routed_path = _first_existing_template(base_dir, list(routes.get(template_route) or []))
        if routed_path is not None:
            return routed_path

    return _first_existing_template(base_dir, list(profile.get("template_candidates") or []))
