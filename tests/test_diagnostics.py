import subprocess
import unittest
from unittest.mock import patch

from dualsensedriver.diagnostics import require_controller_isolation


class ControllerIsolationTests(unittest.TestCase):
    def test_active_steam_blocks_physical_controller_use(self):
        result = subprocess.CompletedProcess([], 0, stdout=b'"steam.exe","1234","Console"\r\n')
        with (
            patch("dualsensedriver.diagnostics.os.name", "nt"),
            patch("dualsensedriver.diagnostics.subprocess.run", return_value=result),
            self.assertRaisesRegex(RuntimeError, "Steam is running"),
        ):
            require_controller_isolation()

    def test_no_steam_allows_controller_use(self):
        result = subprocess.CompletedProcess([], 0, stdout=b"INFO: No tasks are running.\r\n")
        with (
            patch("dualsensedriver.diagnostics.os.name", "nt"),
            patch("dualsensedriver.diagnostics.subprocess.run", return_value=result),
        ):
            require_controller_isolation()

    def test_failed_process_check_does_not_start_controller(self):
        result = subprocess.CompletedProcess([], 1, stdout=b"")
        with (
            patch("dualsensedriver.diagnostics.os.name", "nt"),
            patch("dualsensedriver.diagnostics.subprocess.run", return_value=result),
            self.assertRaisesRegex(RuntimeError, "Could not check"),
        ):
            require_controller_isolation()
