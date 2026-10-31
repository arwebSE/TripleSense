"""Touch gestures adapted from Macle57/ds5-virtual-cable's MIT input engine.

Reference: app/ds5app/intercept.py at c99dd9c519bebd508ff814fa7aedced0c0c443b6.
Retains its contact-adoption, tap suppression, centroid and fractional-motion
approach, without importing Windows-only shortcuts, desktop actions or its OSK.
The USB decoder is the already-vendored upstream implementation.
"""

from __future__ import annotations

import math
import time

from ds5bridge.protocol import decode_input


class TouchpadMouse:
    def __init__(self, output, *, clock=time.monotonic, speed=0.8):
        self.output, self.clock, self.speed = output, clock, speed
        self.previous = None
        self.started = 0.0
        self.distance = 0.0
        self.maximum = 0
        self.clicked = False
        self.held = None
        self.fraction = [0.0, 0.0]
        self.scroll = 0.0

    def on_input(self, report):
        if len(report) != 64 or report[0] != 1:
            return report
        state = decode_input(report[1:], usb=True)
        if state is None:
            return report
        points = sorted((point.id, point.x, point.y) for point in state.touch if point.active)
        fingers = len(points)
        center = (
            (sum(p[1] for p in points) / fingers, sum(p[2] for p in points) / fingers)
            if fingers
            else (0, 0)
        )
        now = self.clock()
        old = self.previous
        if fingers and (old is None or not old[0]):
            self.started, self.distance, self.maximum = now, 0.0, fingers
            # A contact already down when the bridge starts may move, but must
            # not become an accidental tap when the user eventually lifts it.
            self.clicked = old is None
        self.maximum = max(self.maximum, fingers)
        click = bool(state.buttons.get("touchpad"))
        if click:
            self.clicked = True
            if self.held is None:
                self.held = "right" if fingers == 2 else "left"
                self.output.button(self.held, True)
        elif self.held is not None:
            self.output.button(self.held, False)
            self.held = None
        if fingers and old and tuple(p[0] for p in points) == old[0]:
            dx, dy = center[0] - old[1][0], center[1] - old[1][1]
            self.distance += abs(dx) + abs(dy)
            if fingers == 1 and self.maximum == 1:
                movement = [dx * self.speed + self.fraction[0], dy * self.speed + self.fraction[1]]
                whole = [math.trunc(value) for value in movement]
                self.fraction = [
                    value - integer for value, integer in zip(movement, whole, strict=True)
                ]
                if any(whole):
                    self.output.move(*whole)
            elif fingers == 2 and not click:
                self.scroll += -dy / 20
                steps = math.trunc(self.scroll)
                if steps:
                    self.output.scroll(steps)
                    self.scroll -= steps
        elif not fingers and old and old[0]:
            if now - self.started <= 0.22 and self.distance <= 16 and not self.clicked:
                name = "right" if self.maximum == 2 else "left"
                self.output.button(name, True)
                self.output.button(name, False)
            self.maximum, self.scroll = 0, 0.0
        self.previous = (tuple(p[0] for p in points), center)
        # Consume both contacts and the physical click in the game-facing report.
        masked = bytearray(report)
        masked[10] &= ~2
        masked[33] |= 0x80
        masked[37] |= 0x80
        return bytes(masked)

    def close(self):
        if self.held is not None:
            self.output.button(self.held, False)
            self.held = None
        self.output.close()
