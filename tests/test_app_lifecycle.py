import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from triplesense.app import AppEngine
from triplesense.controller import StandaloneControllerBackend
from triplesense.credentials import generate_pair
from triplesense.reverse import GameReceiver


class AudioOptInTests(unittest.TestCase):
    def test_explicit_audio_off_does_not_arm_mic_or_queue_audio(self):
        backend = StandaloneControllerBackend(audio_enabled=False)
        backend.set_alt_setting(1, 1)
        backend.set_alt_setting(2, 1)
        backend.write_audio_out(bytes(384))
        self.assertFalse(backend._audio_armed.is_set())
        self.assertFalse(backend._mic_armed.is_set())
        self.assertEqual(backend.read_audio_in(192), bytes(192))
        self.assertEqual(backend.stats["audio_out_bytes"], 0)

    def test_audio_is_enabled_by_default(self):
        self.assertTrue(StandaloneControllerBackend().audio_enabled)


class AppCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        generate_pair(self.root / "pair")
        self.record = self.root / "owned.json"

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_audio_change_rejects_live_session_without_reconnecting(self):
        engine = object.__new__(AppEngine)
        engine.root = self.root
        engine.operation = asyncio.Lock()
        engine.preferences = {"audio": True}
        engine.connection = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "Disconnect to change audio"):
            await engine.set_audio(False)
        self.assertTrue(engine.preferences["audio"])
        engine.connection.stop.assert_not_awaited()

    async def test_restart_checks_previous_ownership_before_opening_another_device(self):
        self.record.write_text(
            json.dumps(
                {
                    "port": 3,
                    "tcp_port": 45678,
                    "serial": "TRSA123456789ab",
                }
            )
        )
        receiver = GameReceiver(
            self.root / "pair/source",
            lambda *args: None,
            usbip="usbip.exe",
            port=0,
            bind="127.0.0.1",
            ownership_file=self.record,
        )
        with patch("triplesense.reverse.detach_owned", new_callable=AsyncMock) as detach:
            detach.return_value = False  # Port absent or reassigned: never forcibly detach it.
            try:
                await receiver.start()
                detach.assert_awaited_once_with("usbip.exe", 3, 45678, "TRSA123456789ab")
                self.assertFalse(self.record.exists())
            finally:
                await receiver.stop()

    async def test_malformed_ownership_record_never_reaches_driver(self):
        self.record.write_text(
            json.dumps(
                {
                    "port": 0,
                    "tcp_port": 45678,
                    "serial": "other-device",
                }
            )
        )
        receiver = GameReceiver(
            self.root / "pair/source",
            lambda *args: None,
            usbip="usbip.exe",
            port=0,
            ownership_file=self.record,
        )
        with patch("triplesense.reverse.detach_owned", new_callable=AsyncMock) as detach:
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                await receiver.start()
            detach.assert_not_awaited()
            self.assertTrue(self.record.exists())

    async def test_failed_detach_preserves_record_and_can_be_retried(self):
        receiver = GameReceiver(
            self.root / "pair/source",
            lambda *args: None,
            usbip="usbip.exe",
            port=0,
            bind="127.0.0.1",
            ownership_file=self.record,
        )
        await receiver.start()
        receiver.owned_port = 3
        self.record.write_text(
            json.dumps(
                {
                    "port": 3,
                    "tcp_port": receiver.local_port,
                    "serial": receiver.serial,
                }
            )
        )
        with patch("triplesense.reverse.detach_owned", new_callable=AsyncMock) as detach:
            detach.side_effect = RuntimeError("driver unavailable")
            with self.assertRaisesRegex(RuntimeError, "driver unavailable"):
                await receiver.stop()
            self.assertEqual(receiver.owned_port, 3)
            self.assertTrue(self.record.exists())
            detach.side_effect = None
            detach.return_value = True
            await receiver.stop()
            self.assertIsNone(receiver.owned_port)
            self.assertFalse(self.record.exists())

    async def test_quit_during_attach_still_records_the_port_for_cleanup(self):
        receiver = GameReceiver(
            self.root / "pair/source",
            lambda *args: None,
            usbip="usbip.exe",
            port=0,
            ownership_file=self.record,
        )
        receiver.local_port = 45678
        entered, complete = asyncio.Event(), asyncio.Event()

        async def slow_attach(*args):
            entered.set()
            await complete.wait()
            return "3"

        with patch("triplesense.reverse.run_usbip", side_effect=slow_attach):
            task = asyncio.create_task(receiver._attach_once())
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            complete.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(receiver.owned_port, 3)
        self.assertEqual(json.loads(self.record.read_text())["port"], 3)
        with patch("triplesense.reverse.detach_owned", new_callable=AsyncMock) as detach:
            await receiver.stop()
            detach.assert_awaited_once_with("usbip.exe", 3, 45678, receiver.serial)
            self.assertFalse(self.record.exists())
