"""HIDAPI-compatible access to TripleSense's owned macOS Bluetooth HID channels."""

from __future__ import annotations

import json
import logging
import queue
import re
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path

from ds5bridge.device import DeviceInfo, DualSense

log = logging.getLogger(__name__)
HEADER = struct.Struct("<IBI")


def helper_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("triplesense-bluetooth")
    return Path(__file__).resolve().parents[1] / "build/native/triplesense-bluetooth"


def remembered_controller():
    from .app_support import app_directory

    try:
        value = json.loads((app_directory() / "native-controller.json").read_text("utf-8"))
        address = value["address"]
        if not re.fullmatch(r"[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}", address):
            return None
        return DeviceInfo(b"native-bluetooth", "BT", address, "DualSense Wireless Controller")
    except (OSError, ValueError, KeyError, TypeError):
        return None


class NativeHID:
    """Binary IPC keeps controller reports in memory, outside diagnostic logs."""

    def __init__(self, info):
        self.info = info
        self.process = None
        self._send_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._next_request = 1
        self._input = queue.Queue(maxsize=2048)
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._error = None
        self._buffer = bytearray()

    def open_path(self, _path):
        path = helper_path()
        if not path.is_file():
            raise OSError(
                "TripleSense's native Bluetooth helper is missing. Reinstall TripleSense."
            )
        with self._lifecycle_lock:
            if self._closed.is_set():
                raise OSError("Bluetooth connection cancelled.")
            self.process = subprocess.Popen(
                [str(path), self.info.serial.replace(":", "-")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            self._reader = threading.Thread(
                target=self._receive, name="native-bluetooth", daemon=True
            )
            self._reader.start()
        if not self._ready.wait(23):
            self.close()
            raise OSError(
                "Bluetooth connection timed out. Allow TripleSense Bluetooth access and press PS."
            )
        if self._error or self._closed.is_set():
            self.close()
            raise OSError(self._error or "Bluetooth connection cancelled.")
        # Our connection intentionally replaces macOS's HID profile. Retain the
        # selected address so reconnecting does not depend on that removed HID.
        from .app_support import app_directory

        target = app_directory() / "native-controller.json"
        temporary = target.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps({"address": self.info.serial}), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            log.warning("Could not remember the native Bluetooth controller")

    def _read_exact(self, size):
        result = bytearray()
        while len(result) < size:
            chunk = self.process.stdout.read(size - len(result))
            if not chunk:
                raise EOFError("DualSense Bluetooth transport closed.")
            result.extend(chunk)
        return bytes(result)

    def _receive(self):
        try:
            while not self._closed.is_set():
                size, kind, request = HEADER.unpack(self._read_exact(HEADER.size))
                if size > 4096:
                    raise OSError("Invalid Bluetooth transport response.")
                payload = self._read_exact(size)
                if kind == 0:
                    self._ready.set()
                elif kind == 16:
                    self._accept_input(payload)
                elif kind == 255 and request == 0:
                    raise OSError(payload.decode("utf-8", errors="replace"))
                else:
                    with self._pending_lock:
                        response = self._pending.get(request)
                    if response is not None:
                        response.put((kind, payload))
        except (OSError, EOFError, ValueError) as error:
            self._error = str(error)
        finally:
            self._closed.set()
            self._ready.set()
            with self._pending_lock:
                for response in self._pending.values():
                    response.put((255, (self._error or "Bluetooth transport closed.").encode()))

    def _accept_input(self, chunk):
        # CBL2CAPChannel is a byte stream: a read can contain multiple HIDP
        # packets, or just part of one. A microphone packet is never a log line.
        self._buffer.extend(chunk)
        while len(self._buffer) >= 79:
            packet = self._buffer[:79]
            if packet[:2] != b"\xa1\x31" or zlib.crc32(packet[:-4]) & 0xFFFFFFFF != int.from_bytes(
                packet[-4:], "little"
            ):
                del self._buffer[0]
                continue
            del self._buffer[:79]
            try:
                self._input.put_nowait(bytes(packet[1:]))
            except queue.Full:
                # Never block the response reader: feature and write responses
                # share this pipe. Retain recent input if a consumer stalls.
                try:
                    self._input.get_nowait()
                except queue.Empty:
                    pass
                self._input.put_nowait(bytes(packet[1:]))

    def _send(self, kind, request, payload):
        with self._send_lock:
            if self._closed.is_set() or self.process is None:
                raise OSError(self._error or "Bluetooth transport is closed.")
            data = memoryview(HEADER.pack(len(payload), kind, request) + payload)
            while data:
                written = self.process.stdin.write(data)
                if not written:
                    raise OSError("Bluetooth transport command pipe closed.")
                data = data[written:]

    def _request(self, kind, payload):
        response = queue.Queue()
        with self._pending_lock:
            request = self._next_request
            self._next_request += 1
            self._pending[request] = response
        try:
            self._send(kind, request, payload)
            try:
                received_kind, data = response.get(timeout=3)
            except queue.Empty as error:
                raise OSError("Bluetooth controller request timed out.") from error
            if received_kind == 255:
                raise OSError(data.decode("utf-8", errors="replace"))
            if received_kind != kind:
                raise OSError("Unexpected Bluetooth controller response.")
            return data
        finally:
            with self._pending_lock:
                self._pending.pop(request, None)

    def get_feature_report(self, report, length):
        return self._request(1, bytes([report]))[:length]

    def send_feature_report(self, data):
        self._request(3, bytes(data))
        return len(data)

    def write(self, data):
        self._request(2, bytes(data))
        return len(data)

    def read(self, length, timeout_ms=0):
        if self._closed.is_set():
            raise OSError(self._error or "Bluetooth connection closed.")
        try:
            return self._input.get(timeout=timeout_ms / 1000 if timeout_ms else None)[:length]
        except queue.Empty:
            if self._closed.is_set():
                raise OSError(self._error or "Bluetooth connection closed.") from None
            return b""

    def close(self):
        with self._lifecycle_lock:
            self._close()

    def _close(self):
        if self.process is None:
            self._closed.set()
            self._ready.set()
            return
        try:
            if not self._closed.is_set():
                self._send(4, 0, b"")
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=2)
        finally:
            self._closed.set()
            self._reader.join(timeout=1)
            self.process.stdout.close()
            self.process = None


class NativeDualSense(DualSense):
    def __init__(self, info):
        super().__init__(info)
        self.h = NativeHID(info)
