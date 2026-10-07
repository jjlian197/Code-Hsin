"""原生麦克风格式转换，不打开真实设备。"""
from array import array
import unittest
from src.core.audio_pcm import SpeechPCMConverter


class SpeechPCMTests(unittest.TestCase):
    def test_native_float_44100_chunks_have_same_output_and_duration(self):
        recording = array('f', [0.25] * 44100).tobytes()
        expected = SpeechPCMConverter(44100, 1, 'Float').feed(recording)
        converter = SpeechPCMConverter(44100, 1, 'Float')
        actual = b''.join(converter.feed(recording[offset:offset + 997]) for offset in range(0, len(recording), 997))
        self.assertEqual(actual, expected)
        self.assertAlmostEqual(len(actual) / 2, 16000, delta=1)
        self.assertEqual(set(array('h', actual)), {8192})

    def test_stereo_mix_and_int16_passthrough_amplitude(self):
        stereo = array('h', [1000, -1000] * 4800).tobytes()
        self.assertEqual(set(array('h', SpeechPCMConverter(48000, 2, 'Int16').feed(stereo))), {0})
        mono = array('h', [1234] * 1600).tobytes()
        self.assertEqual(set(array('h', SpeechPCMConverter(16000, 1, 'Int16').feed(mono))), {1234})

    def test_invalid_samples_are_safe_and_float_clipped(self):
        converted = SpeechPCMConverter(16000, 1, 'Float').feed(array('f', [2, -2, float('nan'), 0]).tobytes())
        self.assertEqual(list(array('h', converted)), [32767, -32768, 0])


if __name__ == '__main__':
    unittest.main()
