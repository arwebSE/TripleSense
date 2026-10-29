"""Small driver substitute; exercises the real TLS and USB/IP sockets."""

import asyncio
import struct

from ds5emu import wire as W


class Client:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.seq = 0

    @classmethod
    async def connect(cls, port):
        return cls(*await asyncio.open_connection("127.0.0.1", port))

    async def send(self, data):
        self.writer.write(data)
        await self.writer.drain()

    async def read(self, size):
        return await asyncio.wait_for(self.reader.readexactly(size), 3)

    async def devlist(self):
        await self.send(W.pack_op_common(W.OP_REQ_DEVLIST))
        header = W.unpack_op_common(await self.read(8))
        assert header[1:] == (W.OP_REP_DEVLIST, W.ST_OK)
        (count,) = struct.unpack(">I", await self.read(4))
        devices = []
        for _ in range(count):
            device = W.UsbDeviceInfo.unpack(await self.read(W.USB_DEVICE_SIZE))
            await self.read(device.bNumInterfaces * W.USB_INTERFACE_SIZE)
            devices.append(device)
        return devices

    async def attach(self):
        await self.send(W.pack_import_request("1-1"))
        _, _, status = W.unpack_op_common(await self.read(8))
        if status:
            return None
        return W.UsbDeviceInfo.unpack(await self.read(W.USB_DEVICE_SIZE))

    async def submit(self, *, direction, ep, setup=bytes(8), data=b"", length=0, iso=None):
        self.seq += 1
        request = W.CmdSubmit(
            self.seq,
            0x10001,
            direction,
            ep,
            0,
            len(data) if direction == W.DIR_OUT else length,
            0,
            len(iso) if iso else -1,
            1,
            setup,
        )
        await self.send(W.pack_cmd_submit(request) + data + W.pack_iso_packets(iso or []))
        result = W.unpack_ret_submit(await self.read(W.HEADER_SIZE))
        payload = await self.read(result["actual_length"]) if direction == W.DIR_IN else b""
        if result["number_of_packets"] > 0:
            await self.read(result["number_of_packets"] * W.ISO_DESC_SIZE)
        return result, payload

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


def setup(request_type, request, value=0, index=0, length=0):
    return struct.pack("<BBHHH", request_type, request, value, index, length)
