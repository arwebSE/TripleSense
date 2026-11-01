# Development

For installation and daily use, start with the [README](../README.md) or
[user guide](GUIDE.md). This page is for building, testing and diagnosing TripleSense.

[Architecture](ARCHITECTURE.md) · [Compatibility and roadmap](STATUS.md) ·
[Upstream credits](UPSTREAM.md) · [Third-party notices](../THIRD_PARTY_NOTICES.md)

## Source layout

| Directory | Purpose |
| --- | --- |
| `src/` | Application modules, assets and native Mac Bluetooth helper. |
| `tests/` | Application, protocol, lifecycle, networking and UI regressions. |
| `tools/` | Builds, packaging, icon generation and hardware/kernel probes. |
| `packaging/` | Installers, Linux helper/container and bundled license notices. |
| `scripts/` | Pinned Windows driver download/verification. |
| `vendor/ds5-virtual-cable/` | Pinned controller engine, its tests and required notices/reference data. |
| `docs/` | User/developer guides, current status and focused Bluetooth research. |

Setuptools maps the flat `src/` directory to the `triplesense` Python package.
The desktop and console entry points use the TripleSense name. The frozen builder
stages a package under `build/` so PyInstaller can analyze the same modules.

## Environment

Use Python 3.11 or later; Python 3.12 is used in CI. Install an editable checkout
in a virtual environment:

```text
python -m pip install -e ".[controller,app,build,dev]"
python -m triplesense.app
```

The desktop app owns pairing and connection lifecycle. The earlier Sunshine
prep-command/session launcher and SSH forwarding wrapper have been retired;
normal operation needs neither. Existing external launch hooks should be removed
when switching to the desktop app.

On Linux, build dependencies include the compiler, libudev/libevdev headers and
Qt runtime libraries; [the build container](../packaging/linux/Dockerfile) lists
the exact Debian dependencies. End-user packages include Python and Qt.

## Tests

```text
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m unittest discover -s tests -t .
python -m unittest discover -s vendor/ds5-virtual-cable/emulator/tests -t vendor/ds5-virtual-cable/emulator
```

The main suite uses synthetic controllers and isolated settings. It covers
pairing/authentication, saved servers, discovery, attachment ownership, cleanup,
cancellation, audio toggling, updates and mouse filtering. Synthetic success does
not establish physical audio, haptics or game compatibility.

Hardware tools are separate and may open a controller or create a virtual device:

| Tool | Purpose |
| --- | --- |
| `tools/verify_live.py` | Real Bluetooth input/features through a local TLS/USB-IP tunnel, without a Windows driver. |
| `tools/verify_windows.py` | Windows virtual HID/audio enumeration, owned detach, and optional effect/audio signal checks. Use `--help` for options. |
| `tools/profile_bt_audio.py` | Bluetooth capacity and scalar audio diagnostics. |
| `tools/test_linux_vhci.py` | Root-only synthetic virtual USB/kernel test; full mode also checks ALSA. |
| `tools/test_linux_mouse.py` | Actual Linux uinput pointer/button/wheel test. |

Close software using the physical controller, especially Steam on the Client,
before live tests. Signal measurements do not establish subjective audio quality.
Credentials, device identifiers and captures stay out of Git; do not commit keys
or microphone recordings. See [current evidence and acceptance work](STATUS.md).

The console command `triplesense --help` exposes diagnostics plus manual
`pair`, `source` and `host` roles for isolated transport work. These roles use
explicit private TLS credentials and are not the desktop pairing flow. The
`host` role attaches through Windows USB/IP; Linux desktop attachment uses its
separate helper. Do not document these commands as required user setup.

## Desktop builds

Build on the target platform:

```text
python tools/build_app.py
```

Windows builds first need the pinned driver download, verified by
`scripts/Install-HostDriver.ps1` without `-Install`. Install Inno Setup 6 and use
`python tools/build_app.py --installer` to produce the setup executable. The script's
`-Install` option is for deliberate local driver setup, not an ordinary build.

macOS builds compile the native Bluetooth transport and produce an app, DMG and
ZIP. Release builds currently use local signatures; Developer ID signing and
notarization require release credentials.

Linux builds produce an architecture-specific Debian package with desktop
launcher, udev rules and the narrowly scoped Polkit helper. The app stays
unprivileged. Use an isolated kernel fixture for attachment tests; never detach
all USB/IP devices or stop unrelated Docker workloads.

The builder verifies frozen launch, codecs and app icons using temporary settings.
Windows checks include taskbar identity. Shared Qt libraries remain replaceable;
license files are bundled. `Build desktop app` is the CI packaging workflow.

## Releases and updates

Update `src/__init__.py` for the release version; package metadata and the Windows
installer both derive their version from it.
Build/test packages, publish matching assets and `SHA256SUMS.txt` to GitHub, and
record experimental limitations in the release notes. The updater selects the
matching OS/architecture asset and verifies GitHub's SHA-256/size before staging.
Installation waits for safe app shutdown, then installs and relaunches. Only publicly accessible releases are supported; the app has no login or token flow.

Source distributions must retain the native Mac source, Linux helper/container,
installer templates, license notices and inherited test fixtures. Keep
`MANIFEST.in` and package-data rules in sync when moving files.
