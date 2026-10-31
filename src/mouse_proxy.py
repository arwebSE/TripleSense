"""Consume touch reports on the Server using the existing USB/IP response stream.

No new network protocol or client upgrade is required. Audio and feature data
are forwarded unchanged; only successful endpoint-4 HID input is interpreted.
"""

from __future__ import annotations

import logging
import struct

from ds5emu import wire as W

log = logging.getLogger(__name__)


async def forward_responses(reader, writer, mouse_factory):
    header = await reader.readexactly(W.OP_COMMON_SIZE)
    version, code, status = W.unpack_op_common(header)
    if version != W.USBIP_VERSION or status:
        writer.write(header)
        await writer.drain()
        return
    if code == W.OP_REP_DEVLIST:
        count = await reader.readexactly(4)
        number = struct.unpack(">I", count)[0]
        if number > 8:
            raise ValueError("Invalid USB/IP device count")
        writer.write(header + count)
        for _ in range(number):
            device = await reader.readexactly(W.USB_DEVICE_SIZE)
            interfaces = await reader.readexactly(device[-1] * 4)
            writer.write(device + interfaces)
        await writer.drain()
        return
    if code != W.OP_REP_IMPORT:
        raise ValueError("Unexpected USB/IP operation")
    writer.write(header + await reader.readexactly(W.USB_DEVICE_SIZE))
    await writer.drain()
    mouse = mouse_factory()
    try:
        await _urb_responses(reader, writer, mouse)
    finally:
        mouse.close()


async def _urb_responses(reader, writer, mouse):
    first_input = True
    while True:
        header = await reader.readexactly(W.HEADER_SIZE)
        command = struct.unpack_from(">I", header)[0]
        if command == W.RET_UNLINK:
            writer.write(header)
            await writer.drain()
            continue
        fields = W.unpack_ret_submit(header)
        length, packets = fields["actual_length"], fields["number_of_packets"]
        if not 0 <= length <= 1048576 or not 0 <= packets <= W.MAX_ISO_PACKETS:
            raise ValueError("Invalid USB/IP response length")
        payload = await reader.readexactly(length if fields["direction"] == W.DIR_IN else 0)
        iso = await reader.readexactly(packets * W.ISO_DESC_SIZE)
        endpoint = fields["ep"] & 0x7F
        if fields["direction"] == W.DIR_IN and endpoint in (0, 4) and fields["status"] == 0:
            if first_input and payload:
                log.info(
                    "Mouse filter received HID input: endpoint=%s bytes=%s",
                    fields["ep"],
                    len(payload),
                )
                first_input = False
            payload = mouse.on_input(payload)
        writer.write(header + payload + iso)
        await writer.drain()
