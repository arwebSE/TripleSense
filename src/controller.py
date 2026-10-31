"""Scheduling adapter around the pinned physical Bluetooth backend."""

import os
import sys

from ds5emu.bridge import BridgeBackend

from .latency import interactive_thread


class ControllerBackend(BridgeBackend):
    def _native_bluetooth_enabled(self):
        return sys.platform == "darwin" and os.environ.get("DSSHINE_NATIVE_BLUETOOTH", "1") != "0"

    def _pick_device(self):
        try:
            return super()._pick_device()
        except RuntimeError:
            if self._native_bluetooth_enabled() and self.transport == "BT":
                from .macos_bluetooth import remembered_controller

                info = remembered_controller()
                if info and (not self.serial or self.serial.lower() == info.serial.lower()):
                    return info
            raise

    def _make_device(self, info):
        if self._native_bluetooth_enabled() and info.transport == "BT":
            from .macos_bluetooth import NativeDualSense

            self._opening_native = NativeDualSense(info)
            return self._opening_native
        return super()._make_device(info)

    def _open_device(self):
        try:
            return super()._open_device()
        finally:
            self._opening_native = None

    def stop(self):
        pending = getattr(self, "_opening_native", None)
        if pending is not None:
            pending.h.close()
        super().stop()

    def start(self):
        with interactive_thread():
            super().start()

    def _reader_loop(self):
        with interactive_thread():
            super()._reader_loop()

    def _pump_loop(self):
        with interactive_thread():
            super()._pump_loop()

    def _writer_loop(self):
        with interactive_thread():
            super()._writer_loop()


class StandaloneControllerBackend(ControllerBackend):
    """Forward controller audio by default; preserve an explicit off setting."""

    def __init__(self, *, audio_enabled=True, **kwargs):
        self.audio_enabled = audio_enabled
        super().__init__(auto_arm=audio_enabled, **kwargs)

    def write_audio_out(self, pcm):
        if self.audio_enabled:
            super().write_audio_out(pcm)

    def read_audio_in(self, nbytes):
        return super().read_audio_in(nbytes) if self.audio_enabled else bytes(nbytes)

    def set_alt_setting(self, interface, alt):
        if self.audio_enabled:
            super().set_alt_setting(interface, alt)

    def on_uac_control(self, unit, selector, value):
        if self.audio_enabled:
            super().on_uac_control(unit, selector, value)
