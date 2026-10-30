"""DSShine desktop app. Python and the controller libraries ship in the bundle."""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import logging
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .app_support import (
    Discovery,
    app_directory,
    bundled_installer,
    load_preferences,
    local_addresses,
    save_preferences,
    set_launch_at_login,
)
from .diagnostics import choose_controller, find_usbip, require_controller_isolation
from .pairing import PairingOffer, pair_controller
from .reverse import ControllerConnection, GameReceiver


class Events(QObject):
    event = Signal(str, object)


class AppEngine:
    """Own all controller/network state in one background event loop."""

    def __init__(self, root, preferences, notify):
        self.root, self.preferences, self.notify = root, preferences, notify
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="dsshine-network", daemon=True)
        self.thread.start()
        self.operation = asyncio.Lock()
        self.receiver = self.connection = self.pairing = self.expiry = None
        self.discovery = None

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)

        def completed(done):
            try:
                done.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception as exc:
                self.notify("error", str(exc))
            finally:
                self.notify("idle", None)

        future.add_done_callback(completed)
        return future

    async def initialize(self):
        try:
            self.discovery = await asyncio.to_thread(Discovery, self.notify)
        except OSError:
            self.notify("discovery_unavailable", None)
        await self.set_role(
            self.preferences.get("role", "game" if sys.platform == "win32" else "controller")
        )

    def save(self):
        save_preferences(self.root, self.preferences)

    async def _stop(self):
        if self.expiry:
            self.expiry.cancel()
            self.expiry = None
        errors = []
        for name in ("pairing", "receiver", "connection"):
            value = getattr(self, name)
            if value:
                try:
                    await value.stop()
                    setattr(self, name, None)
                except Exception as exc:
                    errors.append(str(exc))
        if errors:
            raise RuntimeError("; ".join(errors))
        self.notify("stopped", "Disconnected")

    async def stop(self):
        async with self.operation:
            await self._stop()

    async def set_role(self, role):
        async with self.operation:
            await self._stop()
            self.preferences["role"] = role
            self.save()
            if self.discovery:
                if role == "game":
                    await asyncio.to_thread(self.discovery.advertise)
                else:
                    await asyncio.to_thread(self.discovery.withdraw)
            if role == "game":
                await self._start_game()

    async def _start_game(self):
        if sys.platform != "win32":
            self.notify("waiting", "Choose Controller PC on this Mac")
            return
        usbip = find_usbip()
        if not usbip:
            self.notify("driver_needed", None)
            return
        credentials = self.preferences.get("game_credentials")
        if not credentials:
            self.notify("waiting", "Pair your controller computer to get started")
            return
        receiver = GameReceiver(
            credentials, self.notify, usbip=usbip, ownership_file=self.root / "usb-session.json"
        )
        await receiver.start()
        self.receiver = receiver
        self.notify("waiting", "Ready for your controller computer")

    async def begin_pairing(self):
        async with self.operation:
            await self._stop()

            async def accepted(credentials, name):
                self.preferences["game_credentials"] = str(credentials)
                self.preferences["controller_name"] = name
                self.save()
                await self._start_game()
                self.notify("paired", name)

            self.pairing = PairingOffer(self.root / "identities", accepted)
            await self.pairing.start()
            self.notify("pair_code", self.pairing.code)

            async def expire():
                await asyncio.sleep(120)
                if self.pairing:
                    await self.pairing.stop()
                    self.pairing = None
                self.notify("pair_code", "")

            self.expiry = asyncio.create_task(expire())

    async def pair(self, address, code):
        async with self.operation:
            profile = await pair_controller(address, code, self.root / "identities")
            self.preferences["controller_profile"] = profile
            self.save()
            self.notify("paired", profile["name"])
        await self.connect()

    async def connect(self):
        async with self.operation:
            if self.connection:
                return
            if self.preferences.get("role") == "game":
                if not self.receiver:
                    await self._start_game()
                return
            profile = self.preferences.get("controller_profile")
            if not profile:
                raise RuntimeError("Choose your game PC and pair it first")
            await asyncio.to_thread(require_controller_isolation)
            selected = await asyncio.to_thread(choose_controller, None)
            from .controller import StandaloneControllerBackend

            backend = StandaloneControllerBackend(
                serial=selected.serial,
                audio_enabled=bool(self.preferences.get("audio", False)),
            )
            connection = ControllerConnection(profile, backend, self.notify)
            await connection.start()
            self.connection = connection
            self.notify("controller_started", selected.product)

    async def update_preferences(self, key, value):
        self.preferences[key] = value
        self.save()

    async def shutdown(self):
        await self.stop()
        if self.discovery:
            await asyncio.to_thread(self.discovery.close)
            self.discovery = None


class Window(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.preferences = load_preferences(root)
        self.events = Events()
        self.events.event.connect(self.on_event)
        self.engine = AppEngine(root, self.preferences, self.events.event.emit)
        self.computers = {}
        self.busy = False
        self.connected = False
        self.quitting = False
        self.setWindowTitle("DSShine")
        self.resize(670, 740)
        self.setMinimumSize(620, 600)
        self._build()
        self._tray()
        self.engine.submit(self.engine.initialize())
        self.retry = QTimer(self)
        self.retry.timeout.connect(self._auto_connect)
        self.retry.start(4000)

    def _build(self):
        container = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(container)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(12)
        title = QLabel("DSShine")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("Your DualSense. On your gaming PC.")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        row = QHBoxLayout()
        row.addWidget(QLabel("This computer"))
        self.role = QComboBox()
        self.role.addItem("Game PC · runs Sunshine", "game")
        self.role.addItem("Controller PC · runs Moonlight", "controller")
        role = self.preferences.get("role", "game" if sys.platform == "win32" else "controller")
        self.role.setCurrentIndex(0 if role == "game" else 1)
        self.role.currentIndexChanged.connect(self._role_changed)
        row.addWidget(self.role, 1)
        layout.addLayout(row)
        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(20, 20, 20, 20)
        self.status = QLabel("Getting ready")
        self.status.setObjectName("status")
        self.description = QLabel("Checking your controller setup…")
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setObjectName("muted")
        status_layout.addWidget(self.status)
        status_layout.addWidget(self.description)
        layout.addWidget(self.status_card)
        self.game_box = QWidget()
        self.game_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        game = QVBoxLayout(self.game_box)
        game.setContentsMargins(0, 0, 0, 0)
        game.setSpacing(12)
        self.addresses = QLabel(
            "Game PC address: " + (", ".join(local_addresses()) or "No network")
        )
        game.addWidget(self.addresses)
        self.pair_button = QPushButton("Pair a controller computer")
        self.pair_button.clicked.connect(lambda: self._perform(self.engine.begin_pairing()))
        game.addWidget(self.pair_button)
        self.pin = QLabel("")
        self.pin.setObjectName("pin")
        self.pin.hide()
        self.pin.setTextInteractionFlags(Qt.TextSelectableByMouse)
        game.addWidget(self.pin)
        self.pin_hint = QLabel(
            "On the controller computer, select this PC and enter the code.\n"
            "Codes expire after two minutes."
        )
        self.pin_hint.setWordWrap(True)
        self.pin_hint.hide()
        game.addWidget(self.pin_hint)
        self.install = QPushButton("Install controller driver")
        self.install.clicked.connect(self._install_driver)
        self.install.hide()
        game.addWidget(self.install)
        self.sunshine = QPushButton("Open Sunshine controller settings")
        self.sunshine.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://localhost:47990/config"))
        )
        game.addWidget(self.sunshine)
        note = QLabel(
            "In Sunshine, turn controller input off to avoid a second gamepad.\n"
            "DSShine supplies the DualSense; Moonlight streams the game as usual."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        game.addWidget(note)
        layout.addWidget(self.game_box)
        self.controller_box = QWidget()
        self.controller_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        controller = QVBoxLayout(self.controller_box)
        controller.setContentsMargins(0, 0, 0, 0)
        controller.setSpacing(12)
        controller.addWidget(QLabel("Game PC"))
        self.hosts = QComboBox()
        self.hosts.setEditable(True)
        self.hosts.setPlaceholderText("Finding PCs… or enter an address")
        self.hosts.lineEdit().setPlaceholderText("Finding PCs… or enter an address")
        controller.addWidget(self.hosts)
        self.client_pair = QPushButton("Pair with this PC")
        self.client_pair.clicked.connect(self._pair_client)
        controller.addWidget(self.client_pair)
        self.audio = QCheckBox("Enable experimental controller audio")
        self.audio.setChecked(bool(self.preferences.get("audio", False)))
        self.audio.toggled.connect(
            lambda value: self.engine.submit(self.engine.update_preferences("audio", value))
        )
        controller.addWidget(self.audio)
        warning = QLabel(
            "Controller speaker, microphone and detailed audio haptics may\n"
            "drop out over Mac Bluetooth. Normal game audio stays in Moonlight."
        )
        warning.setObjectName("muted")
        warning.setWordWrap(True)
        controller.addWidget(warning)
        layout.addWidget(self.controller_box)
        self.auto = QCheckBox("Connect automatically when DSShine opens")
        self.auto.setChecked(bool(self.preferences.get("auto_connect", True)))
        self.auto.toggled.connect(
            lambda value: self.engine.submit(self.engine.update_preferences("auto_connect", value))
        )
        layout.addWidget(self.auto)
        self.login = QCheckBox("Open DSShine when I log in")
        self.login.setChecked(bool(self.preferences.get("launch_at_login", False)))
        self.login.setVisible(bool(getattr(sys, "frozen", False)))
        self.login.toggled.connect(self._login_changed)
        layout.addWidget(self.login)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self._toggle)
        layout.addWidget(self.connect_button)
        self.details_toggle = QPushButton("Connection details")
        self.details_toggle.setFlat(True)
        self.details_toggle.clicked.connect(
            lambda: self.details.setVisible(not self.details.isVisible())
        )
        layout.addWidget(self.details_toggle)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.document().setMaximumBlockCount(200)
        self.details.setMaximumHeight(120)
        self.details.hide()
        layout.addWidget(self.details)
        layout.addStretch(1)
        footer = QLabel(f"DSShine {__version__} · Free and open source")
        footer.setObjectName("muted")
        layout.addWidget(footer)
        self.setStyleSheet("""
            QWidget { background: #14181f; color: #e7edf4; font-size: 14px; }
            QLabel#title { font-size: 34px; font-weight: 700; }
            QLabel#muted { color: #a4b0bf; }
            QLabel#status { font-size: 21px; font-weight: 600; }
            QFrame#card { background: #202833; border: 1px solid #334155; border-radius: 12px; }
            QFrame#card QLabel { background: transparent; }
            QPushButton, QComboBox, QLineEdit {
                padding: 10px; border: 1px solid #3b485b;
                border-radius: 7px; background: #252f3d;
            }
            QPushButton:hover { background: #354459; }
            QPushButton:disabled { color: #718096; }
            QPushButton#primary {
                background: #79dcc4; color: #10241e; font-weight: 600; border: none;
            }
            QPushButton#primary:hover { background: #9ae9d5; }
            QLabel#pin { color: #79dcc4; font-size: 30px; font-weight: 600; }
            QCheckBox { spacing: 9px; }
            QTextEdit { background: #0f1319; border: 1px solid #334155; border-radius: 6px; }
        """)
        self._show_role()
        for button in self.findChildren(QPushButton):
            button.setMinimumHeight(40)
        for combo in self.findChildren(QComboBox):
            combo.setMinimumHeight(42)

    def _tray(self):
        icon = self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("DSShine")
        menu = QMenu()
        show = QAction("Open DSShine", self)
        show.triggered.connect(self.showNormal)
        menu.addAction(show)
        quit_action = QAction("Quit DSShine", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.showNormal()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

    def _show_role(self):
        game = self.role.currentData() == "game"
        self.game_box.setVisible(game)
        self.controller_box.setVisible(not game)
        self.auto.setVisible(not game)
        self.pair_button.setEnabled(sys.platform == "win32")
        self.sunshine.setVisible(sys.platform == "win32")

    def _login_changed(self, enabled):
        try:
            set_launch_at_login(enabled)
            self.engine.submit(self.engine.update_preferences("launch_at_login", enabled))
        except (OSError, RuntimeError) as exc:
            self.login.blockSignals(True)
            self.login.setChecked(not enabled)
            self.login.blockSignals(False)
            self.on_event("error", str(exc))

    def _role_changed(self):
        self._show_role()
        self._perform(self.engine.set_role(self.role.currentData()))

    def _perform(self, coroutine):
        self.busy = True
        self.connect_button.setEnabled(False)
        self.engine.submit(coroutine)

    def _toggle(self):
        if self.connected or self.engine.connection or self.engine.receiver:
            self.auto.setChecked(False)
            self._perform(self.engine.stop())
        else:
            self._perform(self.engine.connect())

    def _auto_connect(self):
        if (
            not self.busy
            and not self.engine.connection
            and self.role.currentData() == "controller"
            and self.auto.isChecked()
            and self.preferences.get("controller_profile")
        ):
            self._perform(self.engine.connect())

    def _pair_client(self):
        item = self.hosts.currentData()
        selected = self.hosts.itemText(self.hosts.currentIndex()) == self.hosts.currentText()
        address = (
            item["address"]
            if selected and isinstance(item, dict)
            else self.hosts.currentText().strip()
        )
        if not address:
            self.description.setText("Select a game PC, or enter its address.")
            return
        code, accepted = QInputDialog.getText(
            self,
            "Pair with game PC",
            "Enter the eight-digit code shown in DSShine on the game PC:",
            QLineEdit.EchoMode.Normal,
        )
        if accepted:
            self.status.setText("Pairing")
            self._perform(self.engine.pair(address, code))

    def _install_driver(self):
        try:
            path = bundled_installer()
            if path:
                os.startfile(str(path))
            else:
                QDesktopServices.openUrl(
                    QUrl("https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.8.1")
                )
        except (OSError, RuntimeError) as exc:
            self.on_event("error", str(exc))

    def on_event(self, kind, value):
        if kind == "computer":
            self.computers[value["id"]] = value
            selected = self.hosts.currentText()
            self.hosts.blockSignals(True)
            self.hosts.clear()
            # Prefer a running DSShine app over a plain Sunshine advertisement.
            by_address = {}
            for pc in sorted(self.computers.values(), key=lambda item: item["dsshine"]):
                by_address[pc["address"]] = pc
            for pc in by_address.values():
                suffix = "" if pc["dsshine"] else " · open DSShine on this PC"
                self.hosts.addItem(pc["name"] + suffix, pc)
            if selected and self.hosts.findText(selected) >= 0:
                self.hosts.setCurrentText(selected)
            self.hosts.blockSignals(False)
            return
        if kind == "computer_removed":
            self.computers.pop(value, None)
            return
        if kind == "idle":
            self.busy = False
            self.connect_button.setEnabled(True)
            return
        if kind == "pair_code":
            self.pin.setText(value[:4] + " " + value[4:] if value else "")
            self.pin.setVisible(bool(value))
            self.pin_hint.setVisible(bool(value))
            if value:
                self.status.setText("Ready to pair")
                self.description.setText("Enter this code on the controller computer.")
            return
        if kind == "driver_needed":
            self.install.show()
            self.status.setText("One-time driver setup")
            self.description.setText("Install the free controller driver, then click Connect.")
            return
        if kind == "discovery_unavailable":
            self.description.setText(
                "Automatic discovery is unavailable. Enter your game PC address."
            )
            return
        self.details.append(str(value or kind))
        message = str(value or "")
        if "Expected one Bluetooth DualSense" in message:
            message = "Turn on your DualSense and connect it to this computer over Bluetooth."
        elif "Steam is running" in message:
            message = (
                "Close Steam on this computer so DSShine can use the controller. "
                "Steam can stay open on the game PC."
            )
        elif "CERTIFICATE_VERIFY_FAILED" in message:
            message = "Disconnect and pair the computers again to renew their trusted connection."
        elif any(
            text in message
            for text in (
                "No route to host",
                "Connect call failed",
                "actively refused",
                "WinError 10060",
            )
        ):
            message = (
                "Check that DSShine is open on the game PC "
                "and both computers are on the same network."
            )
            if sys.platform == "darwin":
                message += " Allow DSShine in Privacy & Security → Local Network."
        if kind == "error":
            self.status.setText("Connection needs attention")
            self.description.setText(message)
            self.connected = False
        elif kind in ("connected", "available"):
            self.status.setText("Connected" if kind == "connected" else "Computer connected")
            self.description.setText(message)
            self.connected = True
        elif kind == "paired":
            self.pin.clear()
            self.pin.hide()
            self.pin_hint.hide()
            self.status.setText("Paired")
            self.description.setText("Paired with " + str(value))
        elif kind == "controller_started":
            self.status.setText("Connecting")
            self.description.setText("DualSense found. Connecting to your game PC…")
        elif kind in ("waiting", "controller_waiting", "reconnecting", "stopped"):
            self.status.setText(
                "Ready"
                if kind in ("waiting", "controller_waiting")
                else "Reconnecting"
                if kind == "reconnecting"
                else "Disconnected"
            )
            self.description.setText(message)
            self.connected = False
        self.connect_button.setText(
            "Disconnect"
            if self.connected or self.engine.connection or self.engine.receiver
            else "Connect"
        )
        self.audio.setEnabled(self.engine.connection is None)
        self.client_pair.setEnabled(self.engine.connection is None)
        self.pair_button.setEnabled(
            sys.platform == "win32"
            and (self.engine.receiver is None or self.engine.receiver.owned_port is None)
        )

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        elif QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            event.ignore()
            self.quit()

    def quit(self):
        if self.quitting:
            return
        self.retry.stop()
        self.status.setText("Disconnecting")
        self.connect_button.setEnabled(False)
        future = self.engine.submit(self.engine.shutdown())

        def check():
            if not future.done():
                QTimer.singleShot(100, check)
                return
            try:
                future.result()
            except Exception as exc:
                QMessageBox.warning(self, "Controller cleanup needs attention", str(exc))
                return
            self.quitting = True
            self.engine.loop.call_soon_threadsafe(self.engine.loop.stop)
            self.tray.hide()
            QApplication.instance().quit()

        check()


def main(argv=None):
    parser = argparse.ArgumentParser(description="DSShine desktop app")
    parser.add_argument("--data-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    application = QApplication(sys.argv[:1])
    application.setApplicationName("DSShine")
    application.setOrganizationName("DSShine")
    application.setQuitOnLastWindowClosed(False)
    application.setFont(QFont("Segoe UI" if sys.platform == "win32" else ".AppleSystemUIFont", 10))
    root = args.data_dir or app_directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = QLockFile(str(root / "app.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(
            None, "DSShine is already open", "Open DSShine from its tray or menu-bar icon."
        )
        return 0
    logging.basicConfig(level=logging.WARNING, filename=root / "app.log", encoding="utf-8")
    window = Window(root)
    if not args.background:
        window.show()
    if args.smoke_test:

        def smoke():
            window.grab().save(str(args.smoke_test))
            window.quit()

        QTimer.singleShot(1800, smoke)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
