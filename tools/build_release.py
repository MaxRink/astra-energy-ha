#!/usr/bin/env python3
"""Build the HACS installable release zip for the current manifest version."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "astra_energy"


def build(output_dir: Path) -> Path:
    """Create one zip containing the integration under custom_components/."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"astra-energy-ha-v{version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            archive.write(path, path.relative_to(ROOT))
    return output


def main() -> int:
    """Build the release zip and print its path and checksum."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    output = build(args.output_dir)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(output)
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
