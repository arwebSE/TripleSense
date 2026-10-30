import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from dualsensedriver.app import AppEngine
from dualsensedriver.lan import MAGIC, LanDiscovery
from dualsensedriver.setup import disable_forwarding


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

    def test_sunshine_setup_preserves_other_settings_and_removes_duplicates(self):
        text = "# settings\ncontroller = enabled\nfps = 60\ncontroller=enabled\n"
        changed = disable_forwarding(text)
        self.assertEqual(changed, "# settings\ncontroller = disabled\nfps = 60\n")
        self.assertEqual(disable_forwarding(changed), changed)


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
