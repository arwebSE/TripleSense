import ctypes
import sys
import unittest

from triplesense.latency import controller_activity, interactive_thread


@unittest.skipUnless(sys.platform == "darwin", "Native macOS scheduling API")
class MacLatencyTests(unittest.TestCase):
    def test_activity_and_thread_priority_unwind_after_failure(self):
        library = ctypes.CDLL(None)
        before = library.qos_class_self()
        with self.assertRaisesRegex(RuntimeError, "test exit"):
            with controller_activity(), interactive_thread():
                self.assertEqual(library.qos_class_self(), 0x21)
                raise RuntimeError("test exit")
        self.assertEqual(library.qos_class_self(), before)
        # A second activity also needs to survive the first autorelease pool's drain.
        with controller_activity():
            pass
