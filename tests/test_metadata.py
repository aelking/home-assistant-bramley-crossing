"""Check HACS-discoverable metadata and English UI text consistency."""

import json
from pathlib import Path


def test_hacs_metadata_and_translation():
    root = Path(__file__).resolve().parents[1]
    integration = root / "custom_components" / "bramley_crossing"
    manifest = json.loads((integration / "manifest.json").read_text())
    hacs = json.loads((root / "hacs.json").read_text())
    strings = json.loads((integration / "strings.json").read_text())
    english = json.loads((integration / "translations" / "en.json").read_text())
    assert manifest["domain"] == "bramley_crossing"
    assert manifest["config_flow"] is True
    assert manifest["version"] == "0.1.0"
    assert manifest["requirements"] == []
    assert hacs["homeassistant"] == "2025.2.0"
    assert strings == english
