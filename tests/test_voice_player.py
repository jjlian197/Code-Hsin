"""检查真实 PCM 驱动音量计算，静音和不同采样格式保持同样含义。"""
from array import array
import math
import unittest
from PyQt6.QtMultimedia import QAudioFormat
from src.core.voice_player import pcm_level


class PcmLevelTest(unittest.TestCase):
    def test_silence_closes_mouth_and_speech_has_level(self):
        self.assertEqual(pcm_level(bytes(3200), QAudioFormat.SampleFormat.Int16), 0)
        speech = array("h", [int(9000 * math.sin(i / 8)) for i in range(1600)]).tobytes()
        self.assertGreater(pcm_level(speech, QAudioFormat.SampleFormat.Int16), 0.5)

    def test_formats_have_equivalent_amplitude(self):
        value16 = pcm_level(array("h", [3277] * 100).tobytes(), QAudioFormat.SampleFormat.Int16)
        value32 = pcm_level(array("i", [214748365] * 100).tobytes(), QAudioFormat.SampleFormat.Int32)
        value_float = pcm_level(array("f", [0.1] * 100).tobytes(), QAudioFormat.SampleFormat.Float)
        self.assertAlmostEqual(value16, value32, places=3)
        self.assertAlmostEqual(value32, value_float, places=3)
        self.assertEqual(pcm_level(bytes([128] * 100), QAudioFormat.SampleFormat.UInt8), 0)


if __name__ == "__main__":
    unittest.main()
