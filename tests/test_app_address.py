import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QScrollArea

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
        window.resize(660, 570)
        for role in ("game", "controller"):
            window.current_role = role
            window._show_role()
            # Select screens without issuing network or pairing operations.
            for page in (window.connection_page, window.pair_page):
                window.server_pair.setVisible(role == "game")
                window.client_pair.setVisible(role == "controller")
                window.pages.setCurrentWidget(page)
                self.application.processEvents()
                self.assertLessEqual(window.height(), 590)
                self.assertGreater(window.pages.height(), 300)
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
