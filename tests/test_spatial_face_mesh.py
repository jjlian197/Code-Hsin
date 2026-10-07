from __future__ import annotations
import unittest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdSkel
from tools.export_hsin_usdz import bind_mesh
from tools.spatial_face_mesh import merge_face_meshes, morph_records


class SpatialFaceTests(unittest.TestCase):
    def test_face_lashes_and_mouth_keep_deltas_skin_and_materials(self) -> None:
        stage = Usd.Stage.CreateInMemory()
        skeleton = UsdSkel.Skeleton.Define(stage, '/Character/Rig/Skeleton')
        skeleton.CreateJointsAttr(['head'])
        for ordinal, (name, channel) in enumerate([('Face', 'blink'), ('Lashes', 'blink'), ('Teeth', 'a'), ('Body', None)]):
            mesh = UsdGeom.Mesh.Define(stage, '/Character/' + name)
            mesh.CreatePointsAttr([Gf.Vec3f(ordinal, index, 0) for index in range(3)])
            mesh.CreateNormalsAttr([Gf.Vec3f(0, 0, 1)] * 3)
            UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray, 'vertex').Set([Gf.Vec2f(0)] * 3)
            mesh.CreateFaceVertexCountsAttr([3]); mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
            binding = bind_mesh(mesh, skeleton.GetPath(), [0] * 12, [1, 0, 0, 0] * 3)
            material = UsdShade.Material.Define(stage, '/Materials/' + name)
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
            if channel:
                shape = UsdSkel.BlendShape.Define(stage, str(mesh.GetPath()) + '/Shape')
                shape.CreatePointIndicesAttr([0]); shape.CreateOffsetsAttr([Gf.Vec3f(0, -0.1, 0)])
                binding.CreateBlendShapesAttr([channel]); binding.CreateBlendShapeTargetsRel().SetTargets([shape.GetPath()])
        report = merge_face_meshes(stage)
        self.assertEqual(report['vertices'], 9)
        face = UsdGeom.Mesh.Get(stage, '/Character/Face')
        records = morph_records(stage, face)
        self.assertEqual(records['blink'][0], [0, 3])
        self.assertEqual(records['a'][0], [6])
        self.assertEqual(len(face.GetPrim().GetAttribute('primvars:skel:jointWeights').Get()), 36)
        self.assertTrue(stage.GetPrimAtPath('/Character/Body'))
        self.assertFalse(stage.GetPrimAtPath('/Character/Lashes'))
        self.assertEqual(len(UsdGeom.Subset.GetAllGeomSubsets(face)), 2)
        materials = [str(UsdShade.MaterialBindingAPI(subset.GetPrim()).ComputeBoundMaterial()[0].GetPath())
                     for subset in UsdGeom.Subset.GetAllGeomSubsets(face)]
        self.assertEqual(materials, ['/Materials/Lashes', '/Materials/Teeth'])
        # Re-running conversion must not double topology or sparse morph entries.
        self.assertEqual(merge_face_meshes(stage)['vertices'], 9)
        self.assertEqual(morph_records(stage, face)['blink'][0], [0, 3])
