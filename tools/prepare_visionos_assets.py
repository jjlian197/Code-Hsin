"""Copy explicitly selected private reference assets into the ignored visionOS build resources."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.repair_spatial_face import repair


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--model', type=Path, help='Calibrated original Aemeath GLB for full interactions')
    parser.add_argument('--hsin-samples', type=Path, help='Calibrated Hsin interaction samples')
    parser.add_argument('--workspace', type=Path, help='Ignored workspace for full conversion')
    parser.add_argument('--realtime-cloth', action='store_true')
    options = parser.parse_args()
    full_options = (options.model, options.hsin_samples, options.workspace)
    if options.realtime_cloth and not all(full_options):
        parser.error('--realtime-cloth requires --model, --hsin-samples and --workspace')
    if any(full_options):
        if not all(full_options):
            parser.error('--model, --hsin-samples and --workspace must be used together')
        from tools.prepare_aemeath_interactions import prepare
        prepare(options.reference_root.resolve(), options.model.resolve(), options.hsin_samples.resolve(), options.workspace, options.realtime_cloth)
        return
    source_root = options.reference_root / 'visionos/AemeathCompanion/Resources'
    output_root = Path(__file__).resolve().parents[1] / 'visionos/HsinVision/Resources'
    current_manifest = output_root / 'Motions/manifest.json'
    if current_manifest.exists() and 'side_lying' in json.loads(current_manifest.read_text()):
        raise ValueError('Full interactions already prepared; use --model --hsin-samples --workspace to preserve them')
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
    repaired = Path(__file__).resolve().parents[1] / '.runtime/aemeath-face-preparation'
    repair(output_root / 'Aemeath.usdz', repaired)
    shutil.copy2(repaired / 'Aemeath.usdz', output_root / 'Aemeath.usdz')
    print('Prepared Aemeath with unified face morphs, idle and wave; originals untouched.')


if __name__ == '__main__':
    main()
