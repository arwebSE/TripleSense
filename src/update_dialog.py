"""Shared update UI for Client and Server; network work stays off the UI thread."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from . import __version__, updates


class UpdateDialog(QDialog):
    completed = Signal(str, object)
    progress = Signal(int, int)
    available = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.release = self.package = self.mac_stage = None
        self.working = False
        self.setWindowTitle("TripleSense updates")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        self.status = QLabel(f"Installed version: {__version__}")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)
        row = QHBoxLayout()
        self.access = QPushButton("GitHub access")
        self.access.clicked.connect(self._access)
        row.addWidget(self.access)
        row.addStretch()
        self.action = QPushButton("Check for updates")
        self.action.setObjectName("primary")
        self.action.clicked.connect(self._action)
        row.addWidget(self.action)
        layout.addLayout(row)
        self.completed.connect(self._completed)
        self.progress.connect(self._progress)

    def _token(self):
        return (
            updates.github_token()
            if self.window.preferences.get("updates_private_access")
            else None
        )

    def _run(self, operation, work):
        if self.working:
            return
        self.working = True
        self.action.setEnabled(False)
        self.access.setEnabled(False)

        def run():
            try:
                result = work()
            except Exception as exc:
                self.completed.emit("error", exc)
            else:
                self.completed.emit(operation, result)

        threading.Thread(target=run, name="release-updater", daemon=True).start()

    def check(self):
        if self.working:
            return
        self.status.setText("Checking GitHub for updates…")
        self._run("check", lambda: updates.check_release(__version__, self._token()))

    def _action(self):
        if self.package:
            self.window.pending_update = (self.package, self.mac_stage)
            self.hide()
            self.window.quit()
        elif self.release:
            self.status.setText(f"Downloading TripleSense {self.release.version}…")
            self.bar.setValue(0)
            self.bar.show()

            def download():
                folder = Path(self.window.root) / "updates" / self.release.version
                package = updates.download_release(
                    self.release,
                    folder,
                    self._token(),
                    self.progress.emit,
                )
                stage = (
                    updates.stage_macos(package, self.release.version)
                    if sys.platform == "darwin"
                    else None
                )
                return package, stage

            self._run("download", download)
        else:
            self.check()

    def _completed(self, operation, result):
        self.working = False
        self.action.setEnabled(True)
        self.access.setEnabled(True)
        if operation == "error":
            self.status.setText(str(result))
            self.bar.hide()
            self.action.setText("Retry download" if self.release else "Check again")
        elif operation == "check":
            self.release = result
            self.package = self.mac_stage = None
            if result:
                self.status.setText(
                    f"TripleSense {result.version} is available. You have {__version__}."
                )
                self.action.setText("Download update")
                self.available.emit(result.version)
            else:
                self.status.setText(f"You're up to date. Installed version: {__version__}.")
                self.action.setText("Check again")
        elif operation == "download":
            self.package, self.mac_stage = result
            self.bar.hide()
            self.status.setText(
                f"TripleSense {self.release.version} is ready. "
                "Installing disconnects your controller and restarts the app."
            )
            self.action.setText("Install and restart")
            self.action.setEnabled(bool(getattr(sys, "frozen", False)))
            if not getattr(sys, "frozen", False):
                self.action.setToolTip(
                    "Install and restart is available in the packaged application."
                )
        elif operation == "access":
            self._completed_access(result)

    def _progress(self, received, total):
        self.bar.setValue(received * 100 // total)

    def _access(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("GitHub access")
        dialog.setFixedWidth(440)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Public releases need no login. For private releases, use a fine-grained "
            "GitHub token with read-only Contents access to arwebSE/TripleSense. "
            "It is saved in your system keychain. Leave empty to remove saved access."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        token_input = QLineEdit()
        token_input.setEchoMode(QLineEdit.EchoMode.Password)
        token_input.setPlaceholderText("GitHub access token")
        layout.addWidget(token_input)
        create = QPushButton("Create a token on GitHub")
        create.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/settings/personal-access-tokens/new")
            )
        )
        layout.addWidget(create)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        token = token_input.text().strip()

        def save():
            if token:
                with updates.open_github(updates.API + "/releases/latest", token) as response:
                    response.read(1)
            updates.save_github_token(token)
            return bool(token.strip())

        self._run("access", save)

    def _completed_access(self, enabled):
        self.window.preferences["updates_private_access"] = enabled
        self.window.engine.submit(
            self.window.engine.update_preferences("updates_private_access", enabled)
        )
        self.check()
