"""Use Linux's existing USB/IP host controller through a narrow privileged helper."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


def helper_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("triplesense-vhci")
    return Path(__file__).resolve().parents[1] / "packaging/linux/triplesense-vhci"


class LinuxAttachment:
    """The helper owns one loopback socket, never an arbitrary USB/IP port."""

    def __init__(self):
        self.process = None

    async def start(self, tcp_port):
        helper = helper_path()
        if not helper.is_file():
            raise RuntimeError("Install the TripleSense Linux package to enable Server mode.")
        command = [str(helper), "--tcp-port", str(tcp_port)]
        if os.geteuid() != 0:
            command.insert(0, "pkexec")
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), 60)
            if not line:
                detail = (await self.process.stderr.read(4096)).decode(errors="replace").strip()
                raise RuntimeError(detail or "Linux controller setup was cancelled.")
            value = json.loads(line)
            if type(value.get("port")) is not int or not 0 <= value["port"] <= 255:
                raise RuntimeError("Invalid response from the Linux controller helper.")
            return value["port"]
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        # Closing stdin requests cleanup, including when pkexec runs as root and
        # the ordinary desktop user cannot send the helper a process signal.
        if process.stdin:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 8)
        except TimeoutError as exc:
            raise RuntimeError("The Linux controller helper did not finish cleanup.") from exc
        if process.returncode:
            detail = (await process.stderr.read(4096)).decode(errors="replace").strip()
            raise RuntimeError(detail or "Linux controller cleanup failed.")
