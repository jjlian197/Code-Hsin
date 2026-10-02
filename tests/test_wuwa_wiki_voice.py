"""验证真实日文网页的音频配对、读音和非战斗筛选。"""
from pathlib import Path
import unittest
from tools.prepare_wuwa_wiki_voice import extract


@unittest.skipUnless(Path("voice/hsin_ja/source/page_ja.html").exists(), "需要本地日文页面快照")
class WuwaWikiVoiceTest(unittest.TestCase):
    def setUp(self):
        self.source = Path("voice/hsin_ja/source/page_ja.html").read_text(encoding="utf-8-sig")

    def test_original_japanese_and_audio_events_are_paired(self):
        manifest = extract(self.source)
        self.assertEqual(manifest["character_id"], 1311)
        first = manifest["selected"][0]
        self.assertEqual(first["key"], "1311101")
        self.assertIn("フラクタル", first["text"])
        self.assertNotIn("自己相似", first["text"])
        self.assertTrue(first["audio_url"].endswith("play_favor_word_xin_sys_toplayer01_ja.opus"))
        events = {row["event"] for row in manifest["selected"]}
        self.assertIn("play_favor_word_xin_com_fly_01", events)
        self.assertIn("play_favor_word_xin_com_scan", events)
        self.assertNotIn("play_favor_word_xin_com_openbox_01", events)
        self.assertNotIn("play_favor_word_xin_atk_atk04_01", events)

    def test_chinese_translation_cannot_be_used_as_japanese_transcript(self):
        with self.assertRaises(ValueError):
            extract(self.source.replace('lang="ja"', 'lang="zh-Hant"', 1))

    def test_invalid_event_path_is_rejected(self):
        with self.assertRaises(ValueError):
            extract(self.source.replace("play_favor_word_xin_sys_toplayer01", "../../invalid"))


if __name__ == "__main__":
    unittest.main()
