import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleOptionButton,
)

from dualsensedriver.app import Window


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.window = Window(Path(self.temporary.name), smoke_test=True)
        self.offer_patch = patch.object(
            self.window.engine, "_create_pairing_offer", new_callable=AsyncMock
        )
        self.offer_patch.start()
        self.window.show()
        self.application.processEvents()

    def tearDown(self):
        self.window.engine.submit(self.window.engine.shutdown()).result(10)
        self.window.engine.loop.call_soon_threadsafe(self.window.engine.loop.stop)
        self.window.engine.thread.join(2)
        self.window.quitting = True
        self.window.close()
        self.application.processEvents()
        self.temporary.cleanup()
        self.offer_patch.stop()

    def test_closing_main_window_quits_instead_of_hiding(self):
        window = self.window
        self.assertFalse(hasattr(window, "tray"))
        event = QCloseEvent()
        with patch.object(window, "quit") as quit_app:
            window.closeEvent(event)
        quit_app.assert_called_once_with()
        self.assertFalse(event.isAccepted())
        self.assertTrue(window.isVisible())  # Remain visible while shutdown cleans up.

    def test_server_address_links_copy_only_the_clicked_ip(self):
        window = self.window
        window.current_role = "game"
        window._show_pair_page()
        self.assertEqual(window.pair_addresses.textFormat(), Qt.TextFormat.RichText)
        window.pair_addresses.linkActivated.emit("100.97.43.25")
        self.assertEqual(self.application.clipboard().text(), "100.97.43.25")
        window.addresses.linkActivated.emit("192.168.1.190")
        self.assertEqual(self.application.clipboard().text(), "192.168.1.190")

    def test_main_window_has_no_scroll_container_or_dropdown(self):
        self.assertEqual(self.window.findChildren(QScrollArea), [])
        self.assertEqual(self.window.findChildren(QComboBox), [])
        self.assertIsNot(self.window.details.window(), self.window)
        self.assertIsNot(self.window.login.window(), self.window)
        self.assertTrue(self.window.audio.isChecked())
        self.assertLessEqual(self.window.audio_box.sizeHint().height(), 40)

    @unittest.skipUnless(sys.platform == "win32", "Windows shell properties")
    def test_native_taskbar_properties_use_our_icon_and_relaunch_command(self):
        import ctypes

        from dualsensedriver.windows_taskbar import read_window_identity, set_window_identity

        # Other layout tests use Qt's offscreen plugin, whose IDs are not HWNDs.
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.restype = ctypes.c_void_p
        hwnd = user32.CreateWindowExW(
            0, "STATIC", "DSShine shell test", 0, 0, 0, 32, 32, None, None, None, None
        )
        self.assertTrue(hwnd)
        try:
            set_window_identity(hwnd)
            values = read_window_identity(hwnd)
            self.assertEqual(values["app_id"], "DSShine.Development")
            self.assertEqual(values["display_name"], "DSShine")
            self.assertTrue(values["relaunch_icon"].endswith("dsshine.ico,0"))
            self.assertTrue(Path(values["relaunch_icon"][:-2]).is_file())
            self.assertIn("-m dualsensedriver.app", values["relaunch_command"])
        finally:
            user32.DestroyWindow(ctypes.c_void_p(hwnd))

    def test_discovery_updates_preserve_manual_address_and_selected_identity(self):
        window = self.window
        window.manual_address.setText("192.168.1.190")
        window.computers = {
            "game": {"id": "game", "name": "Server", "address": "192.168.1.190", "dsshine": True}
        }
        window._refresh_computers()
        window.hosts.setCurrentRow(0)
        window.computers["game"]["address"] = "192.168.1.191"
        window._refresh_computers()
        self.assertEqual(window.manual_address.text(), "192.168.1.190")
        self.assertEqual(window.hosts.currentItem().data(Qt.ItemDataRole.UserRole)["id"], "game")
        window.computers.clear()
        window._refresh_computers()
        window._refresh_computers()  # Empty placeholder must not become a selected server.
        self.assertIsNone(window.hosts.currentItem())

    def test_connection_and_pairing_fit_at_minimum_window_size(self):
        window = self.window
        window.resize(640, 440)
        for role in ("game", "controller"):
            window.current_role = role
            window._show_role()
            # Select screens without issuing network or pairing operations.
            for page in (window.connection_page, window.pair_page):
                window.server_pair.setVisible(role == "game")
                window.client_pair.setVisible(role == "controller")
                window.pages.setCurrentWidget(page)
                window._fit_page()
                self.application.processEvents()
                self.assertLessEqual(window.height(), 590)
                if page is window.connection_page:
                    self.assertLessEqual(window.height(), 540)
                self.assertGreater(window.pages.height(), 200)
                for child in page.findChildren(QPushButton):
                    if child.isVisible():
                        position = child.mapTo(page, child.rect().bottomRight())
                        self.assertLessEqual(
                            position.y(),
                            page.height(),
                            (role, page is window.pair_page, child.text()),
                        )
                if page is window.pair_page and role == "controller":
                    window.pair_error.setText("Server is unreachable. Check network permissions.")
                    self.application.processEvents()
                    choices_bottom = window.manual_address.mapTo(
                        page, window.manual_address.rect().bottomLeft()
                    ).y()
                    code_top = window.code.mapTo(page, window.code.rect().topLeft()).y()
                    self.assertLess(choices_bottom, code_top)

    def test_pairing_code_never_enters_logs(self):
        self.window.on_event("pair_code", "1234")
        self.assertEqual(self.window.pin.text(), "1234")
        self.assertEqual(self.application.clipboard().text(), "1234")
        self.application.clipboard().setText("other")
        self.window.copy_code.click()
        self.assertEqual(self.application.clipboard().text(), "1234")
        self.window.on_event("pair_code", "")
        self.assertFalse(self.window.copy_code.isEnabled())
        self.assertNotIn("1234", self.window.details.toPlainText())

    def test_pairing_timeout_stays_visible_and_reenables_retry(self):
        window = self.window
        window.current_role = "controller"
        window._show_role()
        window._open_pairing()
        window.manual_address.setText("100.97.43.25")
        window.code.setText("1234")
        with patch.object(window.engine, "pair", new_callable=AsyncMock) as pair:
            pair.side_effect = TimeoutError()
            window._pair_client()
            self.assertEqual(window.pair_submit.text(), "Connecting…")
            self.assertFalse(window.pair_submit.isEnabled())
            deadline = time.monotonic() + 2
            while window.busy and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.01)
        self.assertTrue(window.pair_submit.isEnabled())
        self.assertEqual(window.pair_submit.text(), "Connect")
        self.assertEqual(window.pair_error.property("tone"), "danger")
        self.assertIn("VPN", window.pair_error.text())
        self.assertIs(window.pages.currentWidget(), window.pair_page)
        self.assertNotIn("1234", window.details.toPlainText())

    def test_connected_status_and_disconnect_action_have_different_intents(self):
        window = self.window
        window.current_role = "controller"
        window.preferences["controller_profile"] = {"name": "Server"}
        window.engine.connection = object()
        try:
            window.on_event("connected", "")
            self.assertEqual(window.status.property("tone"), "success")
            self.assertEqual(window.connect_button.text(), "Disconnect")
            self.assertEqual(window.connect_button.property("intent"), "danger")
            window.on_event("error", "Connect call failed")
            self.assertEqual(window.status.property("tone"), "danger")
        finally:
            window.engine.connection = None

    def test_connected_audio_click_is_read_only_and_explains_why(self):
        window = self.window
        window.current_role = "controller"
        window._show_role()
        window.engine.connection = object()
        try:
            window.on_event("connected", "")
            previous = window.audio.isChecked()
            window.audio.click()
            self.assertEqual(window.audio.isChecked(), previous)
            self.assertFalse(window.audio.isEnabled())
            self.assertEqual(window.audio.toolTip(), "Disconnect to change audio")
            self.assertTrue(window.audio_status.isHidden())
        finally:
            window.engine.connection = None
            window._update_actions()
        self.assertFalse(window.audio.property("locked"))
        self.assertTrue(window.audio_status.isHidden())

    def test_checked_indicator_contains_white_checkmark(self):
        window = self.window
        window.current_role = "controller"
        window._show_role()
        self.application.processEvents()
        option = QStyleOptionButton()
        window.audio.initStyleOption(option)
        rect = window.audio.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, window.audio
        )
        image = window.audio.grab().toImage()
        scale = image.devicePixelRatio()
        whites = 0
        for y in range(int(rect.top() * scale), int((rect.bottom() + 1) * scale)):
            for x in range(int(rect.left() * scale), int((rect.right() + 1) * scale)):
                color = image.pixelColor(x, y)
                whites += int(min(color.red(), color.green(), color.blue()) > 230)
        self.assertGreater(whites, 4)

    def test_mode_change_requires_disconnect_then_persists_new_mode(self):
        window = self.window
        if sys.platform != "win32":
            self.assertTrue(window.mode_button.isHidden())
            self.assertIsNone(window.mode_page)
            return
        window.current_role = "game"
        window.preferences["role"] = "game"
        window.preferences["game_credentials"] = "fixture"
        window._show_role()
        receiver = SimpleNamespace(stop=AsyncMock())
        window.engine.receiver = receiver
        window.busy = False
        window._update_actions()
        self.assertFalse(window.mode_button.isEnabled())
        self.assertEqual(window.mode_button.toolTip(), "Disconnect to change mode")
        window._role_changed("controller")
        self.assertEqual(window.current_role, "game")
        window.connect_button.click()
        self._wait_for_mode("game")
        receiver.stop.assert_awaited_once()
        window.preferences.pop("game_credentials")
        self.assertTrue(window.mode_button.isEnabled())
        window.mode_button.click()
        self.assertIs(window.pages.currentWidget(), window.mode_page)
        window.client.click()
        self._wait_for_mode("controller")
        self.assertIsNone(window.engine.receiver)
        self.assertTrue(window.role_caption.text().startswith("CLIENT"))
        self.assertIs(window.pages.currentWidget(), window.pair_page)
        settings = json.loads((window.root / "settings.json").read_text())
        self.assertEqual(settings["role"], "controller")
        if sys.platform == "win32":
            window.mode_button.click()
            window.server.click()
            self._wait_for_mode("game")
            self.assertTrue(window.role_caption.text().startswith("SERVER"))

    def test_platform_mode_selection_matches_supported_server_backend(self):
        if sys.platform == "win32":
            self.assertIsNotNone(self.window.mode_page)
            self.assertFalse(self.window.mode_button.isHidden())
        else:
            self.assertIsNone(self.window.mode_page)
            self.assertTrue(self.window.mode_button.isHidden())
            self.assertEqual(self.window.current_role, "controller")

    def _wait_for_mode(self, role):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.application.processEvents()
            if self.window.preferences.get("role") == role and not self.window.busy:
                return
            time.sleep(0.01)
        self.fail("Mode selection did not complete")
