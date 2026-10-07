"""Copy explicitly selected private reference assets into the ignored visionOS build resources."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    options = parser.parse_args()
    source_root = options.reference_root / 'visionos/AemeathCompanion/Resources'
    output_root = Path(__file__).resolve().parents[1] / 'visionos/HsinVision/Resources'
    selected = ['Aemeath.usdz', 'Motions/idle.usdz', 'Motions/wave.usdz']
    for relative in selected:
        if not (source_root / relative).is_file():
            raise FileNotFoundError(source_root / relative)
    for relative in selected:
        output = output_root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, output)
    manifest = json.loads((source_root / 'Motions/manifest.json').read_text())
    (output_root / 'Motions/manifest.json').write_text(json.dumps({name: manifest[name] for name in ('idle', 'wave')}))
    print('Prepared Aemeath, idle and wave private assets; originals untouched.')


if __name__ == '__main__':
    main()
