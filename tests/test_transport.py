import asyncio
import ssl
import tempfile
import unittest
from pathlib import Path

from ds5bridge.protocol import SetState, build_usb_setstate
from ds5emu import descriptors as D
from ds5emu import wire as W
from ds5emu.backend import SyntheticBackend
from triplesense.credentials import SERVER_NAME, generate_pair, tls_context
from triplesense.transport import HostTunnel, SecureSource, close_writer, release_report

from .wire_client import Client, setup


class RecordingBackend(SyntheticBackend):
    def write_audio_out(self, pcm):
        self.last_pcm = bytes(pcm)
        super().write_audio_out(pcm)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pair = Path(self.tmp.name) / "pair"
        generate_pair(self.pair)
        self.backend = RecordingBackend()
        self.source = SecureSource(
            self.backend, tls_context(self.pair / "source", server=True), port=0
        )
        await self.source.start()
        self.tunnel = HostTunnel(
            "127.0.0.1", self.source.port, tls_context(self.pair / "host", server=False)
        )
        await self.tunnel.start()
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        await self.tunnel.stop()
        await self.source.stop()
        self.tmp.cleanup()

    async def client(self):
        client = await Client.connect(self.tunnel.port)
        self.clients.append(client)
        return client

    async def test_full_identity_and_hid_input_cross_tls(self):
        listing = await self.client()
        devices = await listing.devlist()
        self.assertEqual(len(devices), 1)
        self.assertEqual((devices[0].idVendor, devices[0].idProduct), (0x054C, 0x0CE6))
        self.assertEqual(devices[0].bNumInterfaces, 4)  # HID + complete USB audio
        controller = await self.client()
        self.assertIsNotNone(await controller.attach())
        status, descriptor = await controller.submit(
            direction=W.DIR_IN, ep=0, setup=setup(0x80, 6, 0x100, length=18), length=18
        )
        self.assertEqual(status["status"], 0)
        self.assertEqual(descriptor, D.DEVICE_DESCRIPTOR)
        status, report = await controller.submit(direction=W.DIR_IN, ep=4, length=64)
        self.assertEqual(status["status"], 0)
        self.assertEqual(len(report), 64)
        self.assertEqual(report[0], 1)

    async def test_trigger_payload_is_byte_exact(self):
        controller = await self.client()
        await controller.attach()
        effect = SetState().trigger_right(0x21, bytes(range(10))).rumble(20, 40)
        report = build_usb_setstate(bytes(effect.body))
        result, _ = await controller.submit(direction=W.DIR_OUT, ep=3, data=report)
        self.assertEqual(result["status"], 0)
        self.assertEqual(self.backend.output_reports[-1], report)

    async def test_four_channel_audio_crosses_tls_without_downmix(self):
        controller = await self.client()
        await controller.attach()
        # Windows configures the device and opens the playback alternate setting.
        for control in (setup(0, 9, 1), setup(1, 11, 1, 1)):
            result, _ = await controller.submit(direction=W.DIR_OUT, ep=0, setup=control)
            self.assertEqual(result["status"], 0)
        pcm = bytes(range(256)) + bytes(range(128))  # one 48kHz/4ch/s16 1ms packet
        result, _ = await controller.submit(
            direction=W.DIR_OUT, ep=1, data=pcm, iso=[W.IsoPacket(0, len(pcm), 0, 0)]
        )
        self.assertEqual(result["status"], 0)
        self.assertEqual(self.backend.audio_out_bytes, len(pcm))
        self.assertEqual(self.backend.last_pcm, pcm)

    async def test_idle_usb_device_stays_attached(self):
        controller = await self.client()
        await controller.attach()
        await asyncio.sleep(5.1)
        status, report = await controller.submit(direction=W.DIR_IN, ep=4, length=64)
        self.assertEqual(status["status"], 0)
        self.assertEqual(len(report), 64)

    async def test_second_import_is_refused_and_close_releases_effects(self):
        first = await self.client()
        second = await self.client()
        await first.attach()
        self.assertIsNone(await second.attach())
        await first.close()
        for _ in range(50):
            if not self.source.imported:
                break
            await asyncio.sleep(0.01)
        self.assertFalse(self.source.imported)
        self.assertEqual(self.backend.output_reports[-1], release_report())
        third = await self.client()
        self.assertIsNotNone(await third.attach())

    async def test_unpaired_host_is_refused(self):
        other = Path(self.tmp.name) / "other"
        generate_pair(other)
        bad_tunnel = HostTunnel(
            "127.0.0.1", self.source.port, tls_context(other / "host", server=False)
        )
        await bad_tunnel.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", bad_tunnel.port)
            writer.write(W.pack_op_common(W.OP_REQ_DEVLIST))
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(1), 3), b"")
            await close_writer(writer)
            self.assertIsNotNone(bad_tunnel.last_error)
            self.assertEqual(self.source.connections, 0)
        finally:
            await bad_tunnel.stop()

    async def test_missing_client_certificate_is_refused(self):
        context = ssl.create_default_context(cafile=str(self.pair / "host" / "ca.pem"))
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", self.source.port, ssl=context, server_hostname=SERVER_NAME
            )
        except ssl.SSLError:
            return
        try:
            try:
                data = await asyncio.wait_for(reader.read(1), 3)
                self.assertEqual(data, b"")
            except (ssl.SSLError, ConnectionResetError):
                pass
        finally:
            try:
                await close_writer(writer)
            except ssl.SSLError:
                pass
        self.assertEqual(self.source.connections, 0)
