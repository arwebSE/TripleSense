"""Enumerate and sample the real controller without sending force effects."""

from __future__ import annotations

import dataclasses
import shutil
import time
from collections import Counter
from pathlib import Path


def find_usbip(explicit: str | None = None) -> str | None:
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"USB/IP executable not found: {path}")
        return str(path)
    found = shutil.which("usbip")
    if found:
        return found
    for location in (r"C:\Program Files\USBip\usbip.exe", r"C:\Program Files\usbip-win2\usbip.exe"):
        if Path(location).is_file():
            return location
    return None


def devices() -> list[dict]:
    from ds5bridge.device import enumerate_devices

    return [
        {"transport": d.transport, "serial": d.serial, "product": d.product}
        for d in enumerate_devices()
    ]


def choose_controller(serial: str | None):
    from ds5bridge.device import enumerate_devices

    candidates = [d for d in enumerate_devices() if d.transport == "BT"]
    if serial:
        candidates = [d for d in candidates if d.serial.lower() == serial.lower()]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one Bluetooth DualSense; found {len(candidates)}. "
            "Turn it on, run 'ds5driver devices', and select it with --serial."
        )
    return candidates[0]


def probe(serial: str | None, seconds: float) -> dict:
    from ds5bridge.device import DualSense

    info = choose_controller(serial)
    device = DualSense(info)
    lengths: Counter = Counter()
    states = 0
    last = None
    features = {}
    start = time.perf_counter()
    try:
        device.open()
        for report_id in (0x05, 0x09, 0x20):
            try:
                report = device.get_feature(report_id, 64)
                features[f"0x{report_id:02x}"] = {"bytes": len(report), "ok": bool(report)}
            except OSError as exc:
                features[f"0x{report_id:02x}"] = {"error": str(exc)}
        start = time.perf_counter()
        while time.perf_counter() - start < seconds:
            report = device.read_raw(timeout_ms=50)
            if not report:
                continue
            lengths[f"0x{report[0]:02x}/{len(report)}"] += 1
            from ds5emu.translate import bt31_report_to_usb01

            usb = bt31_report_to_usb01(report)
            if usb:
                from ds5bridge.protocol import decode_input

                last = decode_input(usb[1:], usb=True)
                states += 1
    finally:
        device.close()
    elapsed = time.perf_counter() - start
    summary = dataclasses.asdict(last) if last else None
    if summary:
        summary.pop("raw", None)
    result = {
        "transport": info.transport,
        "serial": info.serial,
        "elapsed_s": round(elapsed, 3),
        "input_reports": states,
        "reports_per_s": round(states / elapsed, 1),
        "report_shapes": dict(lengths),
        "features": features,
        "last_state": summary,
        "output_effects_sent": False,
    }
    if not states:
        raise RuntimeError(f"Controller opened but no extended input arrived: {result}")
    return result
