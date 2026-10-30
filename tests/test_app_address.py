import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
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
        self.window.show()
        self.application.processEvents()

    def tearDown(self):
        self.window.engine.submit(self.window.engine.shutdown()).result(10)
        self.window.engine.loop.call_soon_threadsafe(self.window.engine.loop.stop)
        self.window.engine.thread.join(2)
        self.window.quitting = True
        self.window.tray.hide()
        self.window.close()
        self.application.processEvents()
        self.temporary.cleanup()

    def test_main_window_has_no_scroll_container_or_dropdown(self):
        self.assertEqual(self.window.findChildren(QScrollArea), [])
        self.assertEqual(self.window.findChildren(QComboBox), [])
        self.assertIsNot(self.window.details.window(), self.window)
        self.assertIsNot(self.window.login.window(), self.window)
        self.assertTrue(self.window.audio.isChecked())
        self.assertLessEqual(self.window.audio_box.sizeHint().height(), 40)

    def test_discovery_updates_preserve_manual_address_and_selected_identity(self):
        window = self.window
        window.manual_address.setText("192.168.1.190")
        window.computers = {
            "game": {"id": "game", "name": "Server", "address": "192.168.1.190", "dsshine": True}
        }
        window._refresh_computers()
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
                    self.assertLessEqual(window.height(), 460)
                self.assertGreater(window.pages.height(), 200)
                for child in page.findChildren(QPushButton):
                    if child.isVisible():
                        position = child.mapTo(page, child.rect().bottomRight())
                        self.assertLessEqual(position.y(), page.height())
                if page is window.pair_page and role == "controller":
                    window.pair_error.setText("Server is unreachable. Check network permissions.")
                    self.application.processEvents()
                    choices_bottom = window.server_choices.mapTo(
                        page, window.server_choices.rect().bottomLeft()
                    ).y()
                    code_top = window.code.mapTo(page, window.code.rect().topLeft()).y()
                    self.assertLess(choices_bottom, code_top)

    def test_pairing_code_never_enters_logs(self):
        self.window.on_event("pair_code", "12345678")
        self.assertEqual(self.window.pin.text(), "1234 5678")
        self.assertNotIn("1234", self.window.details.toPlainText())

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
            self.assertEqual(window.audio_status.text(), "Disconnect to change audio")
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

    def test_mode_change_stops_current_session_and_persists_new_mode(self):
        window = self.window
        window.current_role = "game"
        window.preferences["role"] = "game"
        window._show_role()
        receiver = SimpleNamespace(stop=AsyncMock())
        window.engine.receiver = receiver
        window.busy = True
        window._update_actions()
        self.assertTrue(window.mode_button.isEnabled())
        window.mode_button.click()
        self.assertIs(window.pages.currentWidget(), window.mode_page)
        window.client.click()
        self._wait_for_mode("controller")
        receiver.stop.assert_awaited_once()
        self.assertIsNone(window.engine.receiver)
        self.assertTrue(window.role_caption.text().startswith("CLIENT"))
        self.assertIs(window.pages.currentWidget(), window.connection_page)
        settings = json.loads((window.root / "settings.json").read_text())
        self.assertEqual(settings["role"], "controller")
        if sys.platform == "win32":
            window.mode_button.click()
            window.server.click()
            self._wait_for_mode("game")
            self.assertTrue(window.role_caption.text().startswith("SERVER"))

    def _wait_for_mode(self, role):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.application.processEvents()
            if self.window.preferences.get("role") == role and not self.window.busy:
                return
            time.sleep(0.01)
        self.fail("Mode selection did not complete")
