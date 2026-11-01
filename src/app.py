"""TripleSense desktop app. Python and the controller libraries ship in the bundle."""

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

from . import __version__, saved_servers
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
        self.thread = threading.Thread(target=self._run, name="triplesense-network", daemon=True)
        self.thread.start()
        self.operation = asyncio.Lock()
        self.receiver = self.connection = self.pairing = self.expiry = None
        self.discovery = None
        self.discovery_scanning = False
        self.probe_task = None
        saved_servers.profiles(self.preferences)

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
                message = str(exc).strip() or (
                    "The request timed out. Check the server address, VPN and firewall."
                    if isinstance(exc, TimeoutError)
                    else "The request failed. Open Logs for details."
                )
                self.notify("error", message)
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
            await asyncio.to_thread(self.discovery.set_scanning, self.discovery_scanning)
        except OSError:
            self.notify("discovery_unavailable", None)
        await self.set_role(
            self.preferences.get("role", "game" if sys.platform == "win32" else "controller")
            if sys.platform != "darwin"
            else "controller"
        )
        self.probe_task = asyncio.create_task(self._watch_servers())

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
                if self.preferences.get("game_credentials"):
                    await self._start_game()
                else:
                    await self._create_pairing_offer()
            else:
                self.notify("client_ready", None)

    async def _start_game(self):
        attachment = None
        if sys.platform.startswith("linux"):
            from .linux_vhci import LinuxAttachment

            attachment = LinuxAttachment()
            usbip = None
        elif sys.platform == "win32":
            usbip = find_usbip()
        else:
            raise RuntimeError(
                "macOS Server requires Apple's virtual HID entitlement. "
                "This build can run as a Client."
            )
        if not usbip and attachment is None:
            self.notify("driver_needed", None)
            return
        credentials = self.preferences.get("game_credentials")
        if not credentials:
            self.notify("waiting", "Pair your controller computer to get started")
            if not self.pairing:
                await self._create_pairing_offer()
            return
        receiver = GameReceiver(
            credentials,
            self.notify,
            usbip=usbip,
            ownership_file=self.root / "usb-session.json" if usbip else None,
            attachment=attachment,
            touchpad_mouse=bool(self.preferences.get("touchpad_mouse", False)),
        )
        await receiver.start()
        self.receiver = receiver
        self.notify("waiting", "Ready for your controller computer")
        if not self.pairing:
            await self._create_pairing_offer()

    async def begin_pairing(self):
        async with self.operation:
            if self.receiver and self.receiver.owned_port is not None:
                raise RuntimeError("Disconnect before pairing another client")
            if self.expiry:
                self.expiry.cancel()
                self.expiry = None
            if self.pairing:
                await self.pairing.stop()
                self.pairing = None
            if not self.receiver and self.preferences.get("game_credentials"):
                await self._start_game()
                return
            await self._create_pairing_offer()

    async def _create_pairing_offer(self, *, auto_copy=True):
        async def accepted(credentials, name):
            if self.receiver:
                if self.receiver.owned_port is not None:
                    raise RuntimeError("Disconnect before pairing another client")
                await self.receiver.stop()
                self.receiver = None
            self.preferences["game_credentials"] = str(credentials)
            self.preferences["controller_name"] = name
            from .server_identity import remember

            remember(self.root, credentials, name)
            self.save()
            await self._start_game()
            self.notify("pair_code", "")
            self.notify("paired", name)

        self.pairing = PairingOffer(
            self.root / "identities", accepted, host_id=self.preferences["computer_id"]
        )
        await self.pairing.start()
        offer = self.pairing
        self.notify("pair_code" if auto_copy else "pair_code_rotated", self.pairing.code)

        async def expire():
            await asyncio.sleep(120)
            async with self.operation:
                if self.pairing is not offer:
                    return
                await self.pairing.stop()
                self.pairing = None
                if not self.receiver or self.receiver.owned_port is None:
                    await self._create_pairing_offer(auto_copy=False)
                else:
                    self.notify("pair_code", "")

        self.expiry = asyncio.create_task(expire())

    async def cancel_pairing(self):
        async with self.operation:
            await self._stop()
            if self.preferences.get("game_credentials"):
                await self._start_game()

    async def pair(self, address, code, *, manual=False, transport=None):
        async with self.operation:
            if self.connection:
                await self._stop()
            try:
                async with asyncio.timeout(15):
                    profile = await pair_controller(address, code, self.root / "identities")
            except TimeoutError as exc:
                raise TimeoutError(
                    str(exc) or "Pairing timed out. Check your address and VPN."
                ) from exc
            profile["manual_address"] = manual
            if transport:
                profile["transport"] = transport
            saved_servers.remember(self.preferences, profile)
            self.save()
            await self.set_discovery_scanning(False)
            self.notify("servers_changed", None)
            self.notify("paired", profile["name"])
        await self.connect()

    async def select_server(self, identifier):
        async with self.operation:
            if self.connection and identifier != self.preferences.get("selected_server"):
                raise RuntimeError("Disconnect before selecting another server")
            saved_servers.select(self.preferences, identifier)
            self.save()
            self.notify("servers_changed", None)

    async def forget_server(self, identifier):
        async with self.operation:
            if self.connection:
                raise RuntimeError("Disconnect before removing a server")
            saved_servers.forget(self.preferences, identifier, self.root)
            self.save()
            self.notify("servers_changed", None)

    async def refresh_server_status(self):
        semaphore = asyncio.Semaphore(3)

        async def check(identifier, profile):
            async with semaphore:
                status = await saved_servers.probe(profile)
                self.notify("server_status", {"id": identifier, "status": status})

        await asyncio.gather(
            *(
                check(key, dict(value))
                for key, value in dict(self.preferences.get("servers", {})).items()
            )
        )

    async def _watch_servers(self):
        while True:
            if self.preferences.get("role") == "controller":
                await self.refresh_server_status()
            await asyncio.sleep(5)

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
            self.notify("connecting", "Opening your DualSense Bluetooth connection…")
            await asyncio.to_thread(require_controller_isolation)
            selected = await asyncio.to_thread(choose_controller, None, allow_remembered=True)
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
            and profile.get("host_id")
            and profile["host_id"] == computer.get("host_id")
            and profile["address"] != computer["address"]
            and not profile.get("manual_address")
        ):
            # Discovery changes the destination, never the pinned TLS identity.
            profile["address"] = computer["address"]
            self.preferences["game_address"] = computer["address"]
            self.save()

    async def rescan(self):
        if self.discovery:
            await asyncio.to_thread(self.discovery.scan)

    async def set_discovery_scanning(self, enabled):
        self.discovery_scanning = enabled
        if self.discovery:
            await asyncio.to_thread(self.discovery.set_scanning, enabled)

    async def set_audio(self, enabled):
        async with self.operation:
            if self.connection:
                raise RuntimeError("Disconnect to change audio")
            self.preferences["audio"] = enabled
            self.save()

    async def shutdown(self):
        if self.probe_task:
            self.probe_task.cancel()
            await asyncio.gather(self.probe_task, return_exceptions=True)
            self.probe_task = None
        await self.stop()
        if self.discovery:
            await asyncio.to_thread(self.discovery.close)
            self.discovery = None
        await self.loop.shutdown_asyncgens()
        await self.loop.shutdown_default_executor()

    async def diagnostics(self):
        result = {"version": __version__, "role": self.preferences.get("role")}
        if self.receiver:
            result["server"] = {
                "attached": self.receiver.owned_port is not None,
                "mouse_enabled": self.receiver.touchpad_mouse,
                "last_error": self.receiver.last_error,
            }
        if self.connection:
            backend = self.connection.backend
            result["controller"] = {
                "status": backend.device_status(),
                "stats": backend.stats.copy(),
                "threads": [(t.name, t.is_alive()) for t in backend._threads],
                "stopping": backend._stop.is_set(),
            }
            device = backend._dev
            handle = device.h if device else None
            if hasattr(handle, "_input"):
                result["controller"]["native"] = {
                    "queued_reports": handle._input.qsize(),
                    "buffered_bytes": len(handle._buffer),
                    "closed": handle._closed.is_set(),
                    "error": handle._error,
                }
        return result


from .desktop import Window  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="TripleSense desktop app")
    parser.add_argument("--data-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--quit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repair-setup", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        import ctypes

        from .windows_taskbar import application_id

        # Keep the taskbar separate from Python and match the installer shortcuts.
        identify = ctypes.OleDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        identify.argtypes = [ctypes.c_wchar_p]
        identify.restype = ctypes.c_long
        result = identify(application_id())
        if result < 0:
            raise OSError(f"Could not set the Windows app identity: {result:#x}")
    if args.repair_setup:
        from .setup import repair_windows

        application = QApplication(sys.argv[:1])
        application.setWindowIcon(
            QIcon(str(Path(__file__).with_name("assets") / "triplesense.png"))
        )
        try:
            repair_windows()
            QMessageBox.information(
                None,
                "TripleSense setup repaired",
                "Driver and local-network access are ready.",
            )
            return 0
        except Exception as exc:
            QMessageBox.warning(None, "TripleSense setup needs attention", str(exc))
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
    application.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "triplesense.png")))
    application.setApplicationName("TripleSense")
    application.setOrganizationName("TripleSense")
    application.setQuitOnLastWindowClosed(False)
    application.setFont(
        QFont(
            "Segoe UI"
            if sys.platform == "win32"
            else ".AppleSystemUIFont"
            if sys.platform == "darwin"
            else "Sans Serif",
            10,
        )
    )
    root = args.data_dir or app_directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    import hashlib

    endpoint = "TripleSense-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
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
    for name in ("mouse_proxy", "touchpad_mouse"):
        logging.getLogger(f"triplesense.{name}").setLevel(logging.INFO)
    # cython-hidapi initializes IOHIDManager at import and finalizes at atexit.
    # macOS requires that owner thread to survive until hid_exit, on that same
    # thread. Import before the engine can first import it in an executor.
    if sys.platform == "darwin":
        importlib.import_module("hid")
    window = Window(root, smoke_test=bool(args.smoke_test))
    if sys.platform == "win32":
        from .windows_taskbar import set_window_identity

        set_window_identity(int(window.winId()))
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(endpoint)
    server.listen(endpoint)

    def incoming():
        peer = server.nextPendingConnection()

        def command():
            message = bytes(peer.readAll())
            if message == b"diagnostics":
                future = asyncio.run_coroutine_threadsafe(
                    window.engine.diagnostics(), window.engine.loop
                )

                def respond():
                    if not future.done():
                        QTimer.singleShot(25, respond)
                        return
                    try:
                        peer.write(json.dumps(future.result()).encode())
                        peer.disconnectFromServer()
                    except (RuntimeError, OSError):
                        pass

                respond()
                return
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
        if preferences.get("launch_at_login", True):
            try:
                set_launch_at_login(True)
                window.login.setChecked(True)
                window.engine.submit(window.engine.update_preferences("launch_at_login", True))
            except (OSError, RuntimeError) as exc:
                window.on_event("error", "Could not enable automatic startup: " + str(exc))
    if not args.smoke_test:
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
                from .windows_taskbar import read_window_identity

                metadata["window_shell"] = read_window_identity(int(window.winId()))
            args.smoke_test.with_suffix(".json").write_text(json.dumps(metadata))
            window.grab().save(str(args.smoke_test))
            window.quit()

        QTimer.singleShot(1800, smoke)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
