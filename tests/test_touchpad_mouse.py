import asyncio
import unittest

from ds5emu import wire as W
from triplesense.mouse_proxy import forward_responses
from triplesense.touchpad_mouse import TouchpadMouse


def report(points=(), clicked=False):
    data = bytearray(64)
    data[0] = 1
    data[1:5] = bytes([128] * 4)
    data[8] = 8
    data[10] = 2 if clicked else 0
    data[33] = data[37] = 0x80
    for index, (identity, x, y) in enumerate(points):
        base = 33 + index * 4
        data[base : base + 4] = bytes([identity, x & 255, (x >> 8) | ((y & 15) << 4), y >> 4])
    return bytes(data)


class Output:
    def __init__(self):
        self.events = []

    def move(self, *args):
        self.events.append(("move", *args))

    def button(self, *args):
        self.events.append(("button", *args))

    def scroll(self, *args):
        self.events.append(("scroll", *args))

    def close(self):
        self.events.append(("close",))


class TouchTests(unittest.TestCase):
    def setUp(self):
        self.output = Output()
        self.time = 1.0
        self.mouse = TouchpadMouse(self.output, clock=lambda: self.time, speed=1)
        self.mouse.on_input(report())

    def test_move_consumes_touch_but_keeps_other_input(self):
        self.mouse.on_input(report([(1, 100, 100)]))
        packet = bytearray(report([(1, 140, 110)]))
        packet[8] |= 0x20  # Cross still reaches the game.
        masked = self.mouse.on_input(bytes(packet))
        self.assertEqual(self.output.events, [("move", 40, 10)])
        self.assertEqual(masked[8], packet[8])
        self.assertTrue(masked[33] & 0x80)

    def test_tap_and_drag_do_not_double_click(self):
        self.mouse.on_input(report([(1, 100, 100)]))
        self.time += 0.1
        self.mouse.on_input(report())
        self.assertEqual(self.output.events, [("button", "left", True), ("button", "left", False)])
        self.output.events.clear()
        self.mouse.on_input(report([(1, 100, 100)], True))
        self.mouse.on_input(report([(1, 120, 100)], True))
        self.mouse.on_input(report())
        self.assertEqual(sum(event == ("button", "left", True) for event in self.output.events), 1)
        self.assertEqual(self.output.events[-1], ("button", "left", False))

    def test_two_fingers_scroll_without_cursor_jump_or_tap(self):
        self.mouse.on_input(report([(1, 100, 100)]))
        self.mouse.on_input(report([(1, 100, 100), (2, 300, 100)]))
        self.mouse.on_input(report([(1, 100, 160), (2, 300, 160)]))
        self.mouse.on_input(report())
        self.assertEqual(self.output.events, [("scroll", -3)])

    def test_replaced_contact_is_adopted_without_jump(self):
        self.mouse.on_input(report([(1, 100, 100)]))
        self.mouse.on_input(report([(2, 1400, 800)]))
        self.assertEqual(self.output.events, [])

    def test_shutdown_releases_held_button(self):
        self.mouse.on_input(report([(1, 100, 100)], True))
        self.mouse.close()
        self.assertEqual(self.output.events[-2:], [("button", "left", False), ("close",)])


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_and_features_stay_exact_and_hid_touch_is_consumed(self):
        device = W.UsbDeviceInfo("/virtual", "1-1", 1, 1, 3, 0x54C, 0xCE6, 0x100, 0, 0, 0, 1, 1, 4)
        prefix = W.pack_op_common(W.OP_REP_IMPORT) + device.pack()
        audio = W.pack_ret_submit(
            seqnum=1,
            ep=2,
            direction=W.DIR_IN,
            actual_length=4,
            data=b"abcd",
            number_of_packets=1,
            iso_packets=[W.IsoPacket(0, 4, 4, 0)],
        )
        feature = W.pack_ret_submit(
            seqnum=2, ep=0, direction=W.DIR_IN, actual_length=4, data=b"\x05abc"
        )
        raw = report([(1, 100, 100)])
        hid_header = W.pack_ret_submit(seqnum=3, ep=4, direction=W.DIR_IN, actual_length=64)
        reader = asyncio.StreamReader()
        reader.feed_data(prefix + audio + feature + hid_header + raw)
        reader.feed_eof()
        output = Output()

        class Writer:
            data = bytearray()

            def write(self, data):
                self.data.extend(data)

            async def drain(self):
                pass

        writer = Writer()
        with self.assertRaises(asyncio.IncompleteReadError):
            await forward_responses(reader, writer, lambda: TouchpadMouse(output))
        self.assertEqual(writer.data[: len(prefix + audio + feature)], prefix + audio + feature)
        self.assertTrue(writer.data[-31] & 0x80)
        self.assertEqual(output.events[-1], ("close",))

    async def test_malformed_device_list_is_rejected(self):
        reader = asyncio.StreamReader()
        reader.feed_data(W.pack_op_common(W.OP_REP_DEVLIST) + (1000).to_bytes(4, "big"))
        with self.assertRaises(ValueError):
            await forward_responses(reader, None, None)
