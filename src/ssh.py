"""Owned OpenSSH forwarding for a source that stays bound to Mac loopback."""

from __future__ import annotations

import asyncio
import os
import re
import socket
from contextlib import suppress
from pathlib import Path


class SshForward:
    def __init__(self, target: str, remote_port: int, *, identity=None, known_hosts=None):
        if not re.fullmatch(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*", target):
            raise ValueError("SSH target must be user@hostname or user@IPv4-address")
        self.target, self.remote_port = target, remote_port
        self.identity, self.known_hosts = identity, known_hosts
        self.process = None
        self.reader = None
        self.error = b""
        self.port = 0

    async def start(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        command = [
            "ssh",
            "-N",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ConnectTimeout=7",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=2",
            "-L",
            f"127.0.0.1:{self.port}:127.0.0.1:{self.remote_port}",
        ]
        if self.identity:
            command.extend(["-i", str(self.identity), "-o", "IdentitiesOnly=yes"])
        if self.known_hosts:
            path = Path(self.known_hosts).as_posix().replace('"', '\\"')
            command.extend(["-o", f'UserKnownHostsFile="{path}"'])
        command.append(self.target)
        options = {"creationflags": 0x08000000} if os.name == "nt" else {}
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            **options,
        )

        async def drain():
            while data := await self.process.stderr.read(1024):
                self.error = (self.error + data)[-4096:]

        self.reader = asyncio.create_task(drain())
        try:
            deadline = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < deadline:
                if self.process.returncode is not None:
                    await self.reader
                    raise RuntimeError(
                        f"SSH forwarding failed: {self.error.decode(errors='replace')}"
                    )
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", self.port)
                except OSError:
                    await asyncio.sleep(0.1)
                    continue
                writer.close()
                await writer.wait_closed()
                return
            raise TimeoutError("SSH did not open its local forwarding port within 10s")
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        if self.process and self.process.returncode is None:
            with suppress(ProcessLookupError):
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    self.process.kill()
                await self.process.wait()
        if self.reader:
            await self.reader
