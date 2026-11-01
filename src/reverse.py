"""Controller-initiated TLS: only the game PC needs a listening LAN port."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import socket
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .credentials import SERVER_NAME, tls_context
from .latency import controller_activity
from .pairing import STREAM_PORT, read_frame, send_frame
from .runtime import attached_port, detach_owned, run_usbip, write_json
from .transport import SecureSource, close_writer, low_latency


@dataclass(eq=False)
class Offer:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    done: asyncio.Event = field(default_factory=asyncio.Event)
    claimed: bool = False


class GameReceiver:
    def __init__(
        self,
        credentials,
        notify,
        *,
        usbip=None,
        port=STREAM_PORT,
        bind="0.0.0.0",
        ownership_file=None,
        attachment=None,
        touchpad_mouse=False,
    ):
        self.credentials = Path(credentials)
        self.notify, self.usbip, self.port, self.bind = notify, usbip, port, bind
        self.server = self.local_server = None
        self.local_port = 0
        self.handlers = set()
        self.local_handlers = set()
        self.offers = deque()
        self.available = asyncio.Condition()
        self.closing = False
        self.worker = None
        self.owned_port = None
        self.serial = "TRSA" + uuid.uuid4().hex[:11]
        self.last_error = None
        self.ownership_file = ownership_file
        self.attachment = attachment
        self.touchpad_mouse = touchpad_mouse
        self.mouse_output = None

    async def start(self):
        context = tls_context(self.credentials, server=True)
        if self.usbip and self.ownership_file and self.ownership_file.exists():
            state = json.loads(self.ownership_file.read_text("utf-8"))
            if (
                type(state.get("port")) is not int
                or not 1 <= state["port"] <= 65535
                or type(state.get("tcp_port")) is not int
                or not 1 <= state["tcp_port"] <= 65535
                or not re.fullmatch(r"TRSA[0-9a-f]{11}", str(state.get("serial", "")))
            ):
                raise RuntimeError("Could not verify the previous controller session ownership")
            await detach_owned(self.usbip, state["port"], state["tcp_port"], state["serial"])
            self.ownership_file.unlink()
        self.local_server = await asyncio.start_server(self._local, "127.0.0.1", 0)
        self.local_port = self.local_server.sockets[0].getsockname()[1]
        try:
            if self.touchpad_mouse:
                from .mouse_output import create_mouse

                self.mouse_output = create_mouse()
            self.server = await asyncio.start_server(
                self._incoming,
                self.bind,
                self.port,
                ssl=context,
                ssl_handshake_timeout=5,
                ssl_shutdown_timeout=1,
            )
            self.port = self.server.sockets[0].getsockname()[1]
            if self.usbip or self.attachment:
                self.worker = asyncio.create_task(self._attach_worker())
        except BaseException:
            await self.stop()
            raise

    async def _incoming(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        offer = None
        try:
            if self.closing or len(self.handlers) > 4:
                return
            hello = json.loads(await read_frame(reader, 1024))
            if hello.get("protocol") != 1 or hello.get("kind") != "controller":
                return
            low_latency(writer)
            offer = Offer(reader, writer)
            async with self.available:
                self.offers.append(offer)
                self.available.notify_all()
            await send_frame(writer, b"ready")
            if self.owned_port is None:
                self.notify("available", str(hello.get("name", "Controller PC"))[:64])
            while not offer.done.is_set() and not self.closing:
                if not offer.claimed and reader.at_eof():
                    break
                await asyncio.sleep(0.1)
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            if offer:
                with contextlib.suppress(ValueError):
                    self.offers.remove(offer)
                offer.done.set()
            await close_writer(writer)
            self.handlers.discard(task)

    async def _take(self):
        async with self.available:
            while not self.closing:
                while self.offers:
                    offer = self.offers.popleft()
                    if not offer.done.is_set() and not offer.reader.at_eof():
                        offer.claimed = True
                        return offer
                await self.available.wait()
        raise ConnectionError("Receiver stopped")

    async def _local(self, reader, writer):
        task = asyncio.current_task()
        self.local_handlers.add(task)
        offer = None
        pumps = []
        try:
            offer = await asyncio.wait_for(self._take(), 8)
            await send_frame(offer.writer, b"open")
            low_latency(writer)

            async def pump(source, target):
                while data := await source.read(65536):
                    target.write(data)
                    await target.drain()

            if self.touchpad_mouse:
                from .mouse_proxy import forward_responses
                from .touchpad_mouse import TouchpadMouse

                downstream = forward_responses(
                    offer.reader,
                    writer,
                    lambda: TouchpadMouse(self.mouse_output, close_output=False),
                )
            else:
                downstream = pump(offer.reader, writer)
            pumps = [
                asyncio.create_task(pump(reader, offer.writer)),
                asyncio.create_task(downstream),
            ]
            done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for item in done:
                item.result()
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError) as exc:
            self.last_error = str(exc)
        finally:
            for item in pumps:
                item.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            if offer:
                offer.done.set()
            await close_writer(writer)
            self.local_handlers.discard(task)

    async def _attach_worker(self):
        try:
            while not self.closing:
                async with self.available:
                    await self.available.wait_for(lambda: self.offers or self.closing)
                if self.closing:
                    break
                try:
                    await self._attach_once()
                    self.notify("connected", "DualSense is ready for games")
                    while self.local_handlers and not self.closing:
                        await asyncio.sleep(0.25)
                except (OSError, RuntimeError, TimeoutError) as exc:
                    self.last_error = str(exc)
                    self.notify("error", str(exc))
                finally:
                    if self.owned_port is not None:
                        await self._detach()
                        self.owned_port = None
                        if self.ownership_file:
                            self.ownership_file.unlink(missing_ok=True)
                if not self.closing:
                    self.notify("waiting", "Waiting for the controller computer")
                    await asyncio.sleep(2)
        finally:
            if self.owned_port is not None:
                await self._detach()
                self.owned_port = None
                if self.ownership_file:
                    self.ownership_file.unlink(missing_ok=True)

    async def _attach_once(self):
        if self.attachment is not None:
            # Cancellation closes the helper's stdin, which shuts down only
            # its owned kernel socket; Linux uses no global detach command.
            self.owned_port = await self.attachment.start(self.local_port)
            return
        command = asyncio.create_task(
            run_usbip(
                self.usbip,
                "--tcp-port",
                str(self.local_port),
                "attach",
                "--remote",
                "127.0.0.1",
                "--bus-id",
                "1-1",
                "--terse",
                "--once",
                "--serial",
                self.serial,
            )
        )
        cancelled = None
        try:
            output = await asyncio.shield(command)
        except asyncio.CancelledError as exc:
            # Finish the bounded native command so Quit cannot lose a newly
            # attached port between driver completion and ownership recording.
            cancelled = exc
            output = await command
        self.owned_port = attached_port(output)
        if self.ownership_file:
            write_json(
                self.ownership_file,
                {
                    "port": self.owned_port,
                    "tcp_port": self.local_port,
                    "serial": self.serial,
                },
            )
        if cancelled:
            raise cancelled

    async def _detach(self):
        if self.attachment is not None:
            await self.attachment.stop()
        else:
            await detach_owned(self.usbip, self.owned_port, self.local_port, self.serial)

    async def stop(self):
        self.closing = True
        for server in (self.server, self.local_server):
            if server:
                server.close()
        async with self.available:
            self.available.notify_all()
        error = None
        if self.worker:
            self.worker.cancel()
            result = await asyncio.gather(self.worker, return_exceptions=True)
            if isinstance(result[0], Exception):
                error = result[0]
        tasks = list(self.local_handlers | self.handlers)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for server in (self.server, self.local_server):
            if server:
                await server.wait_closed()
        self.offers.clear()
        if self.mouse_output is not None:
            self.mouse_output.close()
            self.mouse_output = None
        if self.owned_port is not None:
            await self._detach()
            self.owned_port = None
            if self.ownership_file:
                self.ownership_file.unlink(missing_ok=True)
            error = None
        if error:
            raise error


class ControllerConnection:
    """Serve the existing USB model over authenticated outgoing connections."""

    def __init__(self, profile, backend, notify):
        self.profile, self.backend, self.notify = profile, backend, notify
        self.source = SecureSource(backend, None)
        self.context = tls_context(Path(profile["credentials"]), server=False)
        self.tasks = []
        self.closing = False
        self.writers = set()
        self.activity = None

    async def start(self):
        self.activity = controller_activity()
        self.activity.__enter__()
        try:
            await asyncio.to_thread(self.backend.start)
        except BaseException:
            try:
                await asyncio.to_thread(self.backend.stop)
            finally:
                self.activity.__exit__(None, None, None)
                self.activity = None
            raise
        self.tasks = [asyncio.create_task(self._offer()) for _ in range(2)]
        self.tasks.append(asyncio.create_task(self._watch_status()))

    async def _watch_status(self):
        previous = None
        audio_sample = None
        audio_at = 0
        while not self.closing:
            device = getattr(self.backend, "connected", None)
            if device is not None:
                current = (device.is_set(), self.source.imported, bool(self.writers))
                if current != previous:
                    previous = current
                    if not current[0]:
                        self.notify("controller_waiting", "Turn on your Bluetooth DualSense")
                    elif current[1]:
                        self.notify("connected", "DualSense is ready on your game PC")
                    elif current[2]:
                        self.notify(
                            "available", "Connected to " + self.profile.get("name", "Game PC")
                        )
            if getattr(self.backend, "audio_enabled", False):
                now = asyncio.get_running_loop().time()
                if now - audio_at >= 3:
                    stats = self.backend.stats.copy()
                    message = "Controller audio enabled · waiting for game audio"
                    if audio_sample and stats["audio_out_bytes"] > audio_sample["audio_out_bytes"]:
                        rate = (stats["reports_39"] - audio_sample["reports_39"]) / (now - audio_at)
                        message = (
                            "Controller audio is stalling on this Bluetooth link"
                            if rate < 40
                            else "Controller audio is streaming · listening check still needed"
                        )
                    self.notify("audio_status", message)
                    audio_sample, audio_at = stats, now
            await asyncio.sleep(0.5)

    async def _offer(self):
        while not self.closing:
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self.profile["address"],
                        self.profile["port"],
                        ssl=self.context,
                        server_hostname=SERVER_NAME,
                        ssl_handshake_timeout=5,
                        ssl_shutdown_timeout=1,
                    ),
                    8,
                )
                self.writers.add(writer)
                low_latency(writer)
                await send_frame(
                    writer,
                    json.dumps(
                        {
                            "protocol": 1,
                            "kind": "controller",
                            "name": socket.gethostname()[:64],
                        }
                    ).encode(),
                )
                if await read_frame(reader, 64) != b"ready":
                    raise ValueError("Unexpected receiver reply")
                if not self.source.imported:
                    self.notify("available", "Connected to " + self.profile.get("name", "Game PC"))
                if await read_frame(reader, 64, timeout=None) != b"open":
                    raise ValueError("Unexpected USB connection request")
                await self.source._tracked_client(reader, writer)
            except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError) as exc:
                if not self.closing and not self.source.imported:
                    self.notify("reconnecting", str(exc).strip() or "Server connection timed out")
            finally:
                if writer:
                    self.writers.discard(writer)
                    await close_writer(writer)
            if not self.closing:
                await asyncio.sleep(2)

    async def stop(self):
        self.closing = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            await self.source.stop()
        finally:
            if self.activity:
                self.activity.__exit__(None, None, None)
                self.activity = None
