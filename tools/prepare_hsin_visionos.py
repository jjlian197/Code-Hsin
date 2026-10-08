"""Prepare private Hsin geometry, calibrated motions and interaction resources reproducibly."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def prepare(model: Path, transitions: Path, workspace: Path, destination: Path,
            shared_textures: Path | None) -> None:
    root = Path(__file__).resolve().parents[1]
    workspace = workspace.resolve()
    destination = destination.resolve()
    # All generated files live outside the original model/calibration directories.
    for original in (model.resolve(), transitions.resolve()):
        if workspace.is_relative_to(original.parent) or destination.is_relative_to(original.parent):
            raise ValueError('Generated resources must be separate from original assets')
    workspace.mkdir(parents=True, exist_ok=True)
    geometry = workspace / 'geometry.json'
    posture = workspace / 'posture.json'
    interactions = workspace / 'interactions.json'
    for tool, inputs in (
        ('bake_hsin_spatial.mjs', [model.resolve(), geometry]),
        ('bake_hsin_postures.mjs', [geometry, transitions.resolve(), posture]),
        ('bake_hsin_interactions.mjs', [posture, interactions]),
    ):
        subprocess.run(['node', '--loader', './tools/node_three_loader.mjs',
                        'tools/' + tool, *map(str, inputs)], cwd=root, check=True)
    exported = workspace / 'export'
    command = [sys.executable, '-m', 'tools.export_hsin_usdz', str(interactions), str(exported)]
    if shared_textures is not None:
        command.extend(['--shared-textures', str(shared_textures.resolve())])
    subprocess.run(command, cwd=root, check=True)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exported / 'Hsin.usdz', destination / 'Hsin.usdz')
    motions = destination / 'Motions'
    motions.mkdir(exist_ok=True)
    # Do not bundle conversion intermediates or private source paths in provenance reports.
    for source in (exported / 'Motions').iterdir():
        if source.suffix in ('.usdz', '.json'):
            shutil.copy2(source, motions / source.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--transitions', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--shared-textures', type=Path)
    options = parser.parse_args()
    prepare(options.model, options.transitions, options.workspace, options.destination, options.shared_textures)


if __name__ == '__main__':
    main()
