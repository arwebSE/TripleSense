"""Scheduling adapter around the pinned physical Bluetooth backend."""

from ds5emu.bridge import BridgeBackend

from .latency import interactive_thread


class ControllerBackend(BridgeBackend):
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
