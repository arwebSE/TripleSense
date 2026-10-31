"""Verify the Linux pointer adapter with uinput, without a desktop session.

Run only in an isolated Linux test environment: this emits pointer events.
"""

from __future__ import annotations

import json
import os
import select
import stat
import sys
import tempfile
import time
from pathlib import Path

from evdev import InputDevice
from evdev import ecodes as E

from dualsensedriver.mouse_output import LinuxMouse


def main():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("This isolated integration test requires Linux administrator access")
    before = set(Path("/sys/class/input").glob("event*"))
    output = LinuxMouse()
    try:
        node = None
        for _ in range(100):
            for event in set(Path("/sys/class/input").glob("event*")) - before:
                if (event / "device/name").read_text().strip() == "TripleSense touchpad mouse":
                    node = event
                    break
            if node:
                break
            time.sleep(0.01)
        if node is None:
            raise RuntimeError("Linux did not register the virtual mouse")
        major, minor = map(int, (node / "dev").read_text().split(":"))
        with tempfile.TemporaryDirectory(prefix="triplesense-mouse-") as temporary:
            private = Path(temporary) / "events"
            os.mknod(private, stat.S_IFCHR | 0o600, os.makedev(major, minor))
            with InputDevice(str(private)) as reader:
                output.move(17, -9)
                output.button("left", True)
                output.button("left", False)
                output.scroll(-2)
                expected = {
                    (E.EV_REL, E.REL_X, 17),
                    (E.EV_REL, E.REL_Y, -9),
                    (E.EV_KEY, E.BTN_LEFT, 1),
                    (E.EV_KEY, E.BTN_LEFT, 0),
                    (E.EV_REL, E.REL_WHEEL, -2),
                }
                events = set()
                deadline = time.monotonic() + 3
                while not expected.issubset(events) and time.monotonic() < deadline:
                    if select.select([reader.fd], [], [], 0.2)[0]:
                        events.update((item.type, item.code, item.value) for item in reader.read())
                if not expected.issubset(events):
                    raise RuntimeError(f"Missing Linux pointer events: {expected - events}")
                print(json.dumps({"linux_pointer_events": len(expected), "isolated_only": True}))
    finally:
        output.close()


if __name__ == "__main__":
    main()
