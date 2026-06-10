"""Repository structure tests for HACS packaging."""

from __future__ import annotations

import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "etherlighter" / "brand"


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)

    assert header.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", header[16:24])


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
    expected_assets = {
        BRAND / "icon.png": (256, 256),
        BRAND / "logo.png": (512, 512),
    }
    for path, dimensions in expected_assets.items():
        assert path.is_file()
        assert path.stat().st_size > 0
        assert _png_dimensions(path) == dimensions
