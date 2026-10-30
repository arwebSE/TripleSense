import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from dualsensedriver.app import Window


class AddressFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.hosts = QComboBox()
        self.hosts.setEditable(True)
        self.window = SimpleNamespace(
            hosts=self.hosts,
            computers={
                "game": {
                    "address": "192.168.1.190",
                    "name": "Game PC",
                    "dsshine": True,
                }
            },
        )

    def test_discovery_updates_preserve_manually_entered_address(self):
        self.hosts.setEditText("192.168.1.190")
        Window._refresh_computers(self.window)
        self.assertEqual(self.hosts.currentText(), "192.168.1.190")
        self.assertIsNone(self.hosts.currentData())
        self.assertEqual(self.hosts.count(), 1)

    def test_discovery_updates_preserve_selected_pc_and_removed_text(self):
        Window._refresh_computers(self.window)
        self.assertEqual(self.hosts.currentData()["address"], "192.168.1.190")
        self.window.computers.clear()
        Window._refresh_computers(self.window)
        self.assertEqual(self.hosts.currentText(), "Game PC")
        self.assertIsNone(self.hosts.currentData())
