"""Render the shared vector mark into Windows, macOS and Linux icon assets."""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    root = Path(__file__).resolve().parents[1] / "src/assets"
    renderer = QSvgRenderer(str(root / "triplesense.svg"))
    images = {}
    for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        data = QByteArray()
        stream = QBuffer(data)
        stream.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(stream, "PNG")
        images[size] = bytes(data)
    (root / "triplesense.png").write_bytes(images[512])
    sizes = (16, 24, 32, 48, 64, 128, 256)
    offset = 6 + 16 * len(sizes)
    entries = []
    for size in sizes:
        entries.append(
            struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(images[size]), offset)
        )
        offset += len(images[size])
    (root / "triplesense.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(sizes))
        + b"".join(entries)
        + b"".join(images[size] for size in sizes)
    )
    chunks = b"".join(
        kind + struct.pack(">I", len(images[size]) + 8) + images[size]
        for kind, size in (
            (b"icp4", 16),
            (b"icp5", 32),
            (b"icp6", 64),
            (b"ic07", 128),
            (b"ic08", 256),
            (b"ic09", 512),
            (b"ic10", 1024),
        )
    )
    (root / "triplesense.icns").write_bytes(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)
    app.quit()


if __name__ == "__main__":
    main()
