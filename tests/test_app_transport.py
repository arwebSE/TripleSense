import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ds5bridge.protocol import SetState, build_usb_setstate
from ds5emu import wire as W
from ds5emu.backend import SyntheticBackend

from dualsensedriver.credentials import generate_pair
from dualsensedriver.pairing import PairingOffer, pair_controller
from dualsensedriver.reverse import ControllerConnection, GameReceiver
from dualsensedriver.transport import release_report

from .test_touchpad_mouse import Output, report
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
        self.assertEqual(len(self.offer.code), 4)
        self.assertTrue(self.offer.code.isascii() and self.offer.code.isdigit())
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
        wrong = "0000" if self.offer.code != "0000" else "1111"
        with self.assertRaises(ValueError):
            await pair_controller(
                "127.0.0.1", wrong, self.root / "controller", port=self.offer.port
            )
        self.assertEqual(self.paired, [])
        self.assertFalse((self.root / "controller").exists())
        self.assertEqual(self.offer.attempts, 1)

    async def test_touchpad_mouse_works_through_paired_tls_and_releases_output(self):
        profile = await pair_controller(
            "127.0.0.1", self.offer.code, self.root / "controller", port=self.offer.port
        )
        output = Output()
        backend = SyntheticBackend()
        current = report()
        backend.read_input_report = lambda length: current[:length]
        receiver = GameReceiver(
            self.paired[0][0],
            lambda *args: None,
            port=0,
            bind="127.0.0.1",
            touchpad_mouse=True,
        )
        with patch("dualsensedriver.mouse_output.create_mouse", return_value=output):
            await receiver.start()
        profile["port"] = receiver.port
        controller = ControllerConnection(profile, backend, lambda *args: None)
        try:
            await controller.start()
            client = await Client.connect(receiver.local_port)
            try:
                self.assertIsNotNone(await client.attach())
                for points in ((), ((1, 100, 100),), ((1, 140, 110),)):
                    current = report(points)
                    result, masked = await client.submit(direction=W.DIR_IN, ep=4, length=64)
                    self.assertEqual(result["status"], 0)
                    self.assertEqual(masked[:33], current[:33])
                    self.assertTrue(masked[33] & 0x80)
                self.assertTrue(any(event[0] == "move" for event in output.events))
                effect = build_usb_setstate(
                    bytes(SetState().trigger_right(0x21, b"\x01" * 10).body)
                )
                await client.submit(direction=W.DIR_OUT, ep=3, data=effect)
                self.assertEqual(backend.output_reports[-1], effect)
            finally:
                await client.close()
        finally:
            await receiver.stop()
            await controller.stop()
        self.assertEqual(output.events[-1], ("close",))

    async def test_network_timeout_has_actionable_message(self):
        with patch(
            "dualsensedriver.pairing.asyncio.open_connection", new_callable=AsyncMock
        ) as dial:
            dial.side_effect = TimeoutError()
            with self.assertRaisesRegex(TimeoutError, "VPN connection and Windows firewall"):
                await pair_controller("100.97.43.25", self.offer.code, self.root / "client")
        self.assertFalse((self.root / "client").exists())

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
