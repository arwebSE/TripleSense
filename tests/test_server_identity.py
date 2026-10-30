import json
import tempfile
import unittest
from pathlib import Path

from dualsensedriver.app_support import load_preferences
from dualsensedriver.credentials import generate_pair
from dualsensedriver.server_identity import remember, load


class ServerIdentityTests(unittest.TestCase):
    def test_restart_restores_accepted_identity_even_if_ui_preferences_are_older(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "identities/game-accepted"
            generate_pair(identity)
            credentials = identity / "credentials"
            (identity / "source").rename(credentials)
            remember(root, credentials, "Mac")
            (root / "settings.json").write_text(json.dumps({"game_credentials": "old", "audio": True}))
            restored = load_preferences(root)
            self.assertEqual(Path(restored["game_credentials"]), credentials.resolve())
            self.assertEqual(restored["controller_name"], "Mac")
            self.assertTrue(restored["audio"])

    def test_changed_ca_and_paths_outside_identities_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "identities/game-accepted"
            generate_pair(identity)
            credentials = identity / "credentials"
            (identity / "source").rename(credentials)
            remember(root, credentials, "Mac")
            (credentials / "ca.pem").write_text("changed")
            self.assertIsNone(load(root))
            with self.assertRaises(ValueError):
                remember(root, root.parent, "Other")
