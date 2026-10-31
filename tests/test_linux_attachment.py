import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from dualsensedriver.linux_vhci import LinuxAttachment


class AttachmentTests(unittest.IsolatedAsyncioTestCase):
    def process(self, response):
        stdout = asyncio.StreamReader()
        stdout.feed_data(response)
        stdout.feed_eof()
        return SimpleNamespace(
            stdin=SimpleNamespace(close=Mock()),
            stdout=stdout,
            stderr=SimpleNamespace(read=AsyncMock(return_value=b"")),
            wait=AsyncMock(return_value=0),
            returncode=0,
        )

    async def test_zero_is_a_valid_linux_usb_port_and_cleanup_closes_owned_pipe(self):
        process = self.process(b'{"port":0}\n')
        attachment = LinuxAttachment()
        with (
            patch("dualsensedriver.linux_vhci.os.geteuid", return_value=0, create=True),
            patch(
                "dualsensedriver.linux_vhci.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
        ):
            self.assertEqual(await attachment.start(4000), 0)
            await attachment.stop()
            await attachment.stop()
        process.stdin.close.assert_called_once_with()
        process.wait.assert_awaited_once()

    async def test_invalid_helper_reply_cleans_up_without_selecting_a_detach_port(self):
        process = self.process(b'{"port":256}\n')
        attachment = LinuxAttachment()
        with (
            patch("dualsensedriver.linux_vhci.os.geteuid", return_value=0, create=True),
            patch(
                "dualsensedriver.linux_vhci.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Invalid response"):
                await attachment.start(4000)
        process.stdin.close.assert_called_once_with()
        self.assertIsNone(attachment.process)

    async def test_cancel_before_helper_ready_closes_the_helper_input(self):
        process = self.process(b"")
        process.stdout = asyncio.StreamReader()
        attachment = LinuxAttachment()
        with (
            patch("dualsensedriver.linux_vhci.os.geteuid", return_value=0, create=True),
            patch(
                "dualsensedriver.linux_vhci.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
        ):
            pending = asyncio.create_task(attachment.start(4000))
            await asyncio.sleep(0.01)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        process.stdin.close.assert_called_once_with()
