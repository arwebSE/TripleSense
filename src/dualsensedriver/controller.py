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


class StandaloneControllerBackend(ControllerBackend):
    """Keep experimental controller audio opt-in in the desktop app."""

    def __init__(self, *, audio_enabled=False, **kwargs):
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
