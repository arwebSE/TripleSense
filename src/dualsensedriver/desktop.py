"""Compact server/client UI. Only device lists and logs can scroll."""

from __future__ import annotations

import sys
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .app_support import load_preferences, local_addresses, set_launch_at_login


def label(text, name="", *, wrap=False):
    value = QLabel(text)
    value.setObjectName(name)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setWordWrap(wrap)
    value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return value


def button(text, callback, *, primary=False):
    value = QPushButton(text)
    value.setCursor(Qt.CursorShape.PointingHandCursor)
    value.setMinimumHeight(36)
    if primary:
        value.setObjectName("primary")
    value.clicked.connect(callback)
    return value


class PageStack(QStackedWidget):
    """Hidden pairing controls must not dictate the connection window size."""

    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page else super().sizeHint()

    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page else super().minimumSizeHint()


class Window(QMainWindow):
    def __init__(self, root, *, smoke_test=False):
        from .app import AppEngine, Events

        super().__init__()
        self.root = root
        self.preferences = load_preferences(root)
        self.events = Events()
        self.events.event.connect(self.on_event)
        self.engine = AppEngine(root, self.preferences, self.events.event.emit)
        self.computers = {}
        self.busy = self.connected = self.quitting = False
        self.current_role = self.preferences.get(
            "role", "game" if sys.platform == "win32" else "controller"
        )
        self.setWindowTitle("DSShine")
        self.resize(640, 410)
        self.setMinimumWidth(600)
        self._build()
        self._tray()
        self._show_role()
        self._refresh_computers()
        self._fit_page()
        self.retry = QTimer(self)
        self.retry.timeout.connect(self._auto_connect)
        if not smoke_test:
            self.retry.start(4000)
            self._perform(self.engine.initialize())

    def _build(self):
        container = QWidget()
        self.setCentralWidget(container)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(12)
        header = QHBoxLayout()
        title = label("DSShine", "brand")
        header.addWidget(title, 1)
        self.roles = QButtonGroup(self)
        self.server = button("Server", lambda: self._role_changed("game"))
        self.client = button("Client", lambda: self._role_changed("controller"))
        for role in (self.server, self.client):
            role.setCheckable(True)
            role.setObjectName("mode")
            role.setFixedWidth(88)
            self.roles.addButton(role)
            header.addWidget(role)
        self.server.setEnabled(sys.platform == "win32")
        self.server.setToolTip("Server runs on the Windows PC with Sunshine")
        self.client.setToolTip("Client runs on the computer connected to your DualSense")
        outer.addLayout(header)
        self.role_caption = label("", "muted")
        outer.addWidget(self.role_caption)
        self.pages = PageStack()
        self.connection_page = self._connection_page()
        self.pair_page = self._pair_page()
        self.pages.addWidget(self.connection_page)
        self.pages.addWidget(self.pair_page)
        self.pages.currentChanged.connect(self._fit_page)
        outer.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        footer.addWidget(label("v" + __version__, "muted"), 1)
        footer.addWidget(button("Logs", self._open_logs))
        footer.addWidget(button("Settings", self._open_settings))
        outer.addLayout(footer)
        self._build_settings()
        self._build_logs()
        self.setStyleSheet("""
            QWidget { background: #0b0c0e; color: #f0f1f3; font-size: 14px; }
            QLabel { background: transparent; }
            QLabel#brand { font-size: 28px; font-weight: 700; }
            QLabel#muted { color: #a1a5ad; }
            QLabel[tone="success"], QLabel#muted[tone="success"] { color: #79e3a6; }
            QLabel[tone="info"], QLabel#muted[tone="info"] { color: #91caff; }
            QLabel[tone="danger"], QLabel#muted[tone="danger"],
            QLabel#code[tone="danger"] { color: #ff858e; }
            QLabel[tone="warning"] { color: #edc479; }
            QLabel#status { font-size: 25px; font-weight: 600; }
            QLabel#heading { font-size: 20px; font-weight: 600; }
            QLabel#code { font-size: 38px; font-weight: 600; color: #91caff; }
            QFrame#card { background: #15171a; border: 1px solid #2c2f34;
                          border-radius: 12px; }
            QFrame#card QWidget { background: transparent; }
            QPushButton { background: #1c1e22; border: 1px solid #373a40;
                          border-radius: 7px; padding: 0px 14px; }
            QPushButton:hover { background: #2a2d32; }
            QPushButton:disabled { color: #686d76; border-color: #26292e; }
            QPushButton#mode { background: transparent; color: #a1a5ad; }
            QPushButton#mode:checked { background: #282b30; color: #f0f1f3;
                                      border-color: #737983; }
            QPushButton#primary { background: #79e3a6; color: #10291a;
                                  border: none; font-weight: 600; }
            QPushButton#primary:hover { background: #9eebbf; }
            QPushButton#primary[intent="danger"] { background: #ff858e; color: #2d0c11; }
            QPushButton#primary[intent="danger"]:hover { background: #ffa1a8; }
            QPushButton#primary:disabled { background: #25282d; color: #777d86; }
            QLineEdit, QListWidget, QPlainTextEdit { background: #0d0e10;
                border: 1px solid #373a40; border-radius: 7px; padding: 7px; }
            QLineEdit { min-height: 22px; selection-background-color: #34495c; }
            QListWidget::item { border-radius: 5px; padding: 5px 10px; }
            QListWidget::item:selected { background: #292c31; color: #f0f1f3; }
            QCheckBox { spacing: 10px; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #777d87;
                                   border-radius: 4px; background: #0d0e10; }
            QCheckBox::indicator:checked { background: #79e3a6; border-color: #79e3a6; }
        """)

    def _connection_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        card = QFrame()
        card.setObjectName("card")
        content = QVBoxLayout(card)
        content.setContentsMargins(20, 18, 20, 18)
        content.setSpacing(8)
        self.status = label("Starting…", "status", wrap=True)
        self.description = label("Checking the connection.", "muted", wrap=True)
        content.addWidget(self.status)
        content.addWidget(self.description)
        content.addSpacing(12)
        self.peer_label = label("", "muted")
        self.peer_name = label("", wrap=True)
        content.addWidget(self.peer_label)
        content.addWidget(self.peer_name)
        self.addresses = label("", "muted", wrap=True)
        content.addWidget(self.addresses)
        layout.addWidget(card)
        self.audio_box = QWidget()
        audio_layout = QHBoxLayout(self.audio_box)
        audio_layout.setContentsMargins(0, 2, 0, 2)
        audio_layout.setSpacing(12)
        self.audio = QCheckBox("Controller audio")
        self.audio.setChecked(bool(self.preferences.get("audio", True)))
        self.audio.setToolTip("Forward the controller speaker, microphone and audio haptics.")
        self.audio.toggled.connect(lambda value: self._perform(self.engine.set_audio(value)))
        audio_layout.addWidget(self.audio)
        self.audio_status = label("", "muted", wrap=True)
        audio_layout.addWidget(self.audio_status, 1)
        self.audio_status.hide()
        layout.addWidget(self.audio_box)
        actions = QHBoxLayout()
        self.pair_button = button("Pair client", self._open_pairing)
        self.connect_button = button("Connect", self._toggle, primary=True)
        actions.addWidget(self.pair_button)
        actions.addStretch(1)
        actions.addWidget(self.connect_button)
        layout.addLayout(actions)
        layout.addStretch(1)
        return page

    def _pair_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        row = QHBoxLayout()
        self.pair_heading = label("Pair a client", "heading")
        row.addWidget(self.pair_heading, 1)
        row.addWidget(button("Back", self._back))
        layout.addLayout(row)
        self.pair_instructions = label("", "muted", wrap=True)
        layout.addWidget(self.pair_instructions)
        self.server_pair = QWidget()
        server = QVBoxLayout(self.server_pair)
        server.setContentsMargins(0, 4, 0, 4)
        server.setSpacing(14)
        self.pin = label("", "code")
        self.pin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        server.addStretch(1)
        server.addWidget(self.pin)
        self.pin_hint = label(
            "Generate a code, then enter it in the Client app.", "muted", wrap=True
        )
        self.pin_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        server.addWidget(self.pin_hint)
        server.addStretch(1)
        self.generate = button("Generate code", self._generate_code, primary=True)
        server.addWidget(self.generate)
        layout.addWidget(self.server_pair, 1)
        self.client_pair = QWidget()
        client = QVBoxLayout(self.client_pair)
        client.setContentsMargins(0, 0, 0, 0)
        client.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label("Available servers"), 1)
        self.manual_toggle = button("Enter address", self._toggle_manual)
        heading.addWidget(self.manual_toggle)
        self.rescan = button("Refresh", lambda: self._perform(self.engine.rescan()))
        heading.addWidget(self.rescan)
        client.addLayout(heading)
        self.server_choices = QStackedWidget()
        self.server_choices.setFixedHeight(144)
        self.hosts = QListWidget()
        self.hosts.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hosts.setWordWrap(True)
        self.server_choices.addWidget(self.hosts)
        manual = QWidget()
        manual_layout = QVBoxLayout(manual)
        manual_layout.setContentsMargins(0, 4, 0, 4)
        manual_layout.addWidget(label("Server IP address or hostname"))
        self.manual_address = QLineEdit()
        self.manual_address.setPlaceholderText("For example, 192.168.1.190")
        self.manual_address.setText(
            self.preferences.get("game_address")
            or self.preferences.get("controller_profile", {}).get("address", "")
        )
        self.manual_address.editingFinished.connect(self._remember_address)
        manual_layout.addWidget(self.manual_address)
        manual_layout.addWidget(label("The address is shown in the Server app.", "muted"))
        manual_layout.addStretch(1)
        self.server_choices.addWidget(manual)
        client.addWidget(self.server_choices)
        code_row = QHBoxLayout()
        code_row.addWidget(label("Pairing code"), 1)
        self.code = QLineEdit()
        self.code.setPlaceholderText("8-digit code from Server")
        self.code.setMaxLength(11)
        self.code.setFixedWidth(250)
        self.code.returnPressed.connect(self._pair_client)
        code_row.addWidget(self.code)
        client.addLayout(code_row)
        self.pair_error = label("", "muted", wrap=True)
        client.addWidget(self.pair_error)
        self.pair_submit = button("Pair and connect", self._pair_client, primary=True)
        client.addWidget(self.pair_submit)
        layout.addWidget(self.client_pair, 1)
        return page

    def _build_settings(self):
        self.settings = QDialog(self)
        self.settings.setWindowTitle("DSShine settings")
        self.settings.setMinimumWidth(480)
        layout = QVBoxLayout(self.settings)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("Settings", "heading"))
        self.login = QCheckBox("Start DSShine when I log in")
        self.login.setChecked(bool(self.preferences.get("launch_at_login", False)))
        self.login.setEnabled(bool(getattr(sys, "frozen", False)))
        self.login.toggled.connect(self._login_changed)
        layout.addWidget(self.login)
        self.auto = QCheckBox("Reconnect automatically")
        self.auto.setChecked(bool(self.preferences.get("auto_connect", True)))
        self.auto.toggled.connect(
            lambda enabled: self.engine.submit(
                self.engine.update_preferences("auto_connect", enabled)
            )
        )
        layout.addWidget(self.auto)
        self.sunshine = button("Repair Windows setup…", self._repair_setup)
        layout.addWidget(self.sunshine)
        self.setup_note = label(
            "Repairs driver and firewall setup, and configures Sunshine.", "muted", wrap=True
        )
        layout.addWidget(self.setup_note)
        layout.addWidget(button("Network permissions…", self._open_network_permissions))
        layout.addWidget(
            button(
                "Downloads and updates…",
                lambda: QDesktopServices.openUrl(
                    QUrl("https://github.com/arwebSE/DSShine/releases")
                ),
            )
        )
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.settings.hide)
        layout.addWidget(close)

    def _build_logs(self):
        self.logs = QDialog(self)
        self.logs.setWindowTitle("DSShine logs")
        self.logs.resize(700, 420)
        layout = QVBoxLayout(self.logs)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumBlockCount(500)
        self.details.setFont(QFont("Consolas" if sys.platform == "win32" else "Menlo", 11))
        layout.addWidget(self.details)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.logs.hide)
        layout.addWidget(close)

    def _show_role(self):
        server = self.current_role == "game"
        self.server.setChecked(server)
        self.client.setChecked(not server)
        self.role_caption.setText(
            "SERVER · Windows PC running Sunshine"
            if server
            else "CLIENT · Computer connected to your DualSense"
        )
        self.audio_box.setVisible(not server)
        self.auto.setVisible(not server)
        self.sunshine.setVisible(server and sys.platform == "win32")
        self.setup_note.setVisible(server and sys.platform == "win32")
        self.peer_label.setText("PAIRED CLIENT" if server else "PAIRED SERVER")
        self._update_peer()
        self._update_actions()
        if hasattr(self, "settings"):
            self._fit_page()

    def _fit_page(self):
        if not hasattr(self, "pages") or not self.pages.currentWidget():
            return
        self.pages.updateGeometry()
        self.centralWidget().layout().invalidate()
        self.centralWidget().layout().activate()
        pairing = self.pages.currentWidget() is getattr(self, "pair_page", None)
        height = (
            (530 if self.current_role == "controller" else 430)
            if pairing
            else (440 if self.current_role == "controller" else 404)
        )
        self.setMinimumHeight(height)
        self.resize(
            max(640, self.minimumSizeHint().width()), max(height, self.minimumSizeHint().height())
        )

    def _update_peer(self):
        if self.current_role == "game":
            self.peer_name.setText(self.preferences.get("controller_name") or "No client paired")
            self.addresses.setText("Server address: " + (", ".join(local_addresses()) or "Offline"))
        else:
            profile = self.preferences.get("controller_profile", {})
            self.peer_name.setText(profile.get("name", "No server paired"))
            self.addresses.setText(profile.get("address", ""))

    def _update_actions(self):
        server = self.current_role == "game"
        active = bool(self.engine.receiver if server else self.engine.connection)
        paired = bool(
            self.preferences.get("game_credentials")
            if server
            else self.preferences.get("controller_profile")
        )
        self.connect_button.setText(
            ("Stop server" if active else "Start server")
            if server
            else ("Disconnect" if active else "Connect")
        )
        if not paired:
            self.connect_button.setText("Pair client" if server else "Pair server")
        self._tone(self.connect_button, "danger" if active and paired else "positive", "intent")
        self.pair_button.setText("Pair client" if server else "Change server")
        self.pair_button.setVisible(paired)
        for control in (
            self.connect_button,
            self.pair_button,
            self.generate,
            self.pair_submit,
            self.audio,
            self.server,
            self.client,
        ):
            control.setEnabled(not self.busy)
        if sys.platform != "win32":
            self.server.setEnabled(False)

    def _role_changed(self, role):
        if role == self.current_role:
            return
        self.current_role = role
        self.pages.setCurrentWidget(self.connection_page)
        self._show_role()
        self._perform(self.engine.set_role(role))

    def _open_pairing(self):
        server = self.current_role == "game"
        self.pair_heading.setText("Pair a client" if server else "Connect to a server")
        self.pair_instructions.setText(
            "On the Client, select this server and enter the code below."
            if server
            else "Open DSShine on your Windows PC and generate a pairing code."
        )
        self.server_pair.setVisible(server)
        self.client_pair.setVisible(not server)
        self.pages.setCurrentWidget(self.pair_page)
        self._fit_page()
        self.pair_error.clear()
        if not server:
            self._perform(self.engine.rescan())

    def _back(self):
        self.pages.setCurrentWidget(self.connection_page)

    def _generate_code(self):
        self.pin_hint.setText("Creating a code… This disconnects the current client.")
        self._perform(self.engine.begin_pairing())

    def _toggle_manual(self):
        manual = self.server_choices.currentIndex() == 0
        self.server_choices.setCurrentIndex(1 if manual else 0)
        self.manual_toggle.setText("Use discovery" if manual else "Enter address")
        if manual:
            self.manual_address.setFocus()

    def _remember_address(self):
        address = self.manual_address.text().strip()
        if address:
            self.engine.submit(self.engine.update_preferences("game_address", address))

    def _refresh_computers(self):
        current = self.hosts.currentItem()
        selected_pc = current.data(Qt.ItemDataRole.UserRole) if current else None
        selected = selected_pc.get("id") if selected_pc else None
        self.hosts.clear()
        by_address = {}
        for pc in sorted(self.computers.values(), key=lambda item: item["dsshine"]):
            by_address[pc["address"]] = pc
        for pc in by_address.values():
            suffix = "" if pc["dsshine"] else " · open DSShine here first"
            item = QListWidgetItem(pc["name"] + "\n" + pc["address"] + suffix)
            item.setSizeHint(QSize(0, 55))
            item.setData(Qt.ItemDataRole.UserRole, pc)
            self.hosts.addItem(item)
            if pc["id"] == selected:
                self.hosts.setCurrentItem(item)
        if not self.hosts.currentItem() and self.hosts.count():
            self.hosts.setCurrentRow(0)
        if not self.hosts.count():
            item = QListWidgetItem("Searching for servers…\nCheck that DSShine is open on Windows.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(0, 60))
            self.hosts.addItem(item)

    def _pair_client(self):
        self._tone(self.pair_error, "danger")
        if self.server_choices.currentIndex() == 1:
            address = self.manual_address.text().strip()
        else:
            item = self.hosts.currentItem()
            pc = item.data(Qt.ItemDataRole.UserRole) if item else None
            address = pc["address"] if pc else ""
        if not address:
            self.pair_error.setText("Select a server, or enter its address.")
            return
        code = self.code.text().replace(" ", "").replace("-", "")
        if len(code) != 8 or not code.isascii() or not code.isdigit():
            self.pair_error.setText("Enter the 8-digit code shown in the Server app.")
            self.code.setFocus()
            return
        self.engine.submit(self.engine.update_preferences("game_address", address))
        self.pair_error.setText("Pairing with server…")
        self._tone(self.pair_error, "info")
        self._perform(self.engine.pair(address, code))

    def _toggle(self):
        paired = (
            self.preferences.get("game_credentials")
            if self.current_role == "game"
            else self.preferences.get("controller_profile")
        )
        if not paired:
            self._open_pairing()
        elif self.engine.connection or self.engine.receiver:
            self.auto.setChecked(False)
            self._perform(self.engine.stop())
        else:
            if self.current_role == "controller":
                self.auto.setChecked(True)
            self._perform(self.engine.connect())

    def _perform(self, coroutine):
        self.busy = True
        self._update_actions()
        self.engine.submit(coroutine, busy=True)

    def _auto_connect(self):
        if (
            not self.busy
            and not self.engine.connection
            and self.current_role == "controller"
            and self.auto.isChecked()
            and self.preferences.get("controller_profile")
        ):
            self._perform(self.engine.connect())

    def _login_changed(self, enabled):
        try:
            set_launch_at_login(enabled)
            self.engine.submit(self.engine.update_preferences("launch_at_login", enabled))
        except (OSError, RuntimeError) as exc:
            self.login.blockSignals(True)
            self.login.setChecked(not enabled)
            self.login.blockSignals(False)
            self.on_event("error", str(exc))

    def _open_settings(self):
        self.settings.show()
        self.settings.raise_()

    def _open_logs(self):
        self.logs.show()
        self.logs.raise_()

    def _open_network_permissions(self):
        QDesktopServices.openUrl(
            QUrl(
                "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_LocalNetwork"
                if sys.platform == "darwin"
                else "ms-settings:network-status"
            )
        )

    def _repair_setup(self):
        try:
            from .setup import request_repair

            request_repair()
            self.description.setText("Accept the Windows prompt to repair setup.")
        except (OSError, RuntimeError) as exc:
            self.on_event("error", str(exc))

    @staticmethod
    def _tone(widget, value, property_name="tone"):
        widget.setProperty(property_name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    @staticmethod
    def _friendly_error(message):
        if "Expected one Bluetooth DualSense" in message:
            return "Press PS to connect your DualSense to this Client over Bluetooth."
        if "Steam is running" in message:
            return "Quit Steam on this Client so DSShine can access the controller."
        if "CERTIFICATE_VERIFY_FAILED" in message:
            return "The pairing has expired or changed. Pair with your Server again."
        if "Pairing failed" in message:
            return "Pairing failed. Generate a new Server code and try again."
        if any(
            text in message
            for text in ("route", "Connect call failed", "refused", "10060", "timed out")
        ):
            return (
                "Server is unreachable. Check that DSShine is open and network access is allowed."
            )
        if "10048" in message or "Address already in use" in message:
            return "Another DSShine copy is using the connection. Quit it and try again."
        return message if len(message) <= 160 else "Connection failed. Open Logs for details."

    def on_event(self, kind, value):
        if kind == "computer":
            self.computers[value["id"]] = value
            self._refresh_computers()
            self.engine.submit(self.engine.discovered(value))
            return
        if kind == "computer_removed":
            self.computers.pop(value, None)
            self._refresh_computers()
            return
        if kind == "idle":
            self.busy = False
            self._update_actions()
            return
        if kind == "pair_code":
            self.pin.setText(value[:4] + " " + value[4:] if value else "Code expired")
            self.pin_hint.setText(
                "Code expires in 2 minutes."
                if value
                else "Generate a new code to continue pairing."
            )
            self.generate.setText("Generate a new code")
            self._tone(self.pin, "info" if value else "danger")
            return  # Pairing codes are never written to logs.
        if kind == "audio_status":
            stalled = "stall" in str(value)
            self.audio_status.setText("Bluetooth audio is dropping out" if stalled else "")
            self.audio_status.setVisible(stalled and self.audio.isChecked())
            self.audio.setToolTip(str(value).replace("game PC", "Server"))
            self._tone(self.audio_status, "danger" if stalled else "info")
            return
        message = str(value or "")
        self.details.appendPlainText(
            datetime.now().strftime("%H:%M:%S") + "  " + kind + ": " + message
        )
        if kind == "error":
            self._tone(self.pair_error, "danger")
            self.status.setText("Connection needs attention")
            self.description.setText(self._friendly_error(message))
            self.pair_error.setText(self._friendly_error(message))
            self.connected = False
        elif kind == "driver_needed":
            self.status.setText("Server setup needed")
            self.description.setText("Open Settings → Repair Windows setup to install the driver.")
        elif kind == "paired":
            self.pin.clear()
            self.code.clear()
            self._back()
            self.status.setText("Paired")
            self.description.setText("Connecting your controller…")
        elif kind == "connected":
            self.connected = True
            self.status.setText("Connected")
            self.description.setText("Your DualSense is available to games on the Server.")
        elif kind == "available":
            self.status.setText("Starting controller…")
            self.description.setText("Computers are connected. Preparing the DualSense.")
        elif kind == "controller_started":
            self.status.setText("Connecting…")
            self.description.setText("DualSense found. Connecting to your Server.")
        elif kind == "controller_waiting":
            self.connected = False
            self.status.setText("Controller disconnected")
            self.description.setText("Press PS to reconnect your DualSense to this Client.")
        elif kind == "reconnecting":
            self.connected = False
            self.status.setText("Reconnecting…")
            self.description.setText(
                "Looking for your Server. Keep DSShine open on both computers."
            )
        elif kind == "waiting":
            self.connected = False
            paired = bool(self.preferences.get("game_credentials"))
            self.status.setText("Waiting for client" if paired else "Pair your client")
            self.description.setText(
                "Open DSShine on the computer connected to your DualSense."
                if paired
                else "Pair once, then reconnect automatically."
            )
        elif kind == "stopped":
            self.connected = False
            paired = (
                self.preferences.get("game_credentials")
                if self.current_role == "game"
                else self.preferences.get("controller_profile")
            )
            self.status.setText(
                "Disconnected"
                if paired
                else "Pair your client"
                if self.current_role == "game"
                else "Pair your server"
            )
            self.description.setText(
                "The controller connection is stopped."
                if paired
                else "Pair once, then reconnect automatically."
            )
        elif kind == "discovery_unavailable":
            self.pair_error.setText("Discovery is unavailable. Enter a Server address instead.")
        if not self.audio.isChecked():
            self.audio_status.hide()
        tone = (
            "danger"
            if kind in ("error", "controller_waiting", "stopped")
            else "success"
            if kind in ("connected", "paired")
            else "warning"
            if kind == "driver_needed"
            else "info"
        )
        if kind == "stopped" and not paired:
            tone = "info"
        self._tone(self.status, tone)
        self._update_peer()
        self._update_actions()

    def _tray(self):
        self.tray = QSystemTrayIcon(
            self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon), self
        )
        self.setWindowIcon(self.tray.icon())
        self.tray.setToolTip("DSShine")
        menu = QMenu()
        show = QAction("Open DSShine", self)
        show.triggered.connect(self.showNormal)
        menu.addAction(show)
        quit_action = QAction("Quit DSShine", self)
        quit_action.setShortcut("Ctrl+Q" if sys.platform == "win32" else "Meta+Q")
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.showNormal()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

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
        self.status.setText("Disconnecting…")
        self.busy = True
        self._update_actions()
        future = self.engine.submit(self.engine.shutdown())

        def check():
            if not future.done():
                QTimer.singleShot(100, check)
                return
            try:
                future.result()
            except Exception as exc:
                self.busy = False
                self._update_actions()
                QMessageBox.warning(self, "Could not disconnect safely", str(exc))
                return
            self.quitting = True
            self.engine.loop.call_soon_threadsafe(self.engine.loop.stop)
            self.engine.thread.join(timeout=2)
            self.tray.hide()
            QApplication.instance().quit()

        check()
