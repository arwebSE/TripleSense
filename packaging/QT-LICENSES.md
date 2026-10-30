# Qt and PySide

TripleSense uses the open-source LGPL option for dynamically linked Qt/PySide.
The bundled Qt/PySide commercial license text supplied by their wheels does
not mean this project holds or requires a commercial Qt license.

LGPL-3.0 and GPL-3.0 license texts are included next to this file. Upstream
source and build instructions are available at:

- https://code.qt.io/cgit/pyside/pyside-setup.git/ (tag v6.12.0)
- https://code.qt.io/cgit/qt/qtbase.git/ (tag v6.12.0)
- https://doc.qt.io/qtforpython-6/building_from_source/index.html

Qt and PySide remain separate shared libraries in the application bundle.
They may be replaced with compatible modified builds; no check is used to
prevent that replacement. Re-sign a modified macOS app as needed for macOS to
run it. The exact versions used in a build are recorded in DEPENDENCIES.json.

Other bundled library licenses retain their upstream paths in this directory.
