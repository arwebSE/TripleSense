import hashlib
import io
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from dualsensedriver import updates as U


def release_data(name="TripleSense-Setup-1.2.3-Windows-x64.exe", payload=b"installer"):
    return {
        "tag_name": "v1.2.3",
        "prerelease": False,
        "draft": False,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": len(payload),
                "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "url": U.API + "/releases/assets/42",
            }
        ],
    }


class UpdateTests(unittest.TestCase):
    def test_numeric_version_comparison_never_downgrades(self):
        data = release_data()
        self.assertIsNone(U.select_release(data, "1.10.0", system="win32", machine="amd64"))
        self.assertIsNotNone(U.select_release(data, "1.2.2", system="win32", machine="amd64"))
        self.assertIsNone(U.select_release(data, "1.2.3", system="win32", machine="amd64"))

    def test_platform_assets_are_selected_explicitly(self):
        for system, machine, name in (
            ("win32", "AMD64", "TripleSense-Setup-1.2.3-Windows-x64.exe"),
            ("darwin", "arm64", "TripleSense-macOS.dmg"),
            ("linux", "aarch64", "TripleSense-1.2.3-Linux-arm64.deb"),
            ("linux", "x86_64", "TripleSense-1.2.3-Linux-amd64.deb"),
        ):
            with self.subTest(system=system):
                result = U.select_release(
                    release_data(name), "1.0.0", system=system, machine=machine.lower()
                )
                self.assertEqual(result.name, name)
        with self.assertRaises(U.UpdateError):
            U.select_release(release_data(), "1.0.0", system="darwin", machine="x86_64")

    def test_prereleases_and_drafts_are_not_offered(self):
        for field in ("draft", "prerelease"):
            data = release_data()
            data[field] = True
            self.assertIsNone(U.select_release(data, "1.0.0"))

    def test_unverifiable_or_foreign_asset_is_rejected(self):
        for field, bad in (
            ("digest", None),
            ("size", 0),
            ("url", "https://example.com/update.exe"),
        ):
            data = release_data()
            data["assets"][0][field] = bad
            with self.subTest(field=field), self.assertRaises(U.UpdateError):
                U.select_release(data, "1.0.0", system="win32", machine="amd64")

    def test_download_verifies_contents_and_cleans_partial_files(self):
        release = U.select_release(release_data(), "1.0.0", system="win32", machine="amd64")
        for payload, succeeds in (
            (b"installer", True),
            (b"corrupted", False),
            (b"too-long-installer", False),
        ):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as folder:
                with patch.object(U, "open_github", return_value=io.BytesIO(payload)):
                    if succeeds:
                        path = U.download_release(release, folder)
                        self.assertEqual(path.read_bytes(), b"installer")
                    else:
                        with self.assertRaises(U.UpdateError):
                            U.download_release(release, folder)
                        self.assertEqual(list(Path(folder).iterdir()), [])

    def test_redirect_never_leaks_github_token(self):
        request = urllib.request.Request(
            U.API + "/releases/assets/42", headers={"Authorization": "Bearer secret"}
        )
        result = U.SafeRedirect().redirect_request(
            request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/file"
        )
        self.assertFalse(result.has_header("Authorization"))
        with self.assertRaises(U.UpdateError):
            U.SafeRedirect().redirect_request(
                request, None, 302, "Found", {}, "http://example.com/file"
            )

    def test_source_checkout_cannot_launch_installer(self):
        with patch.object(U.sys, "frozen", False, create=True), self.assertRaises(U.UpdateError):
            U.launch_installer(Path("installer.exe"), Path("."))
