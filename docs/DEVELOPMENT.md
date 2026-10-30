# DSShine development

This guide is for contributors. For installation and everyday use, start with
[the user README](../README.md).

[Architecture](ARCHITECTURE.md) · [Upstream comparison](UPSTREAM.md) ·
[Platform roadmap](ROADMAP.md) · [Validation evidence](VALIDATION.md) ·
[Third-party notices](../THIRD_PARTY_NOTICES.md)

A streaming-independent Windows DualSense device bridge, targeting native
controller input, adaptive triggers, and the audio path used for detailed haptics.

**Desktop preview:** DSShine now has a standalone Windows/Mac app with LAN
discovery, one-time PIN pairing, automatic reconnection and safe shutdown when the main window closes.
The Windows installer includes the free signed controller-bus driver and setup
for local-network access. Users do not need Python, SSH, manual certificates or prep commands.
See [standalone setup](STANDALONE.md). The CLI below remains available for
development and diagnostics.

The command is `dsshine`; the existing `ds5driver` command remains available.
Repository: [arwebSE/DSShine](https://github.com/arwebSE/DSShine).

**Development prototype.** Local Windows USB/HID/audio enumeration, live input,
physical adaptive-trigger mode readback, microphone capture, acoustic speaker
output, four-channel PCM transport and Sunshine start/stop commands have passed.
Mac-to-Windows input, native USB enumeration, trigger readback and microphone
signal have also passed. The user confirmed inputs, vibration and adaptive
triggers in the Windows browser tester. Mac Bluetooth audio currently drops
frames and has not passed repeatable speaker checks. Audio tests require Steam isolation on
the source PC. Game compatibility and subjective haptic quality remain unverified.
See [validation](VALIDATION.md) for current evidence.

## How it works

```text
Controller PC (Moonlight)                    Game PC (Sunshine, Windows)
Bluetooth DualSense                         Game -> DualSense HID + USB audio
       |                                                    |
Physical HID / audio codec <--- mutual TLS ---> localhost USB/IP tunnel
       |                                                    |
ds5-virtual-cable device emulator                   usbip-win2 UDE driver
```

Sunshine/Moonlight carry the stream as usual. This companion carries full
controller USB traffic separately, including four-channel speaker/haptic audio.
Sunshine's existing app preparation commands start/stop it. A fork is not
required for this first path. It does not appear in Sunshine's gamepad selector.

The base is the MIT-licensed
[ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable) emulator and
Bluetooth bridge, pinned under `vendor/`. The virtual USB bus uses the separately
installed [usbip-win2](https://github.com/vadimgrn/usbip-win2) driver. This project
adds authenticated remote transport, role commands, diagnostics and Sunshine
lifecycle integration. It does not implement a new custom kernel driver.

A HID-only DS5 emulation can forward trigger effects but lacks the USB audio
function used for audio-driven haptics. Preserving that function provides the
needed path; perceptual equivalence to a wired controller still needs testing.

## Developer / CLI setup

Windows x64 host, Python 3.11+, and a **standard DualSense over Bluetooth** on
the controller PC. For the tested macOS Bluetooth source and its audio limits, see
[Mac Moonlight setup](MACOS.md). USB-connected sources and Edge controllers
are not yet supported by this integration.
Exit Steam on the **physical-controller PC** before starting the source or live
tests. Its raw Bluetooth mappings include PS + L2 opening Magnifier; unintended
shortcuts appeared during microphone tests with Steam active. The source checks this
and refuses to start with Steam running. Steam on a separate Sunshine host is
fine; the host sees only the translated virtual USB controller.

```powershell
uv venv --python 3.12
uv sync --locked --extra controller --extra dev --extra app
.venv/Scripts/ds5driver.exe doctor
.venv/Scripts/ds5driver.exe probe --seconds 3
```

The controller PC needs the `controller` extra; the host needs only the base
package. Development on one PC works, but both physical and virtual controllers
will be visible during local game tests.

## Two-PC use

1. On the controller PC, generate a private credential pair and run the source:

   ```powershell
   .venv/Scripts/ds5driver.exe pair --out .credentials/pair
   .venv/Scripts/ds5driver.exe devices
   .venv/Scripts/ds5driver.exe source --credentials .credentials/pair/source --bind 0.0.0.0 --serial YOUR_CONTROLLER_SERIAL
   ```

   Securely copy only `host/` to the Sunshine PC. Both role folders contain
   private keys: never upload them. Allow TCP 3250 from the Sunshine PC through
   the controller PC's private-network firewall. Default binding is loopback.
   Certificates expire after one year; generate a fresh pair to renew/revoke.

2. Install the pinned, signed driver on the Sunshine host:

   ```powershell
   # Download/verify only:
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Install-HostDriver.ps1
   # Install from Administrator PowerShell:
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Install-HostDriver.ps1 -Install
   ```

   The script pins upstream 0.9.8.1 by SHA-256 and checks Authenticode. It changes
   no Secure Boot/test-signing settings and forces no restart. Review an existing
   USB/IP installation before upgrading. No replacement driver is installed on
   the physical controller; HidHide is not installed.

3. On the Sunshine PC, test manually:

   ```powershell
   .venv/Scripts/ds5driver.exe host --credentials .credentials/pair/host --source CONTROLLER_PC_IP --attach
   ```

   Ctrl+C detaches only this process's USB port. Driver access may require an
   Administrator terminal. This uses the 0.9.8.1 command interface.

4. Configure Sunshine's app hooks using [the integration guide](SUNSHINE.md).
   Disable ordinary forwarded controller input to avoid a second emulated pad.
   Disable Steam Input for native DualSense game testing. The game must support
   the effects itself; the bridge cannot add them to an XInput-only game.

This prototype targets a trusted, low-latency LAN. TCP packet loss and USB/BT
audio buffering add latency. WAN operation and subjective fidelity are untested.

## Verification

```powershell
.venv/Scripts/ruff.exe check src tests tools
.venv/Scripts/python.exe -m unittest discover -s tests -t . -v
.venv/Scripts/python.exe -m unittest discover -s vendor/ds5-virtual-cable/emulator/tests -t vendor/ds5-virtual-cable/emulator
# Real controller, no driver needed:
.venv/Scripts/python.exe tools/verify_live.py
# Installed host driver, administrator access may be required:
.venv/Scripts/python.exe tools/verify_windows.py
# Optional trigger and silent audio tests:
uv sync --locked --extra controller --extra dev --extra hardware-test
.venv/Scripts/python.exe tools/verify_windows.py --effects --audio
# Microphone capture and a quiet speaker tone; save signal statistics only:
.venv/Scripts/python.exe tools/verify_windows.py --microphone --speaker
```

Transport tests cover certificate rejection, native identity/input, exact
adaptive-trigger bytes, four-channel PCM, single importer ownership and release
on disconnect. They do not establish game or physical-effect compatibility.
Hardware captures and credentials are ignored by Git. See
[architecture](ARCHITECTURE.md) and [attribution](../THIRD_PARTY_NOTICES.md).

## Building the desktop apps

Build on the target platform with Python 3.11+:

```text
python -m pip install -e ".[controller,app,build]"
python tools/build_app.py
```

On Windows, first run `scripts/Install-HostDriver.ps1` without `-Install` to
download and verify the pinned driver installer. Install Inno Setup 6 and use
`python tools/build_app.py --installer` to create the setup executable. Neither
Python nor Inno Setup is needed on users' computers.

The app bundle includes dependency licenses. Shared Qt libraries remain
replaceable. Developer ID signing and notarization require release credentials
and are not simulated by the build. GitHub Actions builds downloadable desktop
artifacts with the **Build desktop app** workflow.
