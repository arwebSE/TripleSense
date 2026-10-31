"""Root-only integration against the actual Linux kernel, with synthetic audio.

No physical controller or microphone is opened. Requires vhci_hcd and alsa-utils.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import select
import stat
import struct
import sys
import tempfile
from pathlib import Path

from ds5emu.backend import SyntheticBackend
from ds5emu.server import UsbIpServer

ROOT = Path(__file__).resolve().parents[1]


class MovingSyntheticBackend(SyntheticBackend):
    def read_input_report(self, max_len):
        report = super().read_input_report(max_len)
        if report:
            report = bytearray(report)
            report[1] = 27 + self._counter % 200
            return bytes(report)
        return report


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


async def main(*, hid_only=False):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("This integration test requires Linux administrator access")
    backend = MovingSyntheticBackend()
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
        raw = None
        for _ in range(100):
            raw = next(device.glob("**/hidraw/hidraw*/dev"), None)
            if raw is None:
                raw = next(device.glob("**/input/input*/event*/dev"), None)
            if raw:
                break
            await asyncio.sleep(0.1)
        if raw is None:
            raise RuntimeError("Linux did not publish the controller HID interface")
        # Containers may not see newly-created devtmpfs nodes. Create a private
        # node for exactly the device just discovered through our sysfs tree.
        major, minor = map(int, raw.read_text().strip().split(":"))
        with tempfile.TemporaryDirectory(prefix="triplesense-hid-") as temporary:
            node = Path(temporary) / "controller"
            os.mknod(node, stat.S_IFCHR | 0o600, os.makedev(major, minor))
            fd = await asyncio.to_thread(os.open, node, os.O_RDONLY | os.O_NONBLOCK)
            try:
                ready = await asyncio.to_thread(select.select, [fd], [], [], 3)
                if not ready[0]:
                    raise RuntimeError("No gamepad input arrived through the Linux kernel")
                is_hidraw = "hidraw" in str(raw)
                hid = os.read(fd, 64 if is_hidraw else 4096)
                if is_hidraw:
                    if len(hid) != 64 or hid[0] != 1:
                        raise RuntimeError("Unexpected virtual DualSense input report")
                elif not any(event[2] == 3 for event in struct.iter_unpack("@llHHi", hid)):
                    raise RuntimeError("Linux did not deliver the synthetic gamepad axes")
            finally:
                # evdev close may synchronously unlink its USB URB. Keep the
                # USB/IP event loop alive to answer that kernel request.
                await asyncio.to_thread(os.close, fd)
        if hid_only:
            print(
                json.dumps(
                    {
                        "virtual_usb_port": attached["port"],
                        "input_bytes": len(hid),
                        "input_interface": "hidraw" if is_hidraw else "evdev",
                        "audio_tested": False,
                        "synthetic_only": True,
                    }
                )
            )
            return
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hid-only",
        action="store_true",
        help="Explicitly limit verification on kernels without ALSA USB audio",
    )
    asyncio.run(main(hid_only=parser.parse_args().hid_only))
