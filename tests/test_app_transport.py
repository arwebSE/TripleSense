import asyncio
import tempfile
import unittest
from pathlib import Path

from ds5bridge.protocol import SetState, build_usb_setstate
from ds5emu import wire as W
from ds5emu.backend import SyntheticBackend

from dualsensedriver.credentials import generate_pair
from dualsensedriver.pairing import PairingOffer, pair_controller
from dualsensedriver.reverse import ControllerConnection, GameReceiver
from dualsensedriver.transport import release_report

from .wire_client import Client


class AppPairingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paired = []

        async def accepted(credentials, name):
            self.paired.append((credentials, name))

        self.offer = PairingOffer(self.root / "game", accepted, host="127.0.0.1", port=0)
        await self.offer.start()

    async def asyncTearDown(self):
        await self.offer.stop()
        self.tmp.cleanup()

    async def test_pin_exchanges_separate_credentials_and_reverse_tls_works(self):
        profile = await pair_controller(
            "127.0.0.1", self.offer.code, self.root / "controller", port=self.offer.port
        )
        self.assertEqual(len(self.paired), 1)
        # The Windows identity never goes to the controller, and vice versa.
        game_key = (self.paired[0][0] / "key.pem").read_bytes()
        client_key = (Path(profile["credentials"]) / "key.pem").read_bytes()
        self.assertNotEqual(game_key, client_key)
        self.assertFalse((self.paired[0][0].parent / "host").exists())
        await self.offer.stop()
        self.assertFalse(list((self.root / "game").glob("pairing-*")))
        receiver = GameReceiver(self.paired[0][0], lambda *args: None, port=0, bind="127.0.0.1")
        await receiver.start()
        profile["port"] = receiver.port
        backend = SyntheticBackend()
        controller = ControllerConnection(profile, backend, lambda *args: None)
        try:
            await controller.start()
            client = await Client.connect(receiver.local_port)
            try:
                self.assertIsNotNone(await client.attach())
                result, report = await client.submit(direction=W.DIR_IN, ep=4, length=64)
                self.assertEqual(result["status"], 0)
                self.assertEqual(len(report), 64)
                effect = build_usb_setstate(
                    bytes(SetState().trigger_right(0x21, b"\x01" * 10).body)
                )
                await client.submit(direction=W.DIR_OUT, ep=3, data=effect)
                self.assertEqual(backend.output_reports[-1], effect)
            finally:
                await client.close()
            for _ in range(50):
                if release_report() in backend.output_reports:
                    break
                await asyncio.sleep(0.01)
            self.assertIn(release_report(), backend.output_reports)
        finally:
            await receiver.stop()
            await controller.stop()

    async def test_wrong_pin_is_rejected_without_saving_client_keys(self):
        wrong = "00000000" if self.offer.code != "00000000" else "11111111"
        with self.assertRaises(ValueError):
            await pair_controller(
                "127.0.0.1", wrong, self.root / "controller", port=self.offer.port
            )
        self.assertEqual(self.paired, [])
        self.assertFalse((self.root / "controller").exists())
        self.assertEqual(self.offer.attempts, 1)

    async def test_expired_pin_is_rejected(self):
        self.offer.expires = 0
        with self.assertRaises((ValueError, OSError)):
            await pair_controller(
                "127.0.0.1", self.offer.code, self.root / "controller", port=self.offer.port
            )
        self.assertEqual(self.paired, [])

    async def test_one_pairing_offer_cannot_enroll_a_second_controller(self):
        await pair_controller("127.0.0.1", self.offer.code, self.root / "one", port=self.offer.port)
        with self.assertRaises((ValueError, OSError)):
            await pair_controller(
                "127.0.0.1", self.offer.code, self.root / "two", port=self.offer.port
            )
        self.assertEqual(len(self.paired), 1)

    async def test_unpaired_identity_cannot_offer_a_controller(self):
        other = self.root / "unpaired"
        generate_pair(other)
        receiver = GameReceiver(
            self.offer.pair / "source", lambda *args: None, port=0, bind="127.0.0.1"
        )
        await receiver.start()
        controller = ControllerConnection(
            {"credentials": str(other / "host"), "address": "127.0.0.1", "port": receiver.port},
            SyntheticBackend(),
            lambda *args: None,
        )
        try:
            await controller.start()
            await asyncio.sleep(0.3)
            self.assertEqual(len(receiver.offers), 0)
            self.assertFalse(controller.source.imported)
        finally:
            await receiver.stop()
            await controller.stop()
