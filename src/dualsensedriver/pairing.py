"""Short-lived PIN pairing; PAKE protects the PIN and the credential exchange.

The game PC receives the server identity; the controller PC receives only the
client identity. These TLS roles describe the network connection, not which PC
has the physical controller. No system trust store or Moonlight keys are used.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import struct
import tempfile
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from spake2 import SPAKE2_A, SPAKE2_B

from .credentials import generate_pair, tls_context
from .transport import close_writer

PAIR_PORT = 3251
STREAM_PORT = 3250
CONTEXT = b"DSShine pairing v1"
IDENTITIES = {"idA": b"DSShine controller", "idB": b"DSShine game PC"}


async def read_frame(reader, limit=65536, *, timeout=10):
    header = await asyncio.wait_for(reader.readexactly(4), timeout)
    (size,) = struct.unpack("!I", header)
    if not 0 < size <= limit:
        raise ValueError("Invalid pairing message length")
    return await asyncio.wait_for(reader.readexactly(size), timeout)


async def send_frame(writer, message):
    if not 0 < len(message) <= 65536:
        raise ValueError("Invalid pairing message length")
    writer.write(struct.pack("!I", len(message)) + message)
    await asyncio.wait_for(writer.drain(), 5)


def seal(key, payload, transcript, purpose):
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, payload, CONTEXT + transcript + purpose)


def unseal(key, message, transcript, purpose):
    return AESGCM(key).decrypt(message[:12], message[12:], CONTEXT + transcript + purpose)


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


class PairingOffer:
    """One PIN, one paired controller, two minutes, at most five attempts."""

    def __init__(
        self,
        root,
        on_paired,
        *,
        host="0.0.0.0",
        port=PAIR_PORT,
        stream_port=STREAM_PORT,
        host_id="",
    ):
        self.root = Path(root)
        self.on_paired = on_paired
        self.host, self.port, self.stream_port = host, port, stream_port
        self.host_id = host_id
        self.code = f"{secrets.randbelow(10_000):04d}"
        self.expires = time.monotonic() + 120
        self.attempts = 0
        self.busy = False
        self.completed = False
        self.server = None
        self.handlers = set()
        self.staging = None

    async def start(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.staging = tempfile.TemporaryDirectory(prefix="pairing-", dir=self.root)
        self.pair = Path(self.staging.name) / "pair"
        await asyncio.to_thread(generate_pair, self.pair)
        try:
            self.server = await asyncio.start_server(self._handle, self.host, self.port)
            self.port = self.server.sockets[0].getsockname()[1]
        except BaseException:
            self.staging.cleanup()
            raise

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        acquired = False
        try:
            if self.busy or self.completed or self.attempts >= 5 or time.monotonic() > self.expires:
                return
            self.busy = acquired = True
            self.attempts += 1
            message_a = await read_frame(reader, 256)
            exchange = SPAKE2_B(self.code.encode("ascii"), **IDENTITIES)
            message_b = await asyncio.to_thread(exchange.start)
            await send_frame(writer, message_b)
            key = await asyncio.to_thread(exchange.finish, message_a)
            transcript = message_a + message_b
            payload = json.dumps(
                {
                    "version": 1,
                    "name": socket.gethostname()[:64],
                    "host_id": self.host_id,
                    "port": self.stream_port,
                    "credentials": {
                        name: (self.pair / "host" / name).read_text("ascii")
                        for name in ("ca.pem", "cert.pem", "key.pem")
                    },
                }
            ).encode()
            await send_frame(writer, seal(key, payload, transcript, b"credentials"))
            confirmation = unseal(key, await read_frame(reader), transcript, b"controller-confirm")
            peer = json.loads(confirmation)
            if peer.get("accepted") is not True or not isinstance(peer.get("name"), str):
                raise ValueError("Invalid pairing confirmation")
            destination = self.root / ("game-" + uuid.uuid4().hex)
            destination.mkdir(mode=0o700)
            (self.pair / "source").rename(destination / "credentials")
            try:
                await self.on_paired(destination / "credentials", peer["name"][:64])
            except BaseException:
                # Keep the identity for diagnosis; never overwrite an existing pair.
                raise
            self.completed = True
            await send_frame(writer, seal(key, b"paired", transcript, b"game-confirm"))
        except Exception:
            # Wrong codes, malformed points, disconnects and failed confirmation
            # all consume an attempt. Never log the PIN, key or credential body.
            pass
        finally:
            if acquired:
                self.busy = False
            await close_writer(writer)
            self.handlers.discard(task)

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        tasks = list(self.handlers)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.staging:
            self.staging.cleanup()
            self.staging = None


async def pair_controller(address, code, root, *, port=PAIR_PORT):
    code = code.replace(" ", "").replace("-", "")
    if len(code) != 4 or not code.isascii() or not code.isdigit():
        raise ValueError("Enter the four-digit code shown on the game PC")
    exchange = SPAKE2_A(code.encode("ascii"), **IDENTITIES)
    message_a = await asyncio.to_thread(exchange.start)
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port), 5)
    except TimeoutError as exc:
        raise TimeoutError(
            "Server connection timed out. Check the address, VPN connection and server firewall."
        ) from exc
    try:
        await send_frame(writer, message_a)
        message_b = await read_frame(reader, 256)
        key = await asyncio.to_thread(exchange.finish, message_b)
        transcript = message_a + message_b
        payload = json.loads(unseal(key, await read_frame(reader), transcript, b"credentials"))
        credentials = payload.get("credentials", {})
        if payload.get("version") != 1 or set(credentials) != {"ca.pem", "cert.pem", "key.pem"}:
            raise ValueError("Invalid pairing identity")
        stream_port = payload.get("port")
        if type(stream_port) is not int or not 1 <= stream_port <= 65535:
            raise ValueError("Invalid controller connection port")
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="pairing-", dir=root) as temporary:
            folder = Path(temporary) / "credentials"
            folder.mkdir(mode=0o700)
            for name, value in credentials.items():
                if not isinstance(value, str) or len(value) > 16384:
                    raise ValueError("Invalid pairing credential")
                private_write(folder / name, value.encode("ascii"))
            tls_context(folder, server=False)  # Verify PEMs and matching client key before saving.
            await send_frame(
                writer,
                seal(
                    key,
                    json.dumps(
                        {
                            "accepted": True,
                            "name": socket.gethostname()[:64],
                        }
                    ).encode(),
                    transcript,
                    b"controller-confirm",
                ),
            )
            if unseal(key, await read_frame(reader), transcript, b"game-confirm") != b"paired":
                raise ValueError("Game PC did not confirm pairing")
            destination = root / ("controller-" + uuid.uuid4().hex)
            folder.rename(destination)
        return {
            "address": address,
            "port": stream_port,
            "credentials": str(destination),
            "name": str(payload.get("name", "Game PC"))[:64],
            "host_id": str(payload.get("host_id", ""))[:64],
        }
    except TimeoutError as exc:
        raise TimeoutError("Pairing timed out. Generate a new Server code and try again.") from exc
    except OSError:
        raise
    except Exception as exc:
        raise ValueError(
            "Pairing failed. Check the code and try a new code on the game PC."
        ) from exc
    finally:
        await close_writer(writer)
