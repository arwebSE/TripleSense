import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from dualsensedriver.app import AppEngine
from dualsensedriver.lan import MAGIC, LanDiscovery
from dualsensedriver.setup import repair_windows


class LanTests(unittest.TestCase):
    def test_discovery_finds_game_without_bonjour_and_uses_sender_address(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        ready = threading.Event()
        found = []

        def notify(kind, value):
            found.append((kind, value))
            ready.set()

        game = LanDiscovery(lambda *args: None, "game-id", port=port, targets=["127.0.0.1"])
        controller = None
        try:
            game.advertise()
            controller = LanDiscovery(notify, "mac-id", port=port, targets=["127.0.0.1"])
            controller.scan()
            self.assertTrue(ready.wait(3), "LAN discovery did not find the listening game PC")
            kind, value = found[0]
            self.assertEqual(kind, "computer")
            self.assertEqual(value["host_id"], "game-id")
            self.assertEqual(value["address"], "127.0.0.1")
        finally:
            if controller:
                controller.close()
            game.close()
        self.assertFalse(game.thread.is_alive())

    def test_unsolicited_discovery_reply_is_ignored(self):
        found = []
        client = LanDiscovery(lambda *args: found.append(args), "mac", targets=["127.0.0.1"])
        try:
            packet = (
                MAGIC
                + json.dumps(
                    {"kind": "game", "token": "wrong", "id": "id", "name": "Unrequested PC"}
                ).encode()
            )
            client._receive_reply(packet, ("192.168.1.20", 3252))
            self.assertEqual(found, [])
        finally:
            client.close()

    def test_setup_repair_leaves_streaming_software_configuration_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "Sunshine/config/sunshine.conf"
            config.parent.mkdir(parents=True)
            original = "controller = enabled\nfps = 60\n"
            config.write_text(original)
            with (
                patch("dualsensedriver.setup.sys.platform", "win32"),
                patch("dualsensedriver.setup.sys.frozen", True, create=True),
                patch("dualsensedriver.setup.ctypes", MagicMock()),
                patch("dualsensedriver.setup.find_usbip", return_value="usbip.exe"),
                patch("dualsensedriver.setup.subprocess.run") as run,
                patch.dict("os.environ", {"ProgramFiles": temporary, "SystemRoot": temporary}),
            ):
                repair_windows()
            self.assertEqual(config.read_text(), original)
            self.assertEqual(list(config.parent.iterdir()), [config])
            self.assertEqual(run.call_count, 4)  # Only DSShine's two firewall rules.
            additions = [call.args[0] for call in run.call_args_list if "add" in call.args[0]]
            self.assertIn("remoteip=localsubnet,100.64.0.0/10", additions[0])
            self.assertIn("remoteip=localsubnet,100.64.0.0/10", additions[1])


class RoamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = object.__new__(AppEngine)
        self.engine.root = Path(self.temporary.name)
        self.engine.preferences = {
            "controller_profile": {
                "host_id": "paired-id",
                "address": "192.168.1.10",
                "credentials": "pinned",
            }
        }

    async def asyncTearDown(self):
        self.temporary.cleanup()

    async def test_changed_ip_updates_existing_profile_without_replacing_identity(self):
        await self.engine.discovered({"host_id": "paired-id", "address": "192.168.1.20"})
        profile = self.engine.preferences["controller_profile"]
        self.assertEqual(profile["address"], "192.168.1.20")
        self.assertEqual(profile["credentials"], "pinned")

    async def test_another_game_pc_cannot_replace_the_saved_address(self):
        await self.engine.discovered({"host_id": "other-id", "address": "192.168.1.20"})
        self.assertEqual(self.engine.preferences["controller_profile"]["address"], "192.168.1.10")

    async def test_discovery_does_not_replace_manual_vpn_address(self):
        profile = self.engine.preferences["controller_profile"]
        profile.update(address="100.97.43.25", manual_address=True)
        await self.engine.discovered({"host_id": "paired-id", "address": "192.168.1.190"})
        self.assertEqual(profile["address"], "100.97.43.25")

    async def test_legacy_pair_does_not_adopt_id_when_tls_verification_fails(self):
        self.engine.preferences["controller_profile"].pop("host_id")
        self.engine.preferences["controller_profile"]["port"] = 3250
        with (
            patch("dualsensedriver.credentials.tls_context", return_value=None),
            patch(
                "asyncio.open_connection",
                new_callable=AsyncMock,
                side_effect=OSError("certificate mismatch"),
            ),
        ):
            await self.engine.discovered(
                {"host_id": "spoofed-id", "address": "192.168.1.10", "dsshine": True}
            )
        self.assertNotIn("host_id", self.engine.preferences["controller_profile"])
