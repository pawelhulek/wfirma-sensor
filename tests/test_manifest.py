"""Metadata Home Assistant and HACS rely on."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "wfirma"


def test_manifest() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == "wfirma"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["requirements"] == []
    for key in ("name", "version", "documentation", "issue_tracker", "codeowners"):
        assert manifest[key]


def test_translations_cover_the_same_keys() -> None:
    def keys(node, prefix=""):
        out = set()
        for k, v in node.items():
            path = f"{prefix}.{k}"
            out |= keys(v, path) if isinstance(v, dict) else {path}
        return out

    strings = keys(json.loads((COMPONENT / "strings.json").read_text()))
    for lang in ("en", "pl"):
        assert keys(json.loads((COMPONENT / "translations" / f"{lang}.json").read_text())) == strings, lang


def test_hacs_metadata() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"] and hacs["render_readme"] is True
