"""Explicit Windows shell identity, relaunch target and taskbar icon."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import uuid
from pathlib import Path

APP_ID = "me.dsshine.app"
PROPERTY_IDS = {"relaunch_command": 2, "relaunch_icon": 3, "display_name": 4, "app_id": 5}


def application_id():
    # Development runs must not replace the installed app's taskbar association.
    return APP_ID if getattr(sys, "frozen", False) else "TripleSense.Development"


class _Guid(ctypes.Structure):
    _fields_ = [("data", ctypes.c_byte * 16)]

    def __init__(self, value):
        super().__init__((ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


class _Key(ctypes.Structure):
    _fields_ = [("guid", _Guid), ("pid", ctypes.c_uint32)]


class _Variant(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16 * 3),
        ("data", ctypes.c_void_p * 2),
    ]


def _check(result):
    if result < 0:
        raise OSError(f"Windows taskbar property operation failed: {result:#x}")


class _Store:
    def __init__(self, hwnd):
        self.pointer = ctypes.c_void_p()
        get_store = ctypes.OleDLL("shell32").SHGetPropertyStoreForWindow
        get_store.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        get_store.restype = ctypes.c_long
        _check(
            get_store(
                hwnd,
                ctypes.byref(_Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")),
                ctypes.byref(self.pointer),
            )
        )
        self.vtable = ctypes.cast(
            self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents

    def _method(self, index, *arguments):
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(self.vtable[index])

    def write(self, property_id, text):
        key = _Key(_Guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"), property_id)
        buffer = ctypes.create_unicode_buffer(text)
        value = _Variant()
        value.kind = 31  # VT_LPWSTR; SetValue copies the caller-owned string.
        value.data[0] = ctypes.cast(buffer, ctypes.c_void_p).value
        _check(
            self._method(6, ctypes.POINTER(_Key), ctypes.POINTER(_Variant))(
                self.pointer, ctypes.byref(key), ctypes.byref(value)
            )
        )

    def read(self, property_id):
        key = _Key(_Guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"), property_id)
        value = _Variant()
        try:
            _check(
                self._method(5, ctypes.POINTER(_Key), ctypes.POINTER(_Variant))(
                    self.pointer, ctypes.byref(key), ctypes.byref(value)
                )
            )
            return ctypes.wstring_at(value.data[0]) if value.kind == 31 else None
        finally:
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(value))

    def close(self):
        self._method(2)(self.pointer)  # IUnknown::Release


def set_window_identity(hwnd):
    if sys.platform != "win32":
        return
    icon = Path(__file__).with_name("assets") / "dsshine.ico"
    if not icon.is_file():
        raise FileNotFoundError(icon)
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += ["-m", "dualsensedriver.app"]
    store = _Store(hwnd)
    try:
        # Set relaunch metadata before the ID makes the window visible to the shell.
        store.write(2, subprocess.list2cmdline(command))
        store.write(3, str(icon) + ",0")
        store.write(4, "TripleSense")
        store.write(5, application_id())
        _check(store._method(7)(store.pointer))  # IPropertyStore::Commit
    finally:
        store.close()


def read_window_identity(hwnd):
    store = _Store(hwnd)
    try:
        return {name: store.read(pid) for name, pid in PROPERTY_IDS.items()}
    finally:
        store.close()
