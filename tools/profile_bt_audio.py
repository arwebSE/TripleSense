"""Measure physical Bluetooth write capacity with silent audio, without USB/IP.

Run with the controller extra installed and the normal source stopped. This sends
silent speaker/haptic frames; --microphone enables mic traffic but discards every
input payload. Only timings and packet counts are retained.
"""

from __future__ import annotations

import argparse
import json
import platform
import threading
import time
from collections import Counter
from pathlib import Path

import hid
from ds5bridge import audio as A
from ds5bridge import protocol as P
from ds5bridge.device import DualSense

from dualsensedriver.diagnostics import choose_controller, require_controller_isolation
from dualsensedriver.latency import controller_activity, interactive_thread


def timed_phase(device, build, period, seconds):
    """Pace writes without an unbounded catch-up burst after a native stall."""
    durations = []
    start = due = time.perf_counter()
    deadline = start + seconds
    packet_bytes = 0
    while due < deadline:
        time.sleep(max(0, due - time.perf_counter()))
        if time.perf_counter() >= deadline:
            break
        data = build(len(durations))
        before = time.perf_counter()
        written = device.write_raw(data)
        after = time.perf_counter()
        if written < 0:
            raise OSError("HIDAPI rejected an output report")
        durations.append(after - before)
        packet_bytes = len(data)
        due = max(due + period, after)
    elapsed = time.perf_counter() - start
    ordered = sorted(durations)
    count = len(ordered)
    return {
        "reports": count,
        "report_bytes": packet_bytes,
        "elapsed_s": round(elapsed, 4),
        "required_reports_per_s": round(1 / period, 3),
        "achieved_reports_per_s": round(count / elapsed, 3),
        "write_mean_ms": round(1000 * sum(ordered) / count, 3) if count else None,
        "write_p50_ms": round(1000 * ordered[count // 2], 3) if count else None,
        "write_p99_ms": (
            round(1000 * ordered[min(count - 1, int(count * 0.99))], 3) if count else None
        ),
        "write_max_ms": round(1000 * ordered[-1], 3) if count else None,
        "writes_over_packet_period": sum(value > period for value in ordered),
    }


def profile(serial, seconds, microphone):
    require_controller_isolation()
    info = choose_controller(serial)
    # Encode before measuring: codec initialization is deliberately outside the
    # write-capacity measurement, and no nonzero waveform is generated.
    opus, haptic = A.silent_opus_frame(), A.silent_haptic_frame()
    shapes = Counter()
    errors = []
    stop = threading.Event()
    result = {
        "system": platform.system(),
        "system_version": platform.release(),
        "python": platform.python_version(),
        "hidapi": hid.version_str(),
        "microphone_requested": microphone,
        "audio_content": "silence",
        "input_payloads_saved": False,
        "phases": {},
    }
    with controller_activity(), interactive_thread(), DualSense(info) as device:

        def drain_input():
            with interactive_thread():
                while not stop.is_set():
                    try:
                        report = device.read_raw(timeout_ms=50, length=128)
                    except OSError as exc:
                        errors.append(str(exc))
                        break
                    if report:
                        kind = f"0x{report[0]:02x}/{len(report)}"
                        if report[0] == P.BT_INPUT_31 and len(report) > 1:
                            kind += f"/type{report[1] & P.PAYLOAD_TYPE_MASK}"
                        shapes[kind] += 1

        reader = threading.Thread(target=drain_input, name="dsshine-probe-input", daemon=True)
        reader.start()
        try:
            device.send_mic_state(microphone)
            time.sleep(0.02)
            device.send_mic_control(microphone)
            time.sleep(0.2)
            for label, period, build in (
                (
                    "control31_100hz",
                    0.01,
                    lambda i: P.build_bt_setstate(bytes(P.SetState().body), device._next_seq()),
                ),
                (
                    "audio36",
                    A.FRAME_MS / 1000,
                    lambda i: P.build_report_36(
                        opus, haptic, device._next_seq(), i % 256, mic_active=microphone
                    ),
                ),
                (
                    "audio39",
                    2 * A.FRAME_MS / 1000,
                    lambda i: P.build_report_39(
                        (opus, opus),
                        (haptic, haptic),
                        device._next_seq(),
                        (2 * i) % 256,
                        mic_enabled=microphone,
                    ),
                ),
            ):
                before = shapes.copy()
                phase = timed_phase(device, build, period, seconds)
                phase["input_report_shapes"] = dict(shapes - before)
                result["phases"][label] = phase
                time.sleep(0.25)
        except (OSError, KeyboardInterrupt) as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        finally:
            # Attempt both independently, including when a phase was interrupted.
            for cleanup in (
                lambda: device.send_mic_control(False),
                lambda: device.send_mic_state(False),
            ):
                try:
                    cleanup()
                    time.sleep(0.02)
                except OSError as exc:
                    errors.append("Microphone cleanup: " + str(exc))
            stop.set()
            reader.join(timeout=1)
            if reader.is_alive():
                errors.append("Input reader did not stop within one second")
    result["input_report_shapes"] = dict(shapes)
    result["errors"] = errors
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    parser.add_argument("--seconds", type=float, default=3, help="1–10 seconds per report type")
    parser.add_argument("--microphone", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("captures/bt-audio-capacity.json"))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 10:
        parser.error("--seconds must be between 1 and 10")
    result = profile(args.serial, args.seconds, args.microphone)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    # Slow but successful native writes are measurements, not an API error or an
    # audio-quality pass. The caller must compare the achieved and required rates.
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
