"""Prepare calibrated Aemeath resources using a read-only reference exporter."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from pxr import Sdf

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from tools.repair_spatial_face import repair
from tools.export_hsin_usdz import package_stage


def prepare(reference: Path, model: Path, hsin_samples: Path, workspace: Path, realtime_cloth: bool = False) -> None:
    if not realtime_cloth and (PROJECT / 'visionos/HsinVision/Resources/Motions/physics.json').exists():
        raise ValueError('Existing realtime resources require --realtime-cloth; refusing stale physics metadata')
    workspace = workspace.resolve()
    # Generated files stay in our ignored workspace; reference sources are never destinations.
    if not workspace.is_relative_to(PROJECT / '.runtime'):
        raise ValueError('Workspace must be inside this project .runtime')
    workspace.mkdir(parents=True, exist_ok=True)
    desktop = workspace / 'desktop.json'
    sampled = workspace / 'interactions.json'
    subprocess.run(['node', str(reference / 'visionos/Tools/bake_motion.mjs'), str(model), str(desktop)], cwd=reference, check=True)
    subprocess.run(['node', str(PROJECT / 'tools/bake_aemeath_interactions.mjs'), str(model), str(desktop), str(hsin_samples), str(sampled), *(['--realtime-cloth'] if realtime_cloth else [])], cwd=PROJECT, check=True)
    sys.path.insert(0, str(reference))
    specification = importlib.util.spec_from_file_location('aemeath_reference_export', reference / 'visionos/Tools/export_usdz.py')
    if specification is None or specification.loader is None:
        raise ImportError('Reference exporter unavailable')
    exporter = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(exporter)
    # Source gaze morph directions match the character axes; positive X is her left.
    exporter.MORPH_TARGETS.update({'left': 'look_left', 'right': 'look_right', 'up': 'look_up', 'down': 'look_down'})
    # USD packaging mutates loaded layers; isolate it so later clips retain texture references.
    def package(source: Sdf.AssetPath, destination: str) -> bool:
        package_stage(Path(source.path), Path(destination))
        return True
    exporter.UsdUtils.CreateNewUsdzPackage = package
    generated = workspace / 'generated'
    clips = generated / 'Motions'
    exporter.export(model, sampled, generated / 'Aemeath.usdz', clips, True)
    repaired = workspace / 'repaired'
    face_report = repair(generated / 'Aemeath.usdz', repaired)
    payload = json.loads(sampled.read_text())
    for name in ('behavior', 'posture', *(['physics'] if 'physics' in payload else [])):
        (clips / (name + '.json')).write_text(json.dumps(payload[name], ensure_ascii=False))
    output = PROJECT / 'visionos/HsinVision/Resources'
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repaired / 'Aemeath.usdz', output / 'Aemeath.usdz')
    destination = output / 'Motions'
    destination.mkdir(exist_ok=True)
    for clip in clips.iterdir():
        if clip.suffix in ('.usdz', '.json'):
            shutil.copy2(clip, destination / clip.name)
    report = {'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(), 'calibration': payload['calibration'], 'face': face_report, 'motions': [motion['name'] for motion in payload['motions']]}
    (workspace / 'preparation.json').write_text(json.dumps(report, indent=2))
    print('Prepared 18 Aemeath motions and shared interactions; source assets unchanged.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--hsin-samples', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--realtime-cloth', action='store_true')
    options = parser.parse_args()
    prepare(options.reference_root.resolve(), options.model.resolve(), options.hsin_samples.resolve(), options.workspace, options.realtime_cloth)

if __name__ == '__main__':
    main()
