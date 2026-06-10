"""Repository structure tests for HACS packaging."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hacs_has_single_custom_component() -> None:
    components = [
        path
        for path in (ROOT / "custom_components").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    ]
    assert [path.name for path in components] == ["etherlighter"]


def test_manifest_required_fields() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "etherlighter" / "manifest.json").read_text()
    )
    for key in (
        "domain",
        "documentation",
        "issue_tracker",
        "codeowners",
        "name",
        "version",
    ):
        assert key in manifest
    assert manifest["domain"] == "etherlighter"
    assert manifest["config_flow"] is True
    assert "paramiko>=3.5,<4" in manifest["requirements"]


def test_hacs_brand_icon_exists() -> None:
    icon = ROOT / "custom_components" / "etherlighter" / "brand" / "icon.png"
    assert icon.is_file()
    assert icon.stat().st_size > 0
