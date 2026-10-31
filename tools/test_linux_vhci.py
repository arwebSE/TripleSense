"""Root-only integration against the actual Linux kernel, with synthetic audio.

No physical controller or microphone is opened. Requires vhci_hcd and alsa-utils.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from ds5emu.backend import SyntheticBackend
from ds5emu.server import UsbIpServer

ROOT = Path(__file__).resolve().parents[1]


async def wait_device():
    for _ in range(100):
        for device in Path("/sys/bus/usb/devices").glob("*"):
            try:
                if (
                    (device / "idVendor").read_text().strip(),
                    (device / "idProduct").read_text().strip(),
                ) == ("054c", "0ce6"):
                    return device.resolve()
            except OSError:
                pass
        await asyncio.sleep(0.1)
    raise RuntimeError("Linux did not enumerate the virtual DualSense")


async def main():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("This integration test requires Linux administrator access")
    backend = SyntheticBackend()
    server = UsbIpServer(backend, host="127.0.0.1", port=0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "packaging/linux/triplesense-vhci"),
            "--tcp-port",
            str(port),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        line = await asyncio.wait_for(process.stdout.readline(), 20)
        if not line:
            raise RuntimeError((await process.stderr.read()).decode())
        attached = json.loads(line)
        device = await wait_device()
        card = None
        for _ in range(100):
            card = next(
                (
                    item
                    for item in Path("/sys/class/sound").glob("card[0-9]*")
                    if item.resolve().is_relative_to(device)
                ),
                None,
            )
            if card:
                break
            await asyncio.sleep(0.1)
        if card is None:
            raise RuntimeError("ALSA did not create the virtual DualSense audio card")
        card_id = card.name[4:]
        capture = await asyncio.create_subprocess_exec(
            "arecord",
            "-q",
            "-D",
            f"hw:{card_id},0",
            "-f",
            "S16_LE",
            "-c",
            "2",
            "-r",
            "48000",
            "-d",
            "1",
            "-t",
            "raw",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pcm, errors = await asyncio.wait_for(capture.communicate(), 15)
        if capture.returncode or not any(pcm):
            raise RuntimeError("Synthetic microphone capture failed: " + errors.decode())
        playback = await asyncio.create_subprocess_exec(
            "aplay",
            "-q",
            "-D",
            f"hw:{card_id},0",
            "-f",
            "S16_LE",
            "-c",
            "4",
            "-r",
            "48000",
            "-t",
            "raw",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, errors = await asyncio.wait_for(playback.communicate(bytes(48000 * 4 * 2)), 15)
        if playback.returncode or backend.audio_out_bytes == 0:
            raise RuntimeError("Synthetic speaker output failed: " + errors.decode())
        print(
            json.dumps(
                {
                    "virtual_usb_port": attached["port"],
                    "audio_card": card.name,
                    "capture_bytes": len(pcm),
                    "playback_bytes": backend.audio_out_bytes,
                    "synthetic_only": True,
                }
            )
        )
    finally:
        if process:
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 10)
            if process.returncode:
                raise RuntimeError((await process.stderr.read()).decode())
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
