import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from dualsensedriver.credentials import generate_pair
from dualsensedriver.runtime import attached_port, detach_owned


class RuntimeTests(unittest.TestCase):
    def test_owned_port_must_be_positive_terse_output(self):
        self.assertEqual(attached_port("3"), 3)
        for invalid in ("0", "-1", "all", "3\n4", "successfully attached to port 3", "99999"):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                attached_port(invalid)

    def test_credentials_never_overwrite_an_existing_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pair"
            generate_pair(path)
            original = (path / "host" / "key.pem").read_bytes()
            with self.assertRaises(FileExistsError):
                generate_pair(path)
            self.assertEqual((path / "host" / "key.pem").read_bytes(), original)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_detach_verifies_both_location_and_session_identity(self):
        listing = (
            "Imported USB devices\n====================\n"
            "Port 01: device in use at High Speed(480Mbps)\n"
            " -> usbip://127.0.0.1:3247/1-1\n -> serial: DS5D123456789ab\n"
            " -> mode: zero-copy\n"
            "Port 02: device in use at High Speed(480Mbps)\n"
            " -> usbip://other:3240/1-1\n -> serial: unrelated\n"
        )
        with patch("dualsensedriver.runtime.run_usbip", new_callable=AsyncMock) as command:
            command.side_effect = [listing, "port 1 is successfully detached"]
            self.assertTrue(await detach_owned("usbip.exe", 1, 3247, "DS5D123456789ab"))
            self.assertEqual(command.await_args.args, ("usbip.exe", "detach", "--port", "1"))

    async def test_reassigned_or_absent_ports_are_left_alone(self):
        listing = "Port 01: device in use\n -> usbip://other:3240/1-1\n -> serial: other\n"
        for output in (listing, ""):
            with patch("dualsensedriver.runtime.run_usbip", new_callable=AsyncMock) as command:
                command.return_value = output
                self.assertFalse(await detach_owned("usbip.exe", 1, 3247, "DS5D123456789ab"))
                command.assert_awaited_once_with("usbip.exe", "port")
