"""Compact server/client UI. Only device lists and logs can scroll."""

from __future__ import annotations

import ipaddress
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import (
    QApplication,
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
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import __version__, saved_servers
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


class DisabledTooltips(QObject):
    """Keep native hover help available when a control cannot be used."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip and isinstance(watched, QWidget):
            target = QApplication.widgetAt(event.globalPos()) or watched
            owner = self.parent()
            if owner.isAncestorOf(target) and not target.isEnabled() and target.toolTip():
                QToolTip.showText(event.globalPos(), target.toolTip(), target)
                return True
        return False


class AudioSwitch(QCheckBox):
    def setLocked(self, locked):
        self.setProperty("locked", locked)
        self.setEnabled(not locked)
        self.setToolTip(
            "Disconnect to change audio"
            if locked
            else "Forward the controller speaker, microphone and audio haptics."
        )
        self.setAccessibleDescription(
            "Disconnect to change audio" if locked else "Controller audio"
        )
        self.style().unpolish(self)
        self.style().polish(self)
        self.setCursor(
            Qt.CursorShape.ForbiddenCursor if locked else Qt.CursorShape.PointingHandCursor
        )


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
        self.server_states = {}
        self.busy = self.connected = self.quitting = self.closing = self.pairing_client = False
        self.current_role = self.preferences.get(
            "role", "game" if sys.platform == "win32" else "controller"
        )
        if sys.platform != "win32":
            self.current_role = "controller"
        self.setWindowTitle("DSShine")
        self.resize(640, 410)
        self.setMinimumWidth(600)
        self._build()
        self.tooltip_filter = DisabledTooltips(self)
        QApplication.instance().installEventFilter(self.tooltip_filter)
        self.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "dsshine.svg")))
        quit_action = QAction("Quit DSShine", self)
        quit_action.setShortcut("Ctrl+Q" if sys.platform == "win32" else "Meta+Q")
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)
        self._show_role()
        self._refresh_computers()
        self._fit_page()
        self.retry = QTimer(self)
        self.retry.timeout.connect(self._auto_connect)
        if not smoke_test:
            self.retry.start(4000)
            self._perform(self.engine.initialize())

    def _build(self):
        # A small HiDPI UI glyph; native scrollbars remain entirely unstyled.
        checkmark = QPixmap(32, 32)
        checkmark.fill(Qt.GlobalColor.transparent)
        painter = QPainter(checkmark)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        painter.setPen(
            QPen(
                QColor("#ffffff"),
                2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPolyline([QPointF(3, 8), QPointF(6.5, 11.5), QPointF(13, 4.5)])
        painter.end()
        glyph = self.root / "checkmark.png"
        checkmark.save(str(glyph))
        glyph_url = glyph.as_posix()
        palette = self.palette()
        for role, color in (
            (QPalette.ColorRole.Window, "#0b0c0e"),
            (QPalette.ColorRole.Base, "#0d0e10"),
            (QPalette.ColorRole.Text, "#f0f1f3"),
            (QPalette.ColorRole.WindowText, "#f0f1f3"),
            (QPalette.ColorRole.Button, "#1c1e22"),
            (QPalette.ColorRole.ButtonText, "#f0f1f3"),
            (QPalette.ColorRole.Highlight, "#0a84ff"),
            (QPalette.ColorRole.HighlightedText, "#ffffff"),
        ):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        container = QWidget()
        self.setCentralWidget(container)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(12)
        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(
            QIcon(str(Path(__file__).with_name("assets") / "dsshine.svg")).pixmap(36, 36)
        )
        mark.setFixedSize(36, 36)
        header.addWidget(mark)
        title = label("DSShine", "brand")
        header.addWidget(title, 1)
        self.mode_button = button("Change mode", self._open_modes)
        self.mode_button.setVisible(sys.platform == "win32")
        header.addWidget(self.mode_button)
        outer.addLayout(header)
        self.role_caption = label("", "muted")
        outer.addWidget(self.role_caption)
        self.pages = PageStack()
        self.connection_page = self._connection_page()
        self.pair_page = self._pair_page()
        self.server = self.client = None
        self.mode_page = self._mode_page() if sys.platform == "win32" else None
        self.pages.addWidget(self.connection_page)
        self.pages.addWidget(self.pair_page)
        if self.mode_page:
            self.pages.addWidget(self.mode_page)
        self.pages.currentChanged.connect(self._fit_page)
        outer.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        footer.addWidget(label("v" + __version__, "muted"), 1)
        footer.addWidget(button("Logs", self._open_logs))
        footer.addWidget(button("Settings", self._open_settings))
        outer.addLayout(footer)
        self._build_settings()
        self._build_logs()
        self.setStyleSheet(
            """
            QMainWindow, QDialog { background: #0b0c0e; color: #f0f1f3; }
            QLabel, QPushButton, QLineEdit, QListWidget, QPlainTextEdit, QCheckBox {
                font-size: 14px; }
            QLabel { background: transparent; }
            QLabel#brand { font-size: 28px; font-weight: 700; }
            QLabel#muted { color: #a1a5ad; }
            QLabel[tone="success"], QLabel#muted[tone="success"] { color: #64b5ff; }
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
            QPushButton#mode:checked { background: #171f29; color: #a5d3ff;
                                      border-color: #0a84ff; }
            QPushButton#primary { background: #0a84ff; color: #ffffff;
                                  border: none; font-weight: 600; }
            QPushButton#primary:hover { background: #409cff; }
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
            QCheckBox::indicator:checked { background: #0a84ff; border-color: #0a84ff;
                                          image: url("__CHECKMARK__"); }
            QCheckBox[locked="true"] { color: #777d87; }
            QCheckBox[locked="true"]::indicator { border-color: #40444c; }
            QCheckBox[locked="true"]::indicator:checked { background: #315a80; }
        """.replace("__CHECKMARK__", glyph_url)
        )

    def _mode_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label("Choose a mode", "heading"), 1)
        heading.addWidget(button("Back", self._back))
        layout.addLayout(heading)
        layout.addWidget(
            label("Changing mode disconnects the current controller session.", "muted", wrap=True)
        )
        self.server = button(
            "Server\nMakes a DualSense available on this Windows PC",
            lambda: self._role_changed("game"),
        )
        self.client = button(
            "Client\nThe DualSense connects to this computer",
            lambda: self._role_changed("controller"),
        )
        self.server.setAutoExclusive(True)
        self.client.setAutoExclusive(True)
        for choice in (self.server, self.client):
            choice.setCheckable(True)
            choice.setObjectName("mode")
            choice.setMinimumHeight(68)
            layout.addWidget(choice)
        if sys.platform != "win32":
            self.server.setText("Server\nRequires Windows")
        layout.addStretch(1)
        return page

    def _open_modes(self):
        if self.mode_page is None or self.engine.receiver or self.engine.connection or self.busy:
            return
        self.pages.setCurrentWidget(self.mode_page)
        self._fit_page()

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
        self.peer_gap = QWidget()
        self.peer_gap.setFixedHeight(8)
        content.addWidget(self.peer_gap)
        self.peer_label = label("", "muted")
        self.peer_name = label("", wrap=True)
        content.addWidget(self.peer_label)
        content.addWidget(self.peer_name)
        self.addresses = label("", "muted", wrap=True)
        content.addWidget(self.addresses)
        layout.addWidget(card)
        self.saved_box = QWidget()
        saved_layout = QVBoxLayout(self.saved_box)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        saved_layout.setSpacing(8)
        saved_header = QHBoxLayout()
        saved_header.addWidget(label("Saved servers"), 1)
        self.add_server = button("Add server", self._open_pairing)
        self.remove_server = button("Remove", self._forget_server)
        saved_header.addWidget(self.add_server)
        saved_header.addWidget(self.remove_server)
        saved_layout.addLayout(saved_header)
        self.saved_list = QListWidget()
        self.saved_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.saved_list.setFixedHeight(126)
        self.saved_list.currentItemChanged.connect(self._select_saved_server)
        saved_layout.addWidget(self.saved_list)
        layout.addWidget(self.saved_box)
        self.audio_box = QWidget()
        audio_layout = QHBoxLayout(self.audio_box)
        audio_layout.setContentsMargins(0, 2, 0, 2)
        audio_layout.setSpacing(12)
        self.audio = AudioSwitch("Controller audio")
        self.audio.setChecked(bool(self.preferences.get("audio", True)))
        self.audio.setToolTip("Forward the controller speaker, microphone and audio haptics.")
        self.audio.toggled.connect(self._change_audio)
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
        self.pair_heading = label("Connect a client", "heading")
        row.addWidget(self.pair_heading, 1)
        self.pair_back = button("Back", self._back)
        row.addWidget(self.pair_back)
        layout.addLayout(row)
        self.pair_instructions = label("", "muted", wrap=True)
        layout.addWidget(self.pair_instructions)
        self.server_pair = QWidget()
        server = QVBoxLayout(self.server_pair)
        server.setContentsMargins(0, 4, 0, 4)
        server.setSpacing(14)
        self.pair_addresses = label("", "muted", wrap=True)
        self.pair_addresses.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        server.addWidget(self.pair_addresses)
        self.pin = label("", "code")
        self.pin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        server.addStretch(1)
        server.addWidget(self.pin)
        self.pin_hint = label("Creating a pairing code…", "muted", wrap=True)
        self.pin_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        server.addWidget(self.pin_hint)
        server.addStretch(1)
        self.generate = button("New code", self._generate_code)
        code_actions = QHBoxLayout()
        code_actions.addStretch(1)
        code_actions.addWidget(self.generate)
        self.copy_code = button("Copy code", self._copy_code, primary=True)
        self.copy_code.setEnabled(False)
        code_actions.addWidget(self.copy_code)
        code_actions.addStretch(1)
        server.addLayout(code_actions)
        layout.addWidget(self.server_pair, 1)
        self.client_pair = QWidget()
        client = QVBoxLayout(self.client_pair)
        client.setContentsMargins(0, 0, 0, 0)
        client.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label("Server address"), 1)
        self.rescan = button("Find on LAN", lambda: self.engine.submit(self.engine.rescan()))
        heading.addWidget(self.rescan)
        client.addLayout(heading)
        self.manual_address = QLineEdit()
        self.manual_address.setPlaceholderText("LAN / VPN IP address or hostname")
        self.manual_address.setToolTip("Use the server's LAN, Tailscale or NetBird address.")
        self.manual_address.setText(
            self.preferences.get("game_address")
            or self.preferences.get("controller_profile", {}).get("address", "")
        )
        self.manual_address.editingFinished.connect(self._remember_address)
        client.addWidget(self.manual_address)
        self.hosts = QListWidget()
        self.hosts.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hosts.setWordWrap(True)
        self.hosts.setFixedHeight(92)
        self.hosts.itemClicked.connect(self._choose_discovered)
        client.addWidget(self.hosts)
        self.discovery_hint = label(
            "Enter the address shown on the Server, or use its VPN address.", "muted", wrap=True
        )
        client.addWidget(self.discovery_hint)
        code_row = QHBoxLayout()
        code_row.addWidget(label("Pairing code"))
        self.code = QLineEdit()
        self.code.setPlaceholderText("0000")
        self.code.setMaxLength(4)
        self.code.setFixedWidth(100)
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.returnPressed.connect(self._pair_client)
        code_row.addWidget(self.code)
        code_row.addStretch(1)
        client.addLayout(code_row)
        self.pair_error = label("", "muted", wrap=True)
        client.addWidget(self.pair_error)
        self.pair_submit = button("Connect", self._pair_client, primary=True)
        connect_row = QHBoxLayout()
        connect_row.addStretch(1)
        connect_row.addWidget(self.pair_submit)
        client.addLayout(connect_row)
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
        self.repair_button = button("Repair Windows setup…", self._repair_setup)
        layout.addWidget(self.repair_button)
        self.setup_note = label(
            "Repairs the controller driver and local-network access.", "muted", wrap=True
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
        if self.server:
            self.server.setChecked(server)
            self.client.setChecked(not server)
        self.role_caption.setText(
            "SERVER · Windows PC receiving the controller"
            if server
            else "CLIENT · Computer connected to your DualSense"
        )
        self.audio_box.setVisible(not server)
        self.auto.setVisible(not server)
        self.repair_button.setVisible(server and sys.platform == "win32")
        self.setup_note.setVisible(server and sys.platform == "win32")
        self.peer_label.setText("PAIRED CLIENT" if server else "PAIRED SERVER")
        for widget in (self.peer_gap, self.peer_label, self.peer_name, self.addresses):
            widget.setVisible(server)
        self.saved_box.setVisible(not server)
        self._refresh_saved_servers()
        self._update_peer()
        self._update_actions()
        paired = (
            self.preferences.get("game_credentials")
            if server
            else self.preferences.get("controller_profile")
        )
        if not paired:
            self._show_pair_page()
        if hasattr(self, "settings"):
            self._fit_page()

    def _fit_page(self):
        if not hasattr(self, "pages") or not self.pages.currentWidget():
            return
        self.pages.updateGeometry()
        self.centralWidget().layout().invalidate()
        self.centralWidget().layout().activate()
        pairing = self.pages.currentWidget() is getattr(self, "pair_page", None)
        mode_selection = self.pages.currentWidget() is getattr(self, "mode_page", None)
        height = (
            450
            if mode_selection
            else (460 if pairing else (500 if self.current_role == "controller" else 404))
        )
        self.setMinimumHeight(height)
        self.resize(
            max(640, self.minimumSizeHint().width()),
            max(height, self.minimumSizeHint().height() + 8),
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
        self.connect_button.setText("Disconnect" if active else "Connect")
        if not paired:
            self.connect_button.setText("Pair client" if server else "Pair server")
        self._tone(self.connect_button, "danger" if active and paired else "positive", "intent")
        self.pair_button.setText("Pair another client")
        self.pair_button.setVisible(bool(paired) and server)
        for control in (
            self.connect_button,
            self.pair_button,
            self.generate,
            self.pair_submit,
            self.pair_back,
        ):
            control.setEnabled(not self.busy)
        self.pair_submit.setText("Connecting…" if self.pairing_client else "Connect")
        self.pair_button.setEnabled(not self.busy and not self.connected)
        self.pair_button.setToolTip(
            "Disconnect before pairing another client" if self.connected else ""
        )
        for control in (self.saved_list, self.add_server, self.remove_server):
            control.setEnabled(not self.busy and not self.engine.connection)
            control.setToolTip(
                "Disconnect before changing servers" if self.engine.connection else ""
            )
        if not self.saved_list.currentItem():
            self.remove_server.setEnabled(False)
        locked = bool(self.engine.connection) or self.busy
        was_locked = self.audio.property("locked")
        self.audio.setLocked(locked)
        if was_locked and not locked:
            self.audio_status.hide()
        mode_locked = active or self.busy
        self.mode_button.setEnabled(not mode_locked)
        self.mode_button.setToolTip(
            "Disconnect to change mode"
            if active
            else "Wait for the current action to finish"
            if self.busy
            else ""
        )
        if self.server:
            self.server.setEnabled(not mode_locked)
            self.client.setEnabled(not mode_locked)
            for choice in (self.server, self.client):
                choice.setToolTip(self.mode_button.toolTip())

    def _change_audio(self, enabled):
        if self.engine.connection or self.busy:
            self.audio.blockSignals(True)
            self.audio.setChecked(bool(self.preferences.get("audio", True)))
            self.audio.blockSignals(False)
            return
        self._perform(self.engine.set_audio(enabled))

    def _role_changed(self, role):
        if sys.platform != "win32" or self.engine.receiver or self.engine.connection or self.busy:
            return
        if role == self.current_role:
            self._back()
            return
        self.current_role = role
        self.pages.setCurrentWidget(self.connection_page)
        self._show_role()
        self._perform(self.engine.set_role(role))

    def _show_pair_page(self):
        server = self.current_role == "game"
        self.pair_heading.setText("Connect a client" if server else "Add a server")
        self.pair_instructions.setText(
            "Enter this code in the Client app on your controller computer."
            if server
            else "Enter your gaming PC's address and the code shown in its Server app."
        )
        self.server_pair.setVisible(server)
        self.client_pair.setVisible(not server)
        self.pair_back.setVisible(
            bool(
                self.preferences.get("game_credentials")
                if server
                else self.preferences.get("controller_profile")
            )
        )
        if server:
            vpn = []
            for address in QNetworkInterface.allAddresses():
                value = address.toString()
                try:
                    if ipaddress.ip_address(value) in ipaddress.ip_network("100.64.0.0/10"):
                        vpn.append(value)
                except ValueError:
                    pass
            lines = ["LAN: " + ", ".join(local_addresses())]
            if vpn:
                lines.append("VPN: " + ", ".join(sorted(set(vpn))))
            self.pair_addresses.setText("\n".join(lines))
        self.pages.setCurrentWidget(self.pair_page)
        self._fit_page()

    def _open_pairing(self):
        if self.engine.connection or self.connected:
            return
        self._show_pair_page()
        self.pair_error.clear()
        if self.current_role == "game":
            if not self.engine.pairing:
                self._generate_code()
        else:
            self.code.clear()
            self.manual_address.setFocus()
            self.manual_address.selectAll()
            self.engine.submit(self.engine.rescan())

    def _back(self):
        server_pairing = (
            self.current_role == "game" and self.pages.currentWidget() is self.pair_page
        )
        self.pages.setCurrentWidget(self.connection_page)
        if server_pairing and self.engine.pairing:
            self._perform(self.engine.cancel_pairing())

    def _generate_code(self):
        self.pin.setText("••••")
        self.copy_code.setEnabled(False)
        self.pin_hint.setText("Creating a pairing code…")
        self._perform(self.engine.begin_pairing())

    def _choose_discovered(self, item):
        computer = item.data(Qt.ItemDataRole.UserRole)
        if computer:
            self.manual_address.setText(computer["address"])
            self._remember_address()
            self.code.setFocus()

    def _remember_address(self):
        if self.quitting or self.closing:
            return
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
        self.hosts.setVisible(bool(self.hosts.count()))
        self.discovery_hint.setVisible(not self.hosts.count())
        self._fit_page()

    def _refresh_saved_servers(self):
        servers = dict(saved_servers.migrate(self.preferences))
        self.saved_list.blockSignals(True)
        self.saved_list.clear()
        for identifier, profile in servers.items():
            status = self.server_states.get(identifier, "checking")
            if self.connected and identifier == self.preferences.get("selected_server"):
                status = "online"
            word = {"online": "Online", "offline": "Offline", "checking": "Checking…"}[status]
            item = QListWidgetItem(
                profile.get("name", "Gaming PC") + "  ·  " + word + "\n" + profile["address"]
            )
            item.setData(Qt.ItemDataRole.UserRole, identifier)
            item.setSizeHint(QSize(0, 54))
            item.setForeground(QColor("#64b5ff" if status == "online" else "#a1a5ad"))
            self.saved_list.addItem(item)
            if identifier == self.preferences.get("selected_server"):
                self.saved_list.setCurrentItem(item)
        self.saved_list.blockSignals(False)
        self.saved_list.setFixedHeight(54 * max(1, min(2, len(servers))) + 8)

    def _select_saved_server(self, item, previous=None):
        if item:
            identifier = item.data(Qt.ItemDataRole.UserRole)
            if identifier != self.preferences.get("selected_server"):
                self._perform(self.engine.select_server(identifier))

    def _forget_server(self):
        item = self.saved_list.currentItem()
        if item:
            self._perform(self.engine.forget_server(item.data(Qt.ItemDataRole.UserRole)))

    def _pair_client(self):
        self._tone(self.pair_error, "danger")
        address = self.manual_address.text().strip()
        if not address:
            self.pair_error.setText("Select a server, or enter its address.")
            return
        code = self.code.text().replace(" ", "").replace("-", "")
        if len(code) != 4 or not code.isascii() or not code.isdigit():
            self.pair_error.setText("Enter the 4-digit code shown in the Server app.")
            self.code.setFocus()
            return
        self.engine.submit(self.engine.update_preferences("game_address", address))
        self.pairing_client = True
        self.pair_error.setText("Connecting to Server…")
        self._tone(self.pair_error, "info")
        manual = not any(pc["address"] == address for pc in self.computers.values())
        self._perform(self.engine.pair(address, code, manual=manual))

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
            and self.pages.currentWidget() is self.connection_page
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
    def _error_heading(message):
        if "Expected one Bluetooth DualSense" in message:
            return "Controller disconnected" if "found 0" in message else "Select one controller"
        if "Steam is running" in message:
            return "Steam is using the controller"
        if "CERTIFICATE_VERIFY_FAILED" in message:
            return "Pairing no longer valid"
        if "Pairing failed" in message:
            return "Pairing failed"
        if "10048" in message or "Address already in use" in message:
            return "Another DSShine copy is running"
        if any(
            text in message
            for text in ("route", "Connect call failed", "refused", "10060", "timed out")
        ):
            return "Server unreachable"
        return "Couldn't connect"

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
                "Server unreachable. Check its address, VPN and Windows firewall, then try again."
            )
        if "10048" in message or "Address already in use" in message:
            return "Another DSShine copy is using the connection. Quit it and try again."
        return message if len(message) <= 160 else "Connection failed. Open Logs for details."

    def on_event(self, kind, value):
        if kind == "server_status":
            self.server_states[value["id"]] = value["status"]
            self._refresh_saved_servers()
            return
        if kind == "servers_changed":
            self._show_role()
            self.engine.submit(self.engine.refresh_server_status())
            return
        if kind == "client_ready":
            if not self.preferences.get("controller_profile"):
                self._open_pairing()
            return
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
            self.pairing_client = False
            self._update_actions()
            return
        if kind == "pair_code":
            self._show_pair_page()
            self.pin.setText(value if value else "Code expired")
            self.copy_code.setEnabled(bool(value))
            if value:
                self._copy_code()
            self.pin_hint.setText(
                "Copied to clipboard. Valid for 2 minutes."
                if value
                else "Generate a new code to continue pairing."
            )
            self.generate.setText("New code")
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
        if kind == "error" and not message.strip():
            message = "The request timed out. Check the server address, VPN and firewall."
        self.details.appendPlainText(
            datetime.now().strftime("%H:%M:%S") + "  " + kind + ": " + message
        )
        if kind == "error" and message == "Disconnect to change audio":
            self.audio.blockSignals(True)
            self.audio.setChecked(bool(self.preferences.get("audio", True)))
            self.audio.blockSignals(False)
            return
        if kind == "error" and message == "Disconnect before changing mode":
            self.current_role = self.preferences["role"]
            self._show_role()
            self._back()
            return
        if kind == "error":
            self.pairing_client = False
            self._tone(self.pair_error, "danger")
            self.status.setText(self._error_heading(message))
            self.description.setText(self._friendly_error(message))
            self.pair_error.setText(self._friendly_error(message))
            self.connected = False
        elif kind == "driver_needed":
            self.status.setText("Server setup needed")
            self.description.setText("Open Settings → Repair Windows setup to install the driver.")
        elif kind == "paired":
            self.pin.clear()
            self.code.clear()
            self.pages.setCurrentWidget(self.connection_page)
            self._show_role()
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
            self.status.setText("Server unreachable")
            self.description.setText(self._friendly_error(message) + " Retrying automatically…")
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
            if kind in ("error", "controller_waiting", "stopped", "reconnecting")
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

    def _copy_code(self):
        if self.copy_code.isEnabled():
            QApplication.clipboard().setText(self.pin.text())

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        else:
            event.ignore()
            self.quit()

    def quit(self):
        if self.quitting or self.closing:
            return
        self.closing = True
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
                self.closing = False
                self.busy = False
                self._update_actions()
                QMessageBox.warning(self, "Could not disconnect safely", str(exc))
                return
            self.quitting = True
            self.engine.loop.call_soon_threadsafe(self.engine.loop.stop)
            self.engine.thread.join(timeout=2)
            QApplication.instance().quit()

        check()
