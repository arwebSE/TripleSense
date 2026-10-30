import unittest
import zlib
from types import SimpleNamespace

from dualsensedriver.macos_bluetooth import NativeHID


def packet(kind, marker):
    data = b"\xa1\x31" + bytes([kind, marker]) + bytes(71)
    return data + (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little")


class NativeBluetoothFramingTests(unittest.TestCase):
    def test_split_and_coalesced_microphone_and_control_reports(self):
        transport = NativeHID(SimpleNamespace())
        control, mic = packet(1, 42), packet(2, 17)
        transport._accept_input(control[:12])
        self.assertTrue(transport._input.empty())
        transport._accept_input(control[12:] + mic + control[:30])
        self.assertEqual(transport.read(78, 1), control[1:])
        self.assertEqual(transport.read(78, 1), mic[1:])
        transport._accept_input(control[30:])
        self.assertEqual(transport.read(78, 1), control[1:])
        self.assertEqual(transport._buffer, b"")

    def test_bad_crc_does_not_turn_noise_into_microphone_audio(self):
        transport = NativeHID(SimpleNamespace())
        corrupt = bytearray(packet(2, 10))
        corrupt[-1] ^= 1
        good = packet(2, 20)
        transport._accept_input(b"noise" + corrupt + good)
        self.assertEqual(transport.read(78, 1), good[1:])
        self.assertTrue(transport._input.empty())

    def test_input_backlog_cannot_block_feature_responses(self):
        transport = NativeHID(SimpleNamespace())
        transport._accept_input(packet(1, 1) * 2048 + packet(2, 2))
        self.assertEqual(transport._input.qsize(), 2048)
        reports = [transport.read(78, 1) for _ in range(2048)]
        self.assertEqual(reports[-1], packet(2, 2)[1:])


if __name__ == "__main__":
    unittest.main()
