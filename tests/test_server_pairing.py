import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from triplesense.app import AppEngine


class ServerPairingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = object.__new__(AppEngine)
        self.engine.root = Path(self.temporary.name)
        self.engine.preferences = {"game_credentials": "saved", "computer_id": "game"}
        self.engine.operation = asyncio.Lock()
        self.engine.receiver = self.engine.pairing = self.engine.expiry = None
        self.engine.notify = Mock()
        self.engine.save = Mock()

    async def asyncTearDown(self):
        if self.engine.expiry:
            self.engine.expiry.cancel()
            await asyncio.gather(self.engine.expiry, return_exceptions=True)
        self.temporary.cleanup()

    async def test_starting_paired_server_also_creates_code(self):
        receiver = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), owned_port=None)
        with (
            patch("triplesense.app.sys.platform", "win32"),
            patch("triplesense.app.find_usbip", return_value="usbip.exe"),
            patch("triplesense.app.GameReceiver", return_value=receiver),
            patch.object(self.engine, "_create_pairing_offer", new_callable=AsyncMock) as offer,
        ):
            await self.engine._start_game()
            offer.assert_awaited_once()
        self.assertIs(self.engine.receiver, receiver)
        receiver.stop.assert_not_awaited()

    async def test_refresh_keeps_existing_client_listener_running(self):
        receiver = SimpleNamespace(stop=AsyncMock(), owned_port=None)
        self.engine.receiver = receiver
        self.engine.pairing = SimpleNamespace(stop=AsyncMock())
        old_offer = self.engine.pairing
        with patch.object(self.engine, "_create_pairing_offer", new_callable=AsyncMock) as offer:
            await self.engine.begin_pairing()
            offer.assert_awaited_once()
        old_offer.stop.assert_awaited_once()
        receiver.stop.assert_not_awaited()

    async def test_expired_waiting_code_is_replaced_without_copying_clipboard(self):
        offer = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), code="1234")
        self.engine.receiver = SimpleNamespace(owned_port=None)
        with (
            patch("triplesense.app.PairingOffer", return_value=offer),
            patch("triplesense.app.asyncio.sleep", new_callable=AsyncMock),
        ):
            await self.engine._create_pairing_offer()
            with patch.object(
                self.engine, "_create_pairing_offer", new_callable=AsyncMock
            ) as rotate:
                await self.engine.expiry
                rotate.assert_awaited_once_with(auto_copy=False)
        offer.stop.assert_awaited_once()

    async def test_refresh_rejects_connected_controller(self):
        self.engine.receiver = SimpleNamespace(stop=AsyncMock(), owned_port=1)
        with self.assertRaisesRegex(RuntimeError, "Disconnect"):
            await self.engine.begin_pairing()
        self.engine.receiver.stop.assert_not_awaited()

    async def test_new_pair_replaces_idle_receiver_before_starting_new_identity(self):
        receiver = SimpleNamespace(stop=AsyncMock(), owned_port=None)
        self.engine.receiver = receiver
        offer = SimpleNamespace(start=AsyncMock(), code="1234")
        with (
            patch("triplesense.app.PairingOffer", return_value=offer) as factory,
            patch.object(self.engine, "_start_game", new_callable=AsyncMock) as start,
        ):
            await self.engine._create_pairing_offer()
            accepted = factory.call_args.args[1]
            credentials = self.engine.root / "identities/game-new/credentials"
            credentials.mkdir(parents=True)
            for name in ("ca.pem", "cert.pem", "key.pem"):
                (credentials / name).write_text("fixture")
            await accepted(credentials, "New client")
            receiver.stop.assert_awaited_once()
            start.assert_awaited_once()
        self.assertEqual(self.engine.preferences["controller_name"], "New client")
