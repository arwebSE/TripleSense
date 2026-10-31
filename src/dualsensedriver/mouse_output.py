"""Small adapters to existing OS pointer injection APIs."""

from __future__ import annotations

import ctypes
import sys


class WindowsMouse:
    def __init__(self):
        # INPUT includes the largest member of its union (MOUSEINPUT). Pointer
        # size and native alignment matter on both Windows architectures.
        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_int32),
                ("dy", ctypes.c_int32),
                ("data", ctypes.c_uint32),
                ("flags", ctypes.c_uint32),
                ("time", ctypes.c_uint32),
                ("extra", ctypes.c_size_t),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("mouse", MouseInput)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_uint32), ("value", InputUnion)]

        self.MouseInput, self.InputUnion, self.Input = MouseInput, InputUnion, Input
        self.send = ctypes.windll.user32.SendInput
        self.send.argtypes = [ctypes.c_uint, ctypes.POINTER(Input), ctypes.c_int]
        self.send.restype = ctypes.c_uint

    def _send(self, flags, dx=0, dy=0, data=0):
        item = self.Input(0, self.InputUnion(self.MouseInput(dx, dy, data, flags, 0, 0)))
        if self.send(1, ctypes.byref(item), ctypes.sizeof(item)) != 1:
            raise OSError("Windows could not send the touchpad mouse event.")

    def move(self, dx, dy):
        self._send(1, dx, dy)

    def button(self, name, down):
        self._send(
            {("left", True): 2, ("left", False): 4, ("right", True): 8, ("right", False): 16}[
                name, down
            ]
        )

    def scroll(self, steps):
        self._send(0x800, data=steps * 120)

    def close(self):
        pass


class LinuxMouse:
    def __init__(self):
        from evdev import UInput
        from evdev import ecodes as E

        self.E = E
        try:
            self.device = UInput(
                {E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT], E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL]},
                name="TripleSense touchpad mouse",
            )
        except OSError as exc:
            raise RuntimeError(
                "Install the Linux package and sign in again to enable the mouse."
            ) from exc

    def move(self, dx, dy):
        self.device.write(self.E.EV_REL, self.E.REL_X, dx)
        self.device.write(self.E.EV_REL, self.E.REL_Y, dy)
        self.device.syn()

    def button(self, name, down):
        self.device.write(
            self.E.EV_KEY, self.E.BTN_LEFT if name == "left" else self.E.BTN_RIGHT, int(down)
        )
        self.device.syn()

    def scroll(self, steps):
        self.device.write(self.E.EV_REL, self.E.REL_WHEEL, steps)
        self.device.syn()

    def close(self):
        self.device.close()


def create_mouse():
    if sys.platform == "win32":
        return WindowsMouse()
    if sys.platform.startswith("linux"):
        return LinuxMouse()
    raise RuntimeError("Touchpad mouse output is not available on this Server yet.")
