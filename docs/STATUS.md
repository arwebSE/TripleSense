# Compatibility, validation and roadmap

Status for release **0.5.1**. Experimental means implemented but not yet accepted
on the physical platform. Source code or a synthetic test is not a hardware pass.

## Platforms

| Platform | Client | Server | Evidence / remaining work |
| --- | --- | --- | --- |
| Windows x64 | Implemented | Available | Mac-to-Windows input, triggers and vibration tested; physical Windows Client acceptance pending. |
| macOS Apple Silicon | Available | Planned | Bluetooth Client tested with Windows; Server needs a virtual-device backend including audio. |
| Linux ARM64 Debian/Ubuntu | Experimental | Experimental | Package installation, frozen launch and isolated kernel input tests passed; physical Bluetooth/audio and desktop permission tests pending. |
| Linux x64 | Source/build configuration | Source/build configuration | No published binary or local build acceptance yet. |

Physical-controller forwarding currently supports a standard Bluetooth DualSense.
USB-connected controllers and DualSense Edge acceptance remain future work.

## Features and evidence

| Feature | Current evidence |
| --- | --- |
| Buttons, sticks and touchpad | User-confirmed Mac-to-Windows browser tester input. Motion/battery reports are transported; broader game acceptance remains pending. |
| Adaptive triggers and ordinary vibration | User-confirmed resistance/release and vibration; physical trigger mode readback returned feedback then Off. |
| Speaker and microphone | Native Mac transport passed speaker/mic signal tests; user heard a clear, quiet tone. Long mixed haptics/full-duplex sessions still need acceptance. |
| Detailed audio haptics | Transport exists; game-specific quality and fidelity remain unverified. |
| Pairing/reconnect | Installed Mac/Windows app pairing and saved reconnect confirmed; cancellation and ownership cleanup covered by regression tests. |
| Tailscale | Live input and adaptive-trigger feedback passed. |
| NetBird | Discovery/firewall paths implemented; complete live controller session pending. |
| Touchpad mouse | Windows pointer injection and Linux uinput tests passed. Live Mac-to-Windows movement is unresolved: empty interrupt-IN responses were observed upstream. |
| In-app updates | Real Windows/Mac install-and-restart checks passed, retained pairings and matched the built executable. GitHub asset hashes verified. Linux package installation passed; desktop update flow still needs live acceptance. |

Release 0.5.1 passed 102 project tests on Windows, macOS and Linux, with one skip
on Windows/macOS and two on Linux. The subsequent cleanup retains applicable
regressions and removes tests solely for the retired Sunshine/SSH launch paths;
use the test command in [development](DEVELOPMENT.md) for the current suite.
Packaged launch, icon and codec checks passed on all three platforms.

The Linux kernel fixture imported a synthetic Sony USB device using `vhci_hcd`,
registered gamepad input and delivered evdev axis events. Import/cleanup passed
including port zero. Real uinput pointer/button/wheel events also passed. The
available Linux VM lacks USB audio drivers; this does not establish physical
Linux audio, Wayland/X11 usability or Bluetooth throughput.

Historical probes and captures are retained in Git history and ignored local
capture directories, rather than presented as current setup instructions.
The [Bluetooth research notes](research/BLUETOOTH_AUDIO.md) retain useful failed
approaches and measurements; their old HID-path limits are not a verdict on the
new native transport.

## macOS Server prerequisite

A native `IOHIDUserDeviceCreateWithProperties` probe on the available Mac returned
no device. Apple's SDK/kernel requires the virtual-HID entitlement or its separate
user-access entitlement; running as administrator does not grant it. The backend
must also supply the controller's audio interfaces: virtual HID alone is not the
complete device.

References: [Apple entitlement documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.hid.virtual.device)
and [IOHID kernel checks](https://github.com/apple-oss-distributions/IOHIDFamily/blob/main/IOHIDFamily/IOHIDResourceUserClient.cpp).
Existing entitled gamepad projects and generic keyboard/mouse drivers do not by
themselves provide an approved, full DualSense USB/audio backend for this app.

## Priorities

1. Resolve the current live Mac input/touchpad failure; test cancellation,
   reconnect, controller sleep and network changes with installed apps.
2. Validate sustained Bluetooth speaker, microphone and detailed haptics together
   in representative games, including a 30-minute session and clean shutdown.
3. Complete physical Linux Client/Server acceptance, USB audio enumeration,
   desktop permissions, both architectures and the Linux updater flow.
4. Validate Windows Clients and complete NetBird sessions.
5. Add physical USB forwarding and a viable macOS Server backend.
6. Add controller shortcuts, touchpad gestures and launchers for the operating
   system's on-screen keyboard; do not build a separate keyboard UI.
7. Add Developer ID signing/notarization for simpler Mac distribution.

The target remains Windows, macOS and Linux in both roles, Bluetooth and USB,
with motion, triggers, vibration, microphone and speaker. Only advertise a
combination as validated after its backend and hardware acceptance pass.
