import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from dualsensedriver.ssh import SshForward


class SshTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_targets_that_could_be_options_or_remote_commands(self):
        for target in ("-oProxyCommand=bad", "user@host command", "user@host\n", "user@-host"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                SshForward(target, 3250)

    async def test_authentication_failure_propagates_and_finishes_stderr_reader(self):
        stderr = asyncio.StreamReader()
        stderr.feed_data(b"Permission denied (publickey).")
        stderr.feed_eof()
        process = Mock(returncode=255, stderr=stderr)
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)):
            forward = SshForward("user@192.0.2.1", 3250)
            with self.assertRaisesRegex(RuntimeError, "Permission denied"):
                await forward.start()
            self.assertTrue(forward.reader.done())
            process.terminate.assert_not_called()

    async def test_shutdown_terminates_only_the_owned_subprocess(self):
        forward = SshForward("user@192.0.2.1", 3250)
        forward.process = Mock(returncode=None, wait=AsyncMock())
        await forward.stop()
        forward.process.terminate.assert_called_once_with()
        forward.process.wait.assert_awaited_once_with()
        forward.process.kill.assert_not_called()
