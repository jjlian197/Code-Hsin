"""Keep related face deltas in one mesh for RealityKit's skeletal importer."""
from __future__ import annotations

from typing import Any
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdSkel

FACE_NAMES = {'まばたき': 'blink', '笑い': 'smile', 'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o',
              'にこり': 'happy', '口角上げ左': 'corner_left', '口角上げ右': 'corner_right',
              '困る': 'troubled', '悲しい目': 'sad', '怒り': 'angry', 'びっくり': 'surprised',
              'ウィンク': 'wink', 'たれ目': 'relaxed', 'にこり２': 'happy2',
              'FaceRed': 'red', '照れ': 'blush', '星目': 'star', '星目2': 'star2',
              'はぁと': 'heart', 'はぁと2': 'heart2',
              'Left': 'look_right', 'Right': 'look_left', 'Up': 'look_up', 'Down': 'look_down'}
FACE_CHANNELS = frozenset(FACE_NAMES.values())
VERTEX_ATTRIBUTES = ('points', 'normals', 'primvars:st', 'primvars:skel:jointIndices', 'primvars:skel:jointWeights')


def morph_records(stage: Usd.Stage, mesh: UsdGeom.Mesh) -> dict[str, tuple[list[int], list[Any]]]:
    binding = UsdSkel.BindingAPI(mesh.GetPrim())
    records = {}
    for name, target in zip(binding.GetBlendShapesAttr().Get() or [], binding.GetBlendShapeTargetsRel().GetTargets()):
        shape = UsdSkel.BlendShape.Get(stage, target)
        offsets = list(shape.GetOffsetsAttr().Get() or [])
        indices = list(shape.GetPointIndicesAttr().Get() or range(len(offsets)))
        if len(indices) != len(offsets):
            raise ValueError('Invalid sparse face morph: ' + str(target))
        records[str(name)] = (indices, offsets)
    return records


def merge_face_meshes(stage: Usd.Stage) -> dict[str, Any]:
    candidates: list[UsdGeom.Mesh] = []
    for prim in stage.Traverse():
        if prim.GetTypeName() != 'Mesh':
            continue
        mesh = UsdGeom.Mesh(prim)
        records = morph_records(stage, mesh)
        if any(name in FACE_CHANNELS and any(offset.GetLength() > 1e-7 for offset in offsets)
               for name, (_, offsets) in records.items()):
            candidates.append(mesh)
    if not candidates:
        raise ValueError('No facial mesh with nonzero morphs')
    destination = candidates[0]
    destination_binding = UsdSkel.BindingAPI(destination.GetPrim())
    skeleton = destination_binding.GetSkeletonRel().GetTargets()
    records = morph_records(stage, destination)
    merged_names = [str(mesh.GetPath()) for mesh in candidates]
    for source in candidates[1:]:
        binding = UsdSkel.BindingAPI(source.GetPrim())
        if (binding.GetSkeletonRel().GetTargets() != skeleton
                or binding.GetGeomBindTransformAttr().Get() != destination_binding.GetGeomBindTransformAttr().Get()):
            raise ValueError('Face meshes have incompatible skin bindings')
        if UsdGeom.Xformable(source).GetLocalTransformation() != UsdGeom.Xformable(destination).GetLocalTransformation():
            raise ValueError('Face meshes have incompatible transforms')
        vertex_offset = len(destination.GetPointsAttr().Get())
        face_offset = len(destination.GetFaceVertexCountsAttr().Get())
        for name in VERTEX_ATTRIBUTES:
            target_attribute = destination.GetPrim().GetAttribute(name)
            source_attribute = source.GetPrim().GetAttribute(name)
            if not target_attribute.HasValue() or not source_attribute.HasValue():
                raise ValueError('Missing face vertex attribute: ' + name)
            target_attribute.Set(list(target_attribute.Get()) + list(source_attribute.Get()))
        destination.GetFaceVertexCountsAttr().Set(list(destination.GetFaceVertexCountsAttr().Get()) + list(source.GetFaceVertexCountsAttr().Get()))
        destination.GetFaceVertexIndicesAttr().Set(list(destination.GetFaceVertexIndicesAttr().Get()) +
                                                  [int(index) + vertex_offset for index in source.GetFaceVertexIndicesAttr().Get()])
        for name, (indices, offsets) in morph_records(stage, source).items():
            joined_indices, joined_offsets = records.setdefault(name, ([], []))
            joined_indices.extend(int(index) + vertex_offset for index in indices)
            joined_offsets.extend(offsets)
        material, _ = UsdShade.MaterialBindingAPI(source.GetPrim()).ComputeBoundMaterial()
        subset = UsdGeom.Subset.Define(stage, destination.GetPath().AppendChild('Material_' + source.GetPrim().GetName()))
        subset.CreateElementTypeAttr(UsdGeom.Tokens.face)
        subset.CreateFamilyNameAttr('materialBind')
        subset.CreateIndicesAttr(list(range(face_offset, len(destination.GetFaceVertexCountsAttr().Get()))))
        if material:
            UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(material)
        # Preserve any existing material subsets, including Aemeath's merged eyelash texture.
        for source_subset in UsdGeom.Subset.GetAllGeomSubsets(source):
            copied = UsdGeom.Subset.Define(stage, destination.GetPath().AppendChild('Subset_' + source.GetPrim().GetName() + '_' + source_subset.GetPrim().GetName()))
            copied.CreateElementTypeAttr(UsdGeom.Tokens.face)
            copied.CreateFamilyNameAttr('materialBind')
            copied.CreateIndicesAttr([int(index) + face_offset for index in source_subset.GetIndicesAttr().Get()])
            subset_material, _ = UsdShade.MaterialBindingAPI(source_subset.GetPrim()).ComputeBoundMaterial()
            if subset_material:
                UsdShade.MaterialBindingAPI.Apply(copied.GetPrim()).Bind(subset_material)
        stage.RemovePrim(source.GetPath())
    targets = []
    for ordinal, (name, (indices, offsets)) in enumerate(records.items()):
        shape = UsdSkel.BlendShape.Define(stage, destination.GetPath().AppendChild(f'UnifiedShape_{ordinal}'))
        shape.CreatePointIndicesAttr(indices)
        shape.CreateOffsetsAttr(offsets)
        targets.append(shape.GetPath())
    destination_binding.CreateBlendShapesAttr(list(records))
    destination_binding.CreateBlendShapeTargetsRel().SetTargets(targets)
    UsdGeom.Subset.SetFamilyType(destination, 'materialBind', UsdGeom.Tokens.nonOverlapping)
    # RealityKit exposes a weight set for the rig but only animates its first skinned
    # morph mesh. Co-locating eyelids, lashes and mouth interiors preserves their deltas.
    return {'destination': str(destination.GetPath()), 'merged': merged_names,
            'vertices': len(destination.GetPointsAttr().Get()),
            'channels': {name: len(records.get(name, ([], []))[0]) for name in sorted(FACE_CHANNELS)}}
