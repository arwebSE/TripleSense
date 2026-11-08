import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from triplesense.app_support import load_preferences
from triplesense.credentials import generate_pair
from triplesense.server_identity import load, remember


class ServerIdentityTests(unittest.TestCase):
    def test_redirected_identity_directory_does_not_need_to_share_the_resolved_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "logical"
            physical = Path(temporary) / "redirected"
            root.mkdir()
            identity = root / "identities/game-accepted"
            generate_pair(identity)
            (identity / "source").rename(identity / "credentials")
            original_resolve = Path.resolve

            def redirected(path, *args, **kwargs):
                if path.is_relative_to(root / "identities"):
                    path = physical / path.relative_to(root)
                return original_resolve(path, *args, **kwargs)

            with patch.object(Path, "resolve", redirected):
                remember(root, root / "identities/game-accepted/credentials", "Mac")
                restored = load(root)
            self.assertEqual(Path(restored["game_credentials"]), identity / "credentials")

    def test_restart_restores_accepted_identity_even_if_ui_preferences_are_older(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "identities/game-accepted"
            generate_pair(identity)
            credentials = identity / "credentials"
            (identity / "source").rename(credentials)
            remember(root, credentials, "Mac")
            (root / "settings.json").write_text(
                json.dumps({"game_credentials": "old", "audio": True})
            )
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
