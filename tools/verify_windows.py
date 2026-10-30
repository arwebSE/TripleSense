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
from dualsensedriver.diagnostics import (  # noqa: E402
    choose_controller,
    find_usbip,
    require_controller_isolation,
)
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


async def verify(
    *,
    effects=False,
    audio=False,
    microphone=False,
    speaker=False,
    source_host=None,
    source_port=3250,
    credentials=None,
    output=Path("captures/windows-enumeration.json"),
):
    if not source_host:
        require_controller_isolation()
    usbip = find_usbip()
    if not usbip:
        raise RuntimeError("Install usbip-win2 before this Windows enumeration test.")
    before_hid = {d["path"] for d in hid.enumerate(0x054C, 0x0CE6)}
    before_pnp = {d["InstanceId"] for d in await pnp_snapshot()}
    with tempfile.TemporaryDirectory() as tmp:
        backend, source = None, None
        if source_host:
            host_credentials = credentials
        else:
            pair = Path(tmp) / "pair"
            generate_pair(pair)
            selected = choose_controller(None)
            # Disable speaker echo cancellation only during the acoustic measurement.
            backend = BridgeBackend(serial=selected.serial, mic_mode="studio" if speaker else "pad")
            source = SecureSource(backend, tls_context(pair / "source", server=True), port=0)
            host_credentials = pair / "host"
        tunnel, owned_port, controller = None, None, None
        serial = "DS5T" + uuid.uuid4().hex[:11]
        try:
            if source:
                await source.start()
            tunnel = HostTunnel(
                source_host or "127.0.0.1",
                source_port if source_host else source.port,
                tls_context(host_credentials, server=False),
            )
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
                "source_host": source_host or "127.0.0.1",
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

                before_bytes = backend.stats["audio_out_bytes"] if backend else None
                await asyncio.to_thread(play_silence)
                if backend:
                    delivered = backend.stats["audio_out_bytes"] - before_bytes
                    if delivered <= 0:
                        raise RuntimeError(
                            "Windows playback delivered no PCM to the Bluetooth bridge"
                        )
                    result["windows_four_channel_silent_pcm_bytes"] = delivered
                else:
                    # Delivery must be corroborated with the remote source's counters.
                    result["windows_four_channel_silent_pcm_submitted_bytes"] = 24000 * 4 * 2
            if microphone or speaker:
                measurement = await asyncio.to_thread(
                    measure_audio, audio_endpoints, play_speaker=speaker
                )
                if backend:
                    measurement["bluetooth_mic_decode_errors"] = backend.stats["mic_decode_errors"]
                    measurement["usb_capture_bytes"] = backend.stats["audio_in_bytes"]
                    measurement["bridge_counters"] = dict(backend.stats)
                    measurement["bluetooth_clock_seam"] = backend.clock_seam()
                else:
                    measurement["remote_counters_require_separate_check"] = True
                measurement["signal_checks_passed"] = bool(
                    measurement["microphone_nonzero"]
                    and (not backend or not backend.stats["disconnects"])
                    and (not backend or not backend.stats["mic_decode_errors"])
                    and (not speaker or measurement["speaker_detected_at_physical_microphone"])
                )
                result["speaker_microphone"] = measurement
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
                if source:
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
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        if (microphone or speaker) and not result["speaker_microphone"]["signal_checks_passed"]:
            raise RuntimeError("Audio signal checks failed; see the recorded scalar measurements.")


def measure_audio(endpoints, *, play_speaker):
    """Short, in-memory capture; return levels only, never persist microphone PCM."""
    from collections import deque

    import numpy as np
    import sounddevice as sd

    names = {endpoint["FriendlyName"] for endpoint in endpoints}
    devices = [
        (index, device)
        for index, device in enumerate(sd.query_devices())
        if device["name"] in names
        and sd.query_hostapis(device["hostapi"])["name"] == "Windows WASAPI"
    ]
    inputs = [index for index, device in devices if device["max_input_channels"] >= 2]
    outputs = [index for index, device in devices if device["max_output_channels"] >= 4]
    if len(inputs) != 1 or (play_speaker and len(outputs) != 1):
        raise RuntimeError("Could not uniquely identify the virtual controller audio endpoints")
    blocks = deque(maxlen=300)
    overflows = []

    def capture(indata, frames, timing, status):
        if status.input_overflow:
            overflows.append(True)
        blocks.append(indata.copy())

    def take():
        snapshot = list(blocks)
        blocks.clear()
        if not snapshot:
            raise RuntimeError("The virtual microphone delivered no capture frames")
        return np.concatenate(snapshot).astype(np.float32).mean(axis=1) / 32768.0

    def band_power(samples):
        spectrum = np.fft.rfft(samples * np.hanning(samples.size))
        hz = np.fft.rfftfreq(samples.size, 1 / 48000)
        return float((np.abs(spectrum[(hz >= 1470) & (hz <= 1530)]) ** 2).sum() / samples.size**2)

    with sd.InputStream(
        device=inputs[0],
        channels=2,
        samplerate=48000,
        dtype="int16",
        blocksize=480,
        extra_settings=sd.WasapiSettings(exclusive=True),
        callback=capture,
    ):
        time.sleep(1.2)  # Bluetooth microphone arming / jitter-buffer priming.
        blocks.clear()
        time.sleep(1)
        baseline = take()
        if play_speaker:
            # Quiet 1.5 kHz tone in speaker channels only. Haptic channels stay zero.
            clock = np.arange(48000, dtype=np.float32) / 48000
            pcm = np.zeros((48000, 4), dtype=np.float32)
            tone = 0.08 * np.sin(2 * np.pi * 1500 * clock)
            tone[:480] *= np.linspace(0, 1, 480)
            tone[-480:] *= np.linspace(1, 0, 480)
            pcm[:, 0] = tone
            pcm[:, 1] = tone
            try:
                sd.play(pcm, samplerate=48000, device=outputs[0], blocking=False)
                time.sleep(1.5)
                driven = take()
            finally:
                sd.stop()
        else:
            driven = baseline
    rms = float(np.sqrt(np.mean(driven**2)))
    result = {
        "microphone_frames": int(driven.size),
        "microphone_rms_dbfs": round(float(20 * np.log10(max(rms, 1e-12))), 2),
        "microphone_nonzero": bool(np.any(driven)),
        "baseline_nonzero": bool(np.any(baseline)),
        "capture_overflows": len(overflows),
        "audio_recording_saved": False,
    }
    if play_speaker:
        rise = 10 * np.log10(max(band_power(driven), 1e-20) / max(band_power(baseline), 1e-20))
        result.update(
            {
                "speaker_test_hz": 1500,
                "speaker_band_rise_db": round(float(rise), 2),
                "speaker_detected_at_physical_microphone": bool(rise >= 10),
            }
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--effects", action="store_true", help="Brief low-strength trigger feedback test"
    )
    parser.add_argument("--audio", action="store_true", help="Silent 4-channel PCM path test")
    parser.add_argument(
        "--microphone", action="store_true", help="Capture briefly; save statistics only"
    )
    parser.add_argument(
        "--speaker", action="store_true", help="Play quiet tone and measure it at the mic"
    )
    parser.add_argument("--source", help="Remote source address; omit for a local physical pad")
    parser.add_argument("--port", type=int, default=3250)
    parser.add_argument("--credentials", type=Path, help="Host TLS credentials for a remote source")
    parser.add_argument("--out", type=Path, default=Path("captures/windows-enumeration.json"))
    args = parser.parse_args()
    if args.source and not args.credentials:
        parser.error("--source requires --credentials")
    run_role(
        verify(
            effects=args.effects,
            audio=args.audio,
            microphone=args.microphone,
            speaker=args.speaker,
            source_host=args.source,
            source_port=args.port,
            credentials=args.credentials,
            output=args.out,
        )
    )
