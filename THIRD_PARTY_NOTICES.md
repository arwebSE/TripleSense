# Third-party code

`vendor/ds5-virtual-cable` contains an unmodified subset of
[Macle57/ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable), pinned to
commit `2e24ffbfafd6d9ccd454a9a8b436e2696be426ce` (MIT).

Included: `emulator/ds5emu`, `emulator/tests`, `prototype/ds5bridge`, the two
reference documents used by those tests, and upstream license/attribution files.
Its nested [LICENSE](vendor/ds5-virtual-cable/LICENSE),
[NOTICE](vendor/ds5-virtual-cable/NOTICE) and
[ATTRIBUTIONS](vendor/ds5-virtual-cable/ATTRIBUTIONS.md) retain the full upstream
notices, including dualsense-tester and DS5Dongle. Those files describe the
upstream distribution; this project does not bundle its installer, GUI,
HidHide, native echo-canceller DLL or drivers. Microphone mode is `pad`, which
does not require the omitted native software echo canceller.

`usbip-win2` is a separately installed BSD-2-Clause Windows driver. Its source
and binary are not checked into this repository or the Python package. The
host installer script downloads an exact upstream release and verifies its
SHA-256 and Authenticode signature before running it.

LibrePadPS5, ViGEmBus, Sunshine, Moonlight, libvirtualhid and libvirtualgamepad
were reviewed as references; no source from those projects is included.
