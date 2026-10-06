"""Load editable YAML and prompt files. Re-read on each call so edits apply immediately."""

from __future__ import annotations

import yaml

from app.settings import ROOT

CONFIG = ROOT / "config"


def load_yaml(name: str) -> dict:
    path = CONFIG / name
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be a mapping")
    return data


def load_text(name: str) -> str:
    return (CONFIG / name).read_text(encoding="utf-8").strip()


def style_rules() -> dict:
    return load_yaml("style.yaml")


def scoring_rules() -> dict:
    return load_yaml("scoring.yaml")


def proof_library() -> list[dict]:
    return list(load_yaml("proof_points.yaml").get("points") or [])


def export_columns() -> list[dict]:
    columns = load_yaml("export_columns.yaml").get("columns") or []
    return list(columns)


def research_config() -> dict:
    return load_yaml("research.yaml")
