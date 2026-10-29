import unittest
from unittest.mock import patch

from ds5bridge.device import BT_PROFILE_GUID, _classify, enumerate_devices


class HidTransportTests(unittest.TestCase):
    def test_macos_opaque_paths_use_bus_metadata(self):
        self.assertEqual(_classify("DevSrvsID:4295001234", 2), "BT")
        self.assertEqual(_classify("DevSrvsID:4295001234", 1), "USB")
        self.assertEqual(_classify("DevSrvsID:4295001234", 0), "?")

    def test_old_windows_path_fallback_remains_available(self):
        self.assertEqual(_classify("hid#" + BT_PROFILE_GUID + "_vid&0002054c"), "BT")
        self.assertEqual(_classify("hid#vid_054c&pid_0ce6"), "USB")

    def test_enumeration_uses_macos_metadata_and_skips_non_gamepad(self):
        records = [
            {
                "path": b"DevSrvsID:123",
                "bus_type": 2,
                "usage_page": 1,
                "usage": 5,
                "serial_number": "aabbccddeeff",
                "product_string": "DualSense",
            },
            {"path": b"DevSrvsID:456", "bus_type": 2, "usage_page": 0xFF00, "usage": 1},
        ]
        with patch("ds5bridge.device.hid.enumerate", return_value=records):
            devices = enumerate_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].transport, "BT")
        self.assertEqual(devices[0].serial, "aabbccddeeff")
