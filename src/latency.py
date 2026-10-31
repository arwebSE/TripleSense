"""Scope macOS scheduling priority to the active controller work."""

import ctypes
import logging
import sys
from contextlib import contextmanager

log = logging.getLogger(__name__)


@contextmanager
def controller_activity():
    """Keep macOS from coalescing the active USB/audio role as background work."""
    if sys.platform != "darwin":
        yield
        return
    ctypes.CDLL("/System/Library/Frameworks/Foundation.framework/Foundation")
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

    def send(restype, argument_types, target, selector, *values):
        method = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argument_types)(
            address
        )
        return method(target, objc.sel_registerName(selector), *values)

    pool = send(ctypes.c_void_p, [], objc.objc_getClass(b"NSAutoreleasePool"), b"new")
    process = None
    activity = None
    try:
        process = send(ctypes.c_void_p, [], objc.objc_getClass(b"NSProcessInfo"), b"processInfo")
        reason = send(
            ctypes.c_void_p,
            [ctypes.c_char_p],
            objc.objc_getClass(b"NSString"),
            b"stringWithUTF8String:",
            b"DualSense controller input and USB audio streaming",
        )
        # NSActivityLatencyCritical | NSActivityUserInitiatedAllowingIdleSystemSleep.
        # Only this process is affected; the display and system can still idle sleep.
        options = 0xFF00000000 | (0xFFFFFF & ~(1 << 20))
        activity = send(
            ctypes.c_void_p,
            [ctypes.c_uint64, ctypes.c_void_p],
            process,
            b"beginActivityWithOptions:reason:",
            options,
            reason,
        )
        yield
    finally:
        if activity:
            send(None, [ctypes.c_void_p], process, b"endActivity:", activity)
        send(None, [], pool, b"drain")


@contextmanager
def interactive_thread():
    """Undo SSH's utility QoS on this thread; restore it when the role exits."""
    library, previous = None, None
    if sys.platform == "darwin":
        library = ctypes.CDLL(None)
        library.qos_class_self.restype = ctypes.c_uint
        library.pthread_set_qos_class_self_np.argtypes = [ctypes.c_uint, ctypes.c_int]
        previous = library.qos_class_self()
        # QOS_CLASS_USER_INTERACTIVE: continuously serviced HID and audio deadlines.
        status = library.pthread_set_qos_class_self_np(0x21, 0)
        if status:
            log.warning("macOS could not request interactive controller scheduling: %d", status)
            library = None
    try:
        yield
    finally:
        if library and previous:
            library.pthread_set_qos_class_self_np(previous, 0)
