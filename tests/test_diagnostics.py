import subprocess
import unittest
from unittest.mock import patch

from triplesense.diagnostics import require_controller_isolation


class ControllerIsolationTests(unittest.TestCase):
    def test_active_steam_blocks_physical_controller_use(self):
        result = subprocess.CompletedProcess([], 0, stdout=b'"steam.exe","1234","Console"\r\n')
        with (
            patch("triplesense.diagnostics.sys.platform", "win32"),
            patch("triplesense.diagnostics.subprocess.run", return_value=result),
            self.assertRaisesRegex(RuntimeError, "Steam is running"),
        ):
            require_controller_isolation()

    def test_no_steam_allows_controller_use(self):
        result = subprocess.CompletedProcess([], 0, stdout=b"INFO: No tasks are running.\r\n")
        with (
            patch("triplesense.diagnostics.sys.platform", "win32"),
            patch("triplesense.diagnostics.subprocess.run", return_value=result),
        ):
            require_controller_isolation()

    def test_failed_process_check_does_not_start_controller(self):
        result = subprocess.CompletedProcess([], 1, stdout=b"")
        with (
            patch("triplesense.diagnostics.sys.platform", "win32"),
            patch("triplesense.diagnostics.subprocess.run", return_value=result),
            self.assertRaisesRegex(RuntimeError, "Could not check"),
        ):
            require_controller_isolation()

    def test_macos_steam_process_blocks_source(self):
        output = b"/usr/libexec/runningboardd\n/Applications/Steam.app/Contents/MacOS/steam_osx\n"
        result = subprocess.CompletedProcess([], 0, stdout=output)
        with (
            patch("triplesense.diagnostics.sys.platform", "darwin"),
            patch("triplesense.diagnostics.subprocess.run", return_value=result) as command,
            self.assertRaisesRegex(RuntimeError, "Steam is running"),
        ):
            require_controller_isolation()
        self.assertNotIn("creationflags", command.call_args.kwargs)

    def test_macos_other_processes_allow_source(self):
        result = subprocess.CompletedProcess(
            [], 0, stdout=b"/Applications/Moonlight.app/Moonlight\n"
        )
        with (
            patch("triplesense.diagnostics.sys.platform", "darwin"),
            patch("triplesense.diagnostics.subprocess.run", return_value=result),
        ):
            require_controller_isolation()
