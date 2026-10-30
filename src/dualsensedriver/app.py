"""DSShine desktop app. Python and the controller libraries ship in the bundle."""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import importlib
import json
import logging
import sys
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
)

from .app_support import (
    Discovery,
    app_directory,
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
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def submit(self, coroutine, *, busy=False):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)

        def completed(done):
            try:
                done.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception as exc:
                self.notify("error", str(exc))
            finally:
                if busy:
                    self.notify("idle", None)

        future.add_done_callback(completed)
        return future

    async def initialize(self):
        self.preferences.setdefault("computer_id", uuid.uuid4().hex)
        self.preferences.setdefault("audio", True)
        self.save()
        try:
            self.discovery = await asyncio.to_thread(
                Discovery, self.notify, self.preferences["computer_id"]
            )
        except OSError:
            self.notify("discovery_unavailable", None)
        await self.set_role(
            self.preferences.get("role", "game") if sys.platform == "win32" else "controller"
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
            if (self.receiver or self.connection) and role != self.preferences.get("role"):
                raise RuntimeError("Disconnect before changing mode")
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

            self.pairing = PairingOffer(
                self.root / "identities", accepted, host_id=self.preferences["computer_id"]
            )
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
            if self.connection:
                await self._stop()
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
                audio_enabled=bool(self.preferences.get("audio", True)),
            )
            connection = ControllerConnection(profile, backend, self.notify)
            await connection.start()
            self.connection = connection
            self.notify("controller_started", selected.product)

    async def update_preferences(self, key, value):
        self.preferences[key] = value
        self.save()

    async def discovered(self, computer):
        profile = self.preferences.get("controller_profile")
        if (
            profile
            and not profile.get("host_id")
            and computer.get("host_id")
            and profile["address"] == computer["address"]
            and computer.get("dsshine")
        ):
            # Upgrade an existing pair only after verifying its pinned TLS CA.
            from .credentials import SERVER_NAME, tls_context
            from .transport import close_writer

            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        profile["address"],
                        profile["port"],
                        ssl=tls_context(Path(profile["credentials"]), server=False),
                        server_hostname=SERVER_NAME,
                        ssl_handshake_timeout=3,
                        ssl_shutdown_timeout=1,
                    ),
                    5,
                )
                await close_writer(writer)
            except (OSError, TimeoutError):
                return
            profile["host_id"] = computer["host_id"]
            self.save()
        if (
            profile
            and profile.get("host_id")
            and profile["host_id"] == computer.get("host_id")
            and profile["address"] != computer["address"]
        ):
            # Discovery changes the destination, never the pinned TLS identity.
            profile["address"] = computer["address"]
            self.preferences["game_address"] = computer["address"]
            self.save()

    async def rescan(self):
        if self.discovery:
            await asyncio.to_thread(self.discovery.scan)

    async def set_audio(self, enabled):
        async with self.operation:
            if self.connection:
                raise RuntimeError("Disconnect to change audio")
            self.preferences["audio"] = enabled
            self.save()

    async def shutdown(self):
        await self.stop()
        if self.discovery:
            await asyncio.to_thread(self.discovery.close)
            self.discovery = None
        await self.loop.shutdown_asyncgens()
        await self.loop.shutdown_default_executor()


from .desktop import Window  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="DSShine desktop app")
    parser.add_argument("--data-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--quit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repair-setup", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        import ctypes

        # Keep the taskbar separate from Python and match the installer shortcuts.
        identify = ctypes.OleDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        identify.argtypes = [ctypes.c_wchar_p]
        identify.restype = ctypes.c_long
        result = identify("DSShine.Desktop")
        if result < 0:
            raise OSError(f"Could not set the Windows app identity: {result:#x}")
    if args.repair_setup:
        from .setup import repair_windows

        application = QApplication(sys.argv[:1])
        application.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "dsshine.png")))
        try:
            repair_windows()
            QMessageBox.information(
                None,
                "DSShine setup repaired",
                "Driver and local-network access are ready.",
            )
            return 0
        except Exception as exc:
            QMessageBox.warning(None, "DSShine setup needs attention", str(exc))
            return 1
    if args.smoke_test:
        try:
            from ds5bridge.audio import silent_opus_frame

            from .controller import StandaloneControllerBackend

            # Import and exercise the frozen codec stack without opening HID.
            packet = silent_opus_frame()
            if len(packet) != 200:
                raise RuntimeError("The bundled Opus encoder returned an invalid frame")
            StandaloneControllerBackend()
        except Exception as exc:
            args.smoke_test.with_suffix(".json").write_text(json.dumps({"error": str(exc)}))
            return 1
    application = QApplication(sys.argv[:1])
    application.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "dsshine.png")))
    application.setApplicationName("DSShine")
    application.setOrganizationName("DSShine")
    application.setQuitOnLastWindowClosed(False)
    application.setFont(QFont("Segoe UI" if sys.platform == "win32" else ".AppleSystemUIFont", 10))
    root = args.data_dir or app_directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    import hashlib

    endpoint = "DSShine-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
    if args.quit:
        peer = QLocalSocket()
        peer.connectToServer(endpoint)
        if peer.waitForConnected(1500):
            peer.write(b"quit")
            peer.waitForBytesWritten(1500)
        return 0
    lock = QLockFile(str(root / "app.lock"))
    if not lock.tryLock(100):
        peer = QLocalSocket()
        peer.connectToServer(endpoint)
        if peer.waitForConnected(1500):
            peer.write(b"show")
            peer.waitForBytesWritten(1500)
        return 0
    logging.basicConfig(level=logging.WARNING, filename=root / "app.log", encoding="utf-8")
    # cython-hidapi initializes IOHIDManager at import and finalizes at atexit.
    # macOS requires that owner thread to survive until hid_exit, on that same
    # thread. Import before the engine can first import it in an executor.
    if sys.platform == "darwin":
        importlib.import_module("hid")
    window = Window(root, smoke_test=bool(args.smoke_test))
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(endpoint)
    server.listen(endpoint)

    def incoming():
        peer = server.nextPendingConnection()

        def command():
            message = bytes(peer.readAll())
            if message == b"quit":
                window.quit()
            elif message == b"show":
                window.showNormal()
                window.raise_()
                window.activateWindow()
            peer.disconnectFromServer()

        peer.readyRead.connect(command)
        peer.disconnected.connect(peer.deleteLater)
        if peer.bytesAvailable():
            command()

    server.newConnection.connect(incoming)
    if getattr(sys, "frozen", False) and not args.smoke_test:
        preferences = window.preferences
        if "launch_at_login" not in preferences:
            try:
                set_launch_at_login(True)
                window.login.setChecked(True)
                window.engine.submit(window.engine.update_preferences("launch_at_login", True))
            except (OSError, RuntimeError) as exc:
                window.on_event("error", "Could not enable automatic startup: " + str(exc))
    # Accept the legacy flag so existing login entries still open a visible app.
    window.show()
    if args.smoke_test:

        def smoke():
            metadata = {"icon_valid": not window.windowIcon().pixmap(32, 32).isNull()}
            if sys.platform == "win32":
                identity = ctypes.c_wchar_p()
                ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(
                    ctypes.byref(identity)
                )
                metadata["windows_app_id"] = identity.value
                ctypes.windll.ole32.CoTaskMemFree(identity)
            args.smoke_test.with_suffix(".json").write_text(json.dumps(metadata))
            window.grab().save(str(args.smoke_test))
            window.quit()

        QTimer.singleShot(1800, smoke)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
