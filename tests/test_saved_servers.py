import tempfile
import unittest
from pathlib import Path

from dualsensedriver import saved_servers
from dualsensedriver.credentials import generate_pair
from dualsensedriver.reverse import GameReceiver


class SavedServerTests(unittest.TestCase):
    def test_existing_pair_is_migrated_and_can_be_selected_without_repairing(self):
        first = {"host_id": "first", "address": "100.97.43.25", "credentials": "first-identity"}
        preferences = {"controller_profile": first}
        saved_servers.migrate(preferences)
        saved_servers.remember(
            preferences,
            {"host_id": "second", "address": "100.127.28.249", "credentials": "second-identity"},
        )
        self.assertEqual(len(preferences["servers"]), 2)
        saved_servers.select(preferences, "first")
        self.assertIs(preferences["controller_profile"], first)
        self.assertEqual(preferences["game_address"], "100.97.43.25")
        saved_servers.migrate(preferences)
        self.assertEqual(len(preferences["servers"]), 2)

    def test_forgetting_selected_server_preserves_the_other_pair_and_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preferences = {}
            folders = []
            for identifier in ("first", "second"):
                folder = root / "identities" / ("controller-" + identifier)
                folder.mkdir(parents=True)
                (folder / "key.pem").write_text("test identity")
                folders.append(folder)
                saved_servers.remember(
                    preferences,
                    {"host_id": identifier, "address": "127.0.0.1", "credentials": str(folder)},
                )
            saved_servers.forget(preferences, "second", root)
            self.assertEqual(preferences["selected_server"], "first")
            self.assertTrue(folders[0].exists())
            self.assertFalse(folders[1].exists())
            saved_servers.forget(preferences, "first", root)
            self.assertNotIn("controller_profile", preferences)

    def test_forgetting_server_does_not_delete_credentials_outside_app_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "keep-me"
            outside.mkdir()
            preferences = {}
            saved_servers.remember(
                preferences,
                {"host_id": "first", "address": "127.0.0.1", "credentials": str(outside)},
            )
            saved_servers.forget(preferences, "first", root)
            self.assertTrue(outside.exists())


class ServerStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_online_requires_the_saved_pair_and_does_not_attach_a_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generate_pair(root / "pair")
            generate_pair(root / "other")
            receiver = GameReceiver(
                root / "pair/source", lambda *args: None, port=0, bind="127.0.0.1"
            )
            await receiver.start()
            profile = {
                "address": "127.0.0.1",
                "port": receiver.port,
                "credentials": str(root / "pair/host"),
            }
            try:
                self.assertEqual(await saved_servers.probe(profile), "online")
                self.assertEqual(len(receiver.offers), 0)
                self.assertIsNone(receiver.owned_port)
                wrong = dict(profile, credentials=str(root / "other/host"))
                self.assertEqual(await saved_servers.probe(wrong), "offline")
            finally:
                await receiver.stop()
            self.assertEqual(await saved_servers.probe(profile), "offline")
