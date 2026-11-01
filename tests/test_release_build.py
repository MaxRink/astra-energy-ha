"""Tests for the HACS release archive builder."""

from __future__ import annotations

import json
import zipfile

from tools.build_release import build


def test_build_release_contains_integration_at_hacs_path(tmp_path) -> None:
    output = build(tmp_path)

    assert output.name.startswith("astra-energy-ha-v")
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "custom_components/astra_energy/manifest.json" in names
        assert "custom_components/astra_energy/translations/en.json" in names
        assert "custom_components/astra_energy/translations/de.json" in names
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        manifest = json.loads(
            archive.read("custom_components/astra_energy/manifest.json")
        )
        assert manifest["domain"] == "astra_energy"
        assert manifest["version"] in output.name
