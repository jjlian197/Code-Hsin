import tempfile
import unittest
from pathlib import Path

try:
    from tools.convert_cmu_motion import read_asf, read_amc, forward_kinematics
except ImportError:
    read_asf = None


@unittest.skipIf(read_asf is None, "离线动作工具需要 requirements-motion.txt")
class CmuMotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        asf = self.directory / "test.asf"
        asf.write_text(""":version 1.10
:units
mass 1
length .45
angle deg
:root
order TX TY TZ RX RY RZ
axis XYZ
position 0 0 0
orientation 0 0 0
:bonedata
begin
id 1
name limb
direction 0 1 0
length 2
axis 0 0 90 XYZ
dof rx
end
begin
id 2
name tip
direction 1 0 0
length 1
axis 0 0 0 XYZ
end
:hierarchy
begin
root limb
limb tip
end
""", encoding="ascii")
        self.skeleton = read_asf(asf)

    def amc(self, contents):
        path = self.directory / "test.amc"
        path.write_text(contents, encoding="ascii")
        return read_amc(path, self.skeleton)

    def test_axis_basis_and_parent_rotation(self):
        frames = self.amc(":FULLY-SPECIFIED\n:DEGREES\n1\nroot 1 2 3 0 0 0\nlimb 90\n")
        result = forward_kinematics(self.skeleton, frames)
        for actual, expected in zip(result["positions"]["limb"][0], (1, 4, 3)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(result["positions"]["tip"][0], (1, 4, 2)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(result["fps"], 120)
        self.assertEqual(result["units"], "asf_native")

    def test_root_world_rotation(self):
        result = forward_kinematics(self.skeleton, self.amc("1\nroot 0 0 0 0 0 90\nlimb 0\n"))
        for actual, expected in zip(result["positions"]["limb"][0], (-2, 0, 0)):
            self.assertAlmostEqual(actual, expected)

    def test_missing_channels_rejected(self):
        with self.assertRaisesRegex(ValueError, "完整通道"):
            self.amc("1\nroot 0 0 0 0 0 0\n")

    def test_nonfinite_channels_rejected(self):
        with self.assertRaisesRegex(ValueError, "通道无效"):
            self.amc("1\nroot 0 0 0 0 0 0\nlimb nan\n")

    def test_nonsequential_frames_rejected(self):
        with self.assertRaisesRegex(ValueError, "帧号不连续"):
            self.amc("2\nroot 0 0 0 0 0 0\nlimb 0\n")
