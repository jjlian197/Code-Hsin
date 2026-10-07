"""Export sampled Hsin PMX geometry and desktop bone clips; original assets remain untouched."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdSkel, UsdUtils, Vt

FACE_NAMES = {'まばたき': 'blink', '笑い': 'smile', 'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o'}


def package_stage(source: Path, destination: Path) -> None:
    # The USD packager rewrites paths in loaded Sdf layers. A separate process preserves
    # the export stage used to copy subsequent skeleton clips and enables repeatable exports.
    subprocess.run([sys.executable, '-c',
        'import sys; from pxr import Sdf, UsdUtils; '
        'ok=UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(sys.argv[1]),sys.argv[2]); sys.exit(0 if ok else 1)',
        str(source.resolve()), str(destination.resolve())], check=True)


def create_surface(stage: Usd.Stage, index: int, source: dict[str, Any], textures: list[str],
                   model_directory: Path, output: Path, shared_textures: Path | None = None) -> UsdShade.Material:
    material = UsdShade.Material.Define(stage, f'/Hsin/Looks/m{index}')
    shader = UsdShade.Shader.Define(stage, f'{material.GetPath()}/Surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*source['diffuse'][:3]))
    shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(.85)
    shader.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(0)
    shader.CreateInput('opacity', Sdf.ValueTypeNames.Float).Set(float(source['diffuse'][3]))
    texture_index = source['textureIndex']
    if texture_index >= 0:
        path = (model_directory / textures[texture_index].replace('\\', '/')).resolve()
        allowed_root = model_directory.resolve()
        if not path.is_file() and shared_textures is not None:
            allowed_root = shared_textures.resolve()
            path = (allowed_root / textures[texture_index].replace('\\', '/')).resolve()
        if not path.is_relative_to(allowed_root) or not path.is_file():
            raise ValueError(f'Missing model texture: {textures[texture_index]}')
        texture_output = output / 'textures' / f'm{index}.png'
        texture_output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as original:
            pixels = original.convert('RGBA')
            pixels.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            # Match the desktop alpha-test boundary instead of importing transparent quads as opaque.
            pixels.putalpha(pixels.getchannel('A').point(lambda alpha: 255 if alpha * source['diffuse'][3] >= 25.5 else 0))
            pixels.save(texture_output)
        reader = UsdShade.Shader.Define(stage, f'{material.GetPath()}/UV')
        reader.CreateIdAttr('UsdPrimvarReader_float2')
        reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
        texture = UsdShade.Shader.Define(stage, f'{material.GetPath()}/Color')
        texture.CreateIdAttr('UsdUVTexture')
        texture.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(texture_output.resolve())))
        texture.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('sRGB')
        texture.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), 'result')
        texture.CreateOutput('rgb', Sdf.ValueTypeNames.Float3)
        texture.CreateOutput('a', Sdf.ValueTypeNames.Float)
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), 'rgb')
        shader.CreateInput('opacity', Sdf.ValueTypeNames.Float).ConnectToSource(texture.ConnectableAPI(), 'a')
        shader.CreateInput('opacityThreshold', Sdf.ValueTypeNames.Float).Set(.1)
    shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    return material


def joint_order(bones: list[dict[str, Any]]) -> tuple[list[int], list[str]]:
    paths: dict[int, str] = {}
    visiting: set[int] = set()

    def joint_path(index: int) -> str:
        if index in paths:
            return paths[index]
        if index in visiting:
            raise ValueError('Cyclic PMX skeleton')
        visiting.add(index)
        parent = bones[index]['parent']
        paths[index] = (joint_path(parent) + '/' if parent >= 0 else '') + f'j{index}'
        visiting.remove(index)
        return paths[index]

    ordered = sorted(range(len(bones)), key=lambda index: (joint_path(index).count('/'), joint_path(index)))
    return ordered, [paths[index] for index in ordered]


def bind_mesh(mesh: UsdGeom.Mesh, skeleton_path: Sdf.Path, joints: list[int], weights: list[float]) -> UsdSkel.BindingAPI:
    mesh.CreateSubdivisionSchemeAttr('none')
    mesh.CreateDoubleSidedAttr(True)
    binding = UsdSkel.BindingAPI.Apply(mesh.GetPrim())
    binding.CreateSkeletonRel().SetTargets([skeleton_path])
    binding.CreateGeomBindTransformAttr(Gf.Matrix4d(1))
    binding.CreateJointIndicesPrimvar(False, 4).Set(joints)
    binding.CreateJointWeightsPrimvar(False, 4).Set(weights)
    return binding


def export(sample_path: Path, output: Path, shared_textures: Path | None = None) -> None:
    sample = json.loads(sample_path.read_text())
    output.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateInMemory()
    stage.SetTimeCodesPerSecond(30)
    stage.SetStartTimeCode(0)
    stage.SetEndTimeCode(max(len(motion['frames']) - 1 for motion in sample['motions']))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    root = UsdSkel.Root.Define(stage, '/Hsin')
    stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.Xform.Define(stage, '/Hsin/Character')
    UsdGeom.Xform.Define(stage, '/Hsin/Character/Rig')
    skeleton = UsdSkel.Skeleton.Define(stage, '/Hsin/Character/Rig/Skeleton')
    ordered, paths = joint_order(sample['bones'])
    mapping = {original: index for index, original in enumerate(ordered)}
    local_transforms: dict[int, Gf.Matrix4d] = {}
    global_transforms: dict[int, Gf.Matrix4d] = {}
    for original in ordered:
        bone = sample['bones'][original]
        local_transforms[original] = Gf.Matrix4d(1).SetTranslate(Gf.Vec3d(*bone['position']))
        parent = bone['parent']
        global_transforms[original] = local_transforms[original] * global_transforms[parent] if parent >= 0 else local_transforms[original]
    skeleton.CreateJointsAttr(paths)
    skeleton.CreateRestTransformsAttr([local_transforms[index] for index in ordered])
    skeleton.CreateBindTransformsAttr([global_transforms[index] for index in ordered])
    motion_paths: dict[str, Sdf.Path] = {}
    for motion in sample['motions']:
        animation = UsdSkel.Animation.Define(stage, f"/Hsin/Character/Rig/{motion['name'].title()}")
        animated = [frame[0] for frame in motion['frames'][0]]
        animation.CreateJointsAttr([paths[mapping[index]] for index in animated])
        animation.CreateScalesAttr(Vt.Vec3hArray([Gf.Vec3h(1) for _ in animated]))
        for frame_index, frame in enumerate(motion['frames']):
            animation.CreateTranslationsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*channel[1:4]) for channel in frame]), frame_index)
            animation.CreateRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(channel[7], Gf.Vec3f(*channel[4:7])) for channel in frame]), frame_index)
        motion_paths[motion['name']] = animation.GetPath()
    UsdSkel.BindingAPI.Apply(skeleton.GetPrim()).CreateAnimationSourceRel().SetTargets([motion_paths['wave']])
    cursor = 0
    for material_index, material in enumerate(sample['materials']):
        faces = sample['faces'][cursor:cursor + material['faceCount']]
        cursor += material['faceCount']
        if not faces or material['diffuse'][3] == 0:
            continue
        vertex_ids = sorted({index for face in faces for index in face})
        vertex_map = {original: local for local, original in enumerate(vertex_ids)}
        vertices = [sample['vertices'][index] for index in vertex_ids]
        mesh = UsdGeom.Mesh.Define(stage, f'/Hsin/Character/Part_{material_index}')
        mesh.CreatePointsAttr([Gf.Vec3f(*vertex['position']) for vertex in vertices])
        mesh.CreateNormalsAttr([Gf.Vec3f(*vertex['normal']) for vertex in vertices])
        mesh.SetNormalsInterpolation('vertex')
        mesh.CreateFaceVertexCountsAttr([3] * len(faces))
        mesh.CreateFaceVertexIndicesAttr([vertex_map[index] for face in faces for index in face])
        UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray, 'vertex').Set([Gf.Vec2f(*vertex['uv']) for vertex in vertices])
        binding = bind_mesh(mesh, skeleton.GetPath(), [mapping[index] for vertex in vertices for index in vertex['joints']],
                            [weight for vertex in vertices for weight in vertex['weights']])
        surface = create_surface(stage, material_index, material, sample['textures'], Path(sample['source']).parent, output, shared_textures)
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(surface)
        names, targets = [], []
        for morph_index, morph in enumerate(sample['morphs']):
            selected = [element for element in morph['elements'] if element['index'] in vertex_map]
            if not selected:
                continue
            shape = UsdSkel.BlendShape.Define(stage, f'{mesh.GetPath()}/Shape_{morph_index}')
            shape.CreatePointIndicesAttr([vertex_map[element['index']] for element in selected])
            shape.CreateOffsetsAttr([Gf.Vec3f(*element['offset']) for element in selected])
            names.append(FACE_NAMES.get(morph['name'], f'morph_{morph_index}'))
            targets.append(shape.GetPath())
        if names:
            binding.CreateBlendShapesAttr(names)
            binding.CreateBlendShapeTargetsRel().SetTargets(targets)
    stage.Export(str(output / 'model.usdc'))
    clips = output / 'Motions'
    clips.mkdir(exist_ok=True)
    for motion in sample['motions']:
        clip = Usd.Stage.CreateNew(str(clips / (motion['name'] + '.usdc')))
        clip.SetTimeCodesPerSecond(30)
        clip.SetEndTimeCode(len(motion['frames']) - 1)
        clip_root = UsdSkel.Root.Define(clip, '/Hsin')
        clip.SetDefaultPrim(clip_root.GetPrim())
        UsdGeom.Xform.Define(clip, '/Hsin/Character/Rig')
        for prim_path in (skeleton.GetPath(), motion_paths[motion['name']]):
            Sdf.CopySpec(stage.GetRootLayer(), prim_path, clip.GetRootLayer(), prim_path)
        UsdSkel.BindingAPI.Apply(clip.GetPrimAtPath(skeleton.GetPath())).CreateAnimationSourceRel().SetTargets([motion_paths[motion['name']]])
        probe = UsdGeom.Mesh.Define(clip, '/Hsin/Character/Probe')
        probe.CreatePointsAttr([Gf.Vec3f(0), Gf.Vec3f(.001, 0, 0), Gf.Vec3f(0, .001, 0)])
        probe.CreateFaceVertexCountsAttr([3])
        probe.CreateFaceVertexIndicesAttr([0, 1, 2])
        bind_mesh(probe, skeleton.GetPath(), [0] * 12, [1, 0, 0, 0] * 3)
        clip.GetRootLayer().Save()
        package_stage(clips / (motion['name'] + '.usdc'), clips / (motion['name'] + '.usdz'))
    package_stage(output / 'model.usdc', output / 'Hsin.usdz')
    (clips / 'manifest.json').write_text(json.dumps({motion['name']: {'duration': motion['duration'], 'looping': motion['looping']} for motion in sample['motions']}))
    (output / 'provenance.json').write_text(json.dumps({'source_sha256': sample['sha256'], 'height_m': 1.65, 'shared_textures': str(shared_textures) if shared_textures else None,
        'limitations': ['SDEF treated as linear skinning', 'MMD outline/toon and real-time cloth not yet ported']}))
    print(f"Exported Hsin: {len(sample['vertices'])} vertices, {len(sample['bones'])} joints")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--shared-textures', type=Path, help='Explicit shared texture root for missing form textures')
    options = parser.parse_args()
    export(options.sample, options.output, options.shared_textures)


if __name__ == '__main__':
    main()
