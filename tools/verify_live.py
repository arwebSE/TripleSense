"""Exercise real Bluetooth -> TLS -> USB/IP URBs on one PC, without installing a driver.

Run from the repository: .venv/Scripts/python tools/verify_live.py
This opens the controller and performs its normal bridge initialization; no
test trigger resistance or rumble is requested. It does not prove Windows USB
enumeration or subjective haptic quality. Reports stay under ignored captures/.
"""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ds5emu import wire as W  # noqa: E402
from ds5emu.bridge import BridgeBackend  # noqa: E402
from ds5emu.timing import TimerResolution  # noqa: E402
from ds5emu.translate import bt31_payload_to_usb01  # noqa: E402
from triplesense.credentials import generate_pair, tls_context  # noqa: E402
from triplesense.diagnostics import (  # noqa: E402
    choose_controller,
    require_controller_isolation,
)
from triplesense.transport import HostTunnel, SecureSource  # noqa: E402

from tests.wire_client import Client, setup  # noqa: E402


async def verify():
    require_controller_isolation()
    with tempfile.TemporaryDirectory() as tmp:
        pair = Path(tmp) / "pair"
        generate_pair(pair)
        physical = choose_controller(None)
        backend = BridgeBackend(serial=physical.serial, keep_raw=True, mic_mode="pad")
        source = SecureSource(backend, tls_context(pair / "source", server=True), port=0)
        tunnel = None
        client = None
        try:
            await source.start()
            tunnel = HostTunnel("127.0.0.1", source.port, tls_context(pair / "host", server=False))
            await tunnel.start()
            client = await Client.connect(tunnel.port)
            device = await client.attach()
            assert device is not None
            features = {}
            for rid, length in ((0x05, 41), (0x09, 20), (0x20, 64)):
                result, data = await client.submit(
                    direction=W.DIR_IN,
                    ep=0,
                    setup=setup(0xA1, 1, 0x300 | rid, 3, length),
                    length=length,
                )
                assert result["status"] == 0 and len(data) == length, (rid, result)
                features[f"0x{rid:02x}"] = len(data)
            parity = 0
            count = 250
            start = time.perf_counter()
            for _ in range(count):
                result, report = await client.submit(direction=W.DIR_IN, ep=4, length=64)
                assert result["status"] == 0 and len(report) == 64
                expected = bt31_payload_to_usb01(backend.last_bt_payload)
                # The emulated USB endpoint owns its sequence counter (byte 7).
                assert report[:7] + report[8:] == expected[:7] + expected[8:]
                parity += 1
            result = {
                "physical_transport": "Bluetooth",
                "virtual_vid_pid": "054c:0ce6",
                "transport": "TLS 1.3 with mutual certificates (loopback)",
                "usb_interfaces": device.bNumInterfaces,
                "input_reports": count,
                "byte_parity_except_usb_sequence": parity,
                "duration_s": round(time.perf_counter() - start, 3),
                "features": features,
                "windows_driver_attached": False,
                "physical_effect_quality_tested": False,
            }
            output = Path("captures/live-tunnel.json")
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, indent=2))
        finally:
            if client:
                await client.close()
            if tunnel:
                await tunnel.stop()
            await source.stop()


if __name__ == "__main__":
    with TimerResolution(1):
        asyncio.run(verify())
