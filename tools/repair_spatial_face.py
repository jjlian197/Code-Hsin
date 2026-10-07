"""Repair a private USDZ copy; never edit source/reference character files."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from pxr import Usd
from tools.export_hsin_usdz import package_stage
from tools.spatial_face_mesh import merge_face_meshes


def repair(source: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    extracted = output / 'source'
    extracted.mkdir(exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        root_layer = archive.namelist()[0]
        for filename in archive.namelist():
            destination = (extracted / filename).resolve()
            if not destination.is_relative_to(extracted.resolve()):
                raise ValueError('USDZ member escapes output directory')
            if filename.endswith('/'):
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(filename))
    stage = Usd.Stage.Open(str(extracted / root_layer))
    report = merge_face_meshes(stage)
    stage.GetRootLayer().Save()
    package_stage(extracted / root_layer, output / source.name)
    report['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    (output / 'face-repair.json').write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    options = parser.parse_args()
    print(json.dumps(repair(options.source, options.output)))


if __name__ == '__main__':
    main()
