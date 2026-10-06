import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.core.character_package import load_character_package


class CharacterPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "model.pmx"
        self.model.write_bytes(b"PMX fixture")
        digest = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.manifest = {"format": "hsin.character", "version": 1, "name": "测试",
            "model": {"path": "model.pmx", "sha256": digest, "textures": []},
            "rig": "rig.json", "morphs": "morphs.json", "capabilities": {"motions": ["idle", "nod"], "physics": False}}
        self.write("rig.json", {"schema": "hsin.standard-rig", "schemaVersion": 1, "model": {"sha256": digest}})
        self.write("morphs.json", {"version": 1, "aliases": {}, "expressions": {"normal": {}}})
    def write(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding="utf-8")
    def load(self):
        self.write("character.json", self.manifest)
        return load_character_package(self.root / "character.json")
    def test_relative_resources_and_capabilities(self):
        value = self.load()
        self.assertEqual(value["model"], self.model)
        self.assertEqual(value["capabilities"]["motions"], ["idle", "nod"])
    def test_changed_model_rejected(self):
        self.model.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "哈希"):
            self.load()
    def test_missing_texture_rejected(self):
        self.manifest["model"]["textures"] = [{"source": "face.png", "path": "missing.png"}]
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.load()
    def test_uncalibrated_motion_rejected(self):
        self.manifest["capabilities"]["motions"] = ["idle", "side_lying"]
        with self.assertRaisesRegex(ValueError, "能力"):
            self.load()
    def test_invalid_weights_rejected(self):
        self.write("morphs.json", {"version": 1, "aliases": {}, "expressions": {"normal": {}, "happy": {"smile": 2}}})
        with self.assertRaisesRegex(ValueError, "权重"):
            self.load()


if __name__ == "__main__":
    unittest.main()
