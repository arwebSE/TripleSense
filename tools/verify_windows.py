"""Verify Windows USB/HID/audio enumeration, then detach only the owned USB port."""

import argparse
import asyncio
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hid  # noqa: E402
from ds5bridge import protocol as P  # noqa: E402
from ds5emu.bridge import BridgeBackend  # noqa: E402

from dualsensedriver.credentials import generate_pair, tls_context  # noqa: E402
from dualsensedriver.diagnostics import choose_controller, find_usbip  # noqa: E402
from dualsensedriver.runtime import attached_port, detach_owned, run_role, run_usbip  # noqa: E402
from dualsensedriver.transport import (  # noqa: E402
    HostTunnel,
    SecureSource,
    release_report,  # noqa: E402
)


async def pnp_snapshot():
    process = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "@(Get-PnpDevice -PresentOnly | Select-Object Class,FriendlyName,InstanceId,Status) "
        "| ConvertTo-Json -Compress",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=0x08000000,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace"))
    return json.loads(stdout.decode("utf-8-sig"))


async def verify(*, effects=False, audio=False):
    usbip = find_usbip()
    if not usbip:
        raise RuntimeError("Install usbip-win2 before this Windows enumeration test.")
    before_hid = {d["path"] for d in hid.enumerate(0x054C, 0x0CE6)}
    before_pnp = {d["InstanceId"] for d in await pnp_snapshot()}
    with tempfile.TemporaryDirectory() as tmp:
        pair = Path(tmp) / "pair"
        generate_pair(pair)
        selected = choose_controller(None)
        backend = BridgeBackend(serial=selected.serial, mic_mode="pad")
        source = SecureSource(backend, tls_context(pair / "source", server=True), port=0)
        tunnel, owned_port, controller = None, None, None
        serial = "DS5T" + uuid.uuid4().hex[:11]
        try:
            await source.start()
            tunnel = HostTunnel("127.0.0.1", source.port, tls_context(pair / "host", server=False))
            await tunnel.start()
            owned_port = attached_port(
                await run_usbip(
                    usbip,
                    "--tcp-port",
                    str(tunnel.port),
                    "attach",
                    "--remote",
                    "127.0.0.1",
                    "--bus-id",
                    "1-1",
                    "--terse",
                    "--once",
                    "--serial",
                    serial,
                )
            )
            deadline = time.monotonic() + 10
            virtual = []
            while time.monotonic() < deadline:
                enumerated = await asyncio.to_thread(hid.enumerate, 0x054C, 0x0CE6)
                virtual = [d for d in enumerated if d["path"] not in before_hid]
                if virtual:
                    break
                await asyncio.sleep(0.1)
            if len(virtual) != 1:
                raise RuntimeError(f"Expected one new DualSense HID device, found {len(virtual)}")
            controller = hid.device()
            await asyncio.to_thread(controller.open_path, virtual[0]["path"])
            reports = []
            for _ in range(100):
                report = bytes(await asyncio.to_thread(controller.read, 64, 1000))
                if len(report) != 64 or report[0] != 1:
                    raise RuntimeError(f"Unexpected Windows HID input shape: {report.hex()}")
                reports.append(report)
            new_pnp = [d for d in await pnp_snapshot() if d["InstanceId"] not in before_pnp]
            audio_endpoints = [d for d in new_pnp if d["Class"] == "AudioEndpoint"]
            if len(audio_endpoints) < 2:
                raise RuntimeError(
                    f"Expected render and capture audio endpoints, found {audio_endpoints}"
                )
            result = {
                "windows_driver_attached": True,
                "owned_usb_port": owned_port,
                "windows_hid_reports": len(reports),
                "new_pnp_devices": new_pnp,
                "audio_endpoint_count": len(audio_endpoints),
                "game_trigger_and_haptic_quality_tested": False,
            }
            if effects:

                async def trigger_status():
                    latest = None
                    deadline = time.monotonic() + 0.6
                    while time.monotonic() < deadline:
                        latest = bytes(await asyncio.to_thread(controller.read, 64, 100))
                    if not latest or len(latest) != 64:
                        raise RuntimeError("Trigger test lost controller input")
                    return latest[1 + P.OFFSETS_USB.at_status2]

                try:
                    # Ten trigger zones at the lowest feedback strength.
                    feedback = P.SetState().trigger_left(P.AT_FEEDBACK, b"\xff\x03")
                    feedback.trigger_right(P.AT_FEEDBACK, b"\xff\x03")
                    await asyncio.to_thread(
                        controller.write, P.build_usb_setstate(bytes(feedback.body))
                    )
                    active = await trigger_status()
                    if active != 0x11:
                        raise RuntimeError(
                            f"Physical trigger mode readback was {active:#x}, wanted 0x11"
                        )
                finally:
                    await asyncio.to_thread(controller.write, release_report())
                off = await trigger_status()
                if off != 0:
                    raise RuntimeError(f"Trigger release readback was {off:#x}, wanted zero")
                result["physical_trigger_mode_feedback_then_off"] = [active, off]
            if audio:

                def play_silence():
                    import numpy as np
                    import sounddevice as sd

                    expected_names = {d["FriendlyName"] for d in audio_endpoints}
                    candidates = [
                        index
                        for index, device in enumerate(sd.query_devices())
                        if device["name"] in expected_names
                        and device["max_output_channels"] >= 4
                        and sd.query_hostapis(device["hostapi"])["name"] == "Windows WASAPI"
                    ]
                    if len(candidates) != 1:
                        raise RuntimeError(
                            f"Expected one new 4-channel WASAPI render device: {candidates}"
                        )
                    # No tone or vibration: validate the class-driver PCM path first.
                    pcm = np.zeros((24000, 4), dtype=np.int16)
                    sd.play(pcm, samplerate=48000, device=candidates[0], blocking=True)

                before_bytes = backend.stats["audio_out_bytes"]
                await asyncio.to_thread(play_silence)
                delivered = backend.stats["audio_out_bytes"] - before_bytes
                if delivered <= 0:
                    raise RuntimeError("Windows playback delivered no PCM to the Bluetooth bridge")
                result["windows_four_channel_silent_pcm_bytes"] = delivered
            await asyncio.to_thread(controller.close)
            controller = None
        finally:
            if controller:
                await asyncio.to_thread(controller.close)
            try:
                if owned_port:
                    await detach_owned(usbip, owned_port, tunnel.port, serial)
            finally:
                if tunnel:
                    await tunnel.stop()
                await source.stop()
        for _ in range(50):
            enumerated = await asyncio.to_thread(hid.enumerate, 0x054C, 0x0CE6)
            remaining = [d for d in enumerated if d["path"] not in before_hid]
            if not remaining:
                break
            await asyncio.sleep(0.1)
        if remaining:
            raise RuntimeError("Virtual HID remained after explicit port detach")
        result["owned_device_detached"] = True
        output = Path("captures/windows-enumeration.json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--effects", action="store_true", help="Brief low-strength trigger feedback test"
    )
    parser.add_argument("--audio", action="store_true", help="Silent 4-channel PCM path test")
    args = parser.parse_args()
    run_role(verify(effects=args.effects, audio=args.audio))
