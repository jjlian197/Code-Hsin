"""验证库街区真实快照的音频/台词配对及异常响应处理。"""
import copy
import json
import unittest
from pathlib import Path
from tools.prepare_kurobbs_voice import extract


@unittest.skipUnless(Path("voice/hsin_zh/source/entry.json").exists(), "需要本地库街区快照")
class KurobbsVoiceTest(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(Path("voice/hsin_zh/source/entry.json").read_text(encoding="utf-8"))
        self.components = self.payload["data"]["content"]["modules"][4]["components"]

    def test_real_snapshot_pairs_and_exploration(self):
        manifest = extract(self.payload, "1543050481616060416")
        self.assertEqual(len(manifest["selected"]), 36)
        self.assertEqual(len(manifest["excluded_combat"]), 38)
        titles = {r["title"] for r in manifest["selected"]}
        self.assertIn("滑翔", titles)
        self.assertIn("感知", titles)
        self.assertNotIn("获得补给1", titles)
        row = next(r for r in manifest["selected"] if r["title"] == "入队2")
        original = next(r for r in self.components[0]["mediaTabs"][0]["mediaList"] if r["audioTitle"] == "入队2")
        self.assertEqual((row["key"], row["audio_url"], row["text"]), (original["id"], original["playUrl"], original["content"]))

    def test_missing_text_or_audio_cannot_enter_training(self):
        rows = self.components[0]["mediaTabs"][0]["mediaList"]
        rows[0]["content"] = ""
        rows[1]["playUrl"] = ""
        manifest = extract(self.payload, "1543050481616060416")
        self.assertEqual(len(manifest["selected"]), 34)
        self.assertEqual(len(manifest["missing_text"]), 1)
        self.assertEqual(len(manifest["missing_audio"]), 1)

    def test_unexpected_media_source_rejected(self):
        self.components[0]["mediaTabs"][0]["mediaList"][0]["playUrl"] = "https://example.com/file.wav"
        with self.assertRaises(ValueError):
            extract(self.payload, "1543050481616060416")

    def test_duplicate_audio_id_rejected(self):
        rows = self.components[0]["mediaTabs"][0]["mediaList"]
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaises(ValueError):
            extract(self.payload, "1543050481616060416")


if __name__ == "__main__":
    unittest.main()
