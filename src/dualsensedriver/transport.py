"""Mutually authenticated USB/IP transport, with a loopback-only driver endpoint."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import socket
import ssl

from ds5emu import wire as W
from ds5emu.server import UsbIpServer

from .credentials import SERVER_NAME

log = logging.getLogger(__name__)


async def close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError, TimeoutError):
        await asyncio.wait_for(writer.wait_closed(), 1)


def low_latency(writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    if sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for option, value in (("TCP_KEEPIDLE", 1), ("TCP_KEEPINTVL", 1), ("TCP_KEEPCNT", 5)):
            if hasattr(socket, option):
                with contextlib.suppress(OSError):
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, option), value)


class SecureSource(UsbIpServer):
    """Full USB device over TLS; exactly one importer owns the physical pad."""

    def __init__(self, backend, context: ssl.SSLContext, **kwargs):
        super().__init__(backend, **kwargs)
        self.context = context
        self.imported = False
        self.handlers: set[asyncio.Task] = set()

    async def start(self) -> None:
        try:
            await asyncio.to_thread(self.backend.start)
            self._server = await asyncio.start_server(
                self._tracked_client,
                self.host,
                self.port,
                ssl=self.context,
                ssl_handshake_timeout=5,
                ssl_shutdown_timeout=1,
            )
            self.port = self._server.sockets[0].getsockname()[1]
        except BaseException:
            await asyncio.to_thread(self.backend.stop)
            raise

    async def _tracked_client(self, reader, writer) -> None:
        task = asyncio.current_task()
        self.handlers.add(task)
        try:
            low_latency(writer)
            await self._handle_client(reader, writer)
        finally:
            self.handlers.discard(task)

    async def _op_phase(self, reader, writer) -> None:
        header = await asyncio.wait_for(reader.readexactly(W.OP_COMMON_SIZE), 5)
        version, code, status = W.unpack_op_common(header)
        if version != W.USBIP_VERSION or status != 0:
            return
        if code == W.OP_REQ_DEVLIST:
            info = self.device.usbip_device_info(busid=self.busid)
            writer.write(W.pack_devlist_reply([] if self.imported else [info]))
            await writer.drain()
        elif code == W.OP_REQ_IMPORT:
            body = await asyncio.wait_for(reader.readexactly(W.BUS_ID_SIZE), 5)
            busid = W.unpack_import_request_body(body)
            if self.imported or busid != self.busid:
                writer.write(W.pack_import_reply(None))
                await writer.drain()
                return
            # No await between checking and taking ownership.
            self.imported = True
            try:
                writer.write(W.pack_import_reply(self.device.usbip_device_info(busid=self.busid)))
                await writer.drain()
                await self._urb_phase(reader, writer)
            finally:
                # A dropped session must release held triggers and rumble.
                self.backend.write_output_report(release_report())
                self.backend.set_alt_setting(1, 0)
                self.backend.set_alt_setting(2, 0)
                # Give the physical writer a bounded chance to transmit release
                # before shutdown or another importer acquires the controller.
                await asyncio.sleep(0.05)
                # Reset device configuration, URB pacing and UAC state between hosts.
                from ds5emu.device import DualSenseDevice

                self.device = DualSenseDevice(self.backend)
                self.imported = False

    async def _urb_phase(self, reader, writer) -> None:
        pending: dict[int, asyncio.Task] = {}
        send_lock = asyncio.Lock()

        async def send(data):
            async with send_lock:
                writer.write(data)
                await writer.drain()

        try:
            while True:
                # USB devices can legitimately idle; use TCP keepalive for link
                # failure rather than timing out normal USB inactivity.
                header = await reader.readexactly(W.HEADER_SIZE)
                command, request = W.unpack_header(header)
                if command == W.CMD_SUBMIT:
                    size = request.payload_size()
                    if size > 4 * 1024 * 1024 or request.transfer_buffer_length > 4 * 1024 * 1024:
                        raise ValueError("USB/IP transfer exceeds the bridge limit")
                    if request.seqnum in pending or len(pending) >= 512:
                        raise ValueError("Duplicate or excessive pending USB/IP requests")
                    payload = await asyncio.wait_for(reader.readexactly(size), 5) if size else b""
                    pending[request.seqnum] = asyncio.create_task(
                        self._submit(request, payload, send, pending)
                    )
                elif command == W.CMD_UNLINK:
                    victim = pending.get(request.unlink_seqnum)
                    status = 0
                    if victim is not None and not victim.done():
                        victim.cancel()
                        await asyncio.gather(victim, return_exceptions=True)
                        status = -W.ECONNRESET
                    await send(
                        W.pack_ret_unlink(
                            seqnum=request.seqnum,
                            devid=request.devid,
                            direction=request.direction,
                            ep=request.ep,
                            status=status,
                        )
                    )
                else:
                    raise ValueError(f"Unexpected USB/IP command {command}")
        finally:
            tasks = list(pending.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
        tasks = list(self.handlers)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._server:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._server.wait_closed(), 2)
            self._server = None
        await asyncio.to_thread(self.backend.stop)


def release_report() -> bytes:
    from ds5bridge.protocol import AT_OFF, SetState, build_usb_setstate

    state = SetState().rumble(0, 0).trigger_left(AT_OFF).trigger_right(AT_OFF)
    return build_usb_setstate(bytes(state.body))


class HostTunnel:
    """The Windows USB/IP driver connects locally; only TLS crosses the LAN."""

    def __init__(self, remote: str, remote_port: int, context: ssl.SSLContext, *, port: int = 0):
        self.remote, self.remote_port, self.context = remote, remote_port, context
        self.port = port
        self.server: asyncio.Server | None = None
        self.handlers: set[asyncio.Task] = set()
        self.last_error: str | None = None

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, local_reader, local_writer) -> None:
        task = asyncio.current_task()
        self.handlers.add(task)
        remote_writer = None
        pumps = []
        try:
            # Defensive even though the listener itself is loopback-only.
            if not ipaddress.ip_address(local_writer.get_extra_info("peername")[0]).is_loopback:
                return
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.remote,
                    self.remote_port,
                    ssl=self.context,
                    server_hostname=SERVER_NAME,
                    ssl_handshake_timeout=5,
                    ssl_shutdown_timeout=1,
                ),
                7,
            )
            low_latency(local_writer)
            low_latency(remote_writer)

            async def pump(reader, writer):
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()

            pumps = [
                asyncio.create_task(pump(local_reader, remote_writer)),
                asyncio.create_task(pump(remote_reader, local_writer)),
            ]
            done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                completed.result()
        except (OSError, TimeoutError) as exc:
            self.last_error = str(exc)
            log.warning("Controller tunnel closed: %s", exc)
        finally:
            for pending in pumps:
                pending.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            if remote_writer:
                await close_writer(remote_writer)
            await close_writer(local_writer)
            self.handlers.discard(task)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
        tasks = list(self.handlers)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.server:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.server.wait_closed(), 2)
            self.server = None
