# Linux and macOS expansion

Version 0.5.1 ships the Linux and touchpad work as experimental features.
The validation boundaries below still apply.

Implementation branch: `codex/platforms-and-touchpad`. At the user's request,
the Windows app was updated to development 0.5.1 for live mouse/update testing.
The Mac was also updated to 0.5.1 after SSH access returned. The temporary
retry/build jobs have finished; no recurring updater job was installed.

## Reuse decisions

- Linux Server reuses the kernel's `vhci_hcd` USB/IP host controller, including
  its isochronous URB path. A small Polkit helper connects one loopback socket
  and passes it to the documented sysfs ABI. It shuts down that exact socket
  for cleanup, avoiding unsafe global port-detach commands.
  [Kernel implementation](https://github.com/torvalds/linux/blob/master/drivers/usb/usbip/vhci_rx.c)
- Linux Client reuses our existing Macle57 Bluetooth backend and report/audio
  conversion. Debian/Ubuntu packaging bundles Python and Qt and installs
  desktop launchers, active-seat HID access and automatic startup support.
  Physical Linux Bluetooth throughput still needs hardware testing.
- Touchpad mouse tracking adapts Macle57's MIT input engine, using its existing
  report decoder. A server-side USB/IP response filter consumes touch contacts
  and clicks while enabled. Buttons and audio stay on the existing connection.
  Windows uses SendInput; Linux uses python-evdev/uinput, including Wayland.
  This is opt-in in Server settings and does not add a network pairing/channel.
  [Upstream gestures](https://github.com/Macle57/ds5-virtual-cable/blob/c99dd9c519bebd508ff814fa7aedced0c0c443b6/app/ds5app/intercept.py)

## macOS Server prerequisite: confirmed on hardware

On the available Apple Silicon Mac running macOS 26.7.1, a minimal native
`IOHIDUserDeviceCreateWithProperties` probe returned a null device
(`VIRTUAL_HID_DENIED`). The current SDK explicitly requires
`com.apple.developer.hid.virtual.device`; the open-source kernel checks that
entitlement or Apple's separate user-access entitlement. Running a process as
administrator is not a substitute for either entitlement.

[Apple entitlement documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.hid.virtual.device)
and [Apple's kernel check](https://github.com/apple-oss-distributions/IOHIDFamily/blob/main/IOHIDFamily/IOHIDResourceUserClient.cpp).

Existing projects confirm the same boundary: Satellite uses entitled
IOHIDUserDevice for its Mac receiver; extender's virtual USB DriverKit path has
additional entitlement/loading limitations. Reusing those projects cannot grant
our app an Apple entitlement. No Steam process injection, SIP changes, test
signing exceptions or paid third-party virtual-gamepad driver are introduced.

OpenJoystickDriver's free signed app was also checked as a possible broker.
Its public virtual-feed API provides normalized buttons/axes and three
generic/Xbox layouts, rather than raw DualSense HID reports or composite USB
audio. Using that API would reduce the required controller feature set.
[Feed schema](https://github.com/xsyetopz/OpenJoystickDriver/blob/main/Sources/OpenJoystickDriverKit/ApplicationService/Payloads/VirtualFeedPayloads.swift)
and [device schema](https://github.com/xsyetopz/OpenJoystickDriver/blob/main/Resources/Schemas/virtual-device.schema.json).

To ship a native macOS Server, obtain the Apple virtual-HID entitlement and
matching provisioning/signing first. HID alone also does not create the
controller's USB audio interfaces: Core Audio virtual audio devices or an
approved virtual USB host controller are separate work. macOS Server remains
unavailable until a working backend can be validated, including microphone,
speaker and feedback. The UI must not advertise it as completed support.

## Validation boundaries

Automated gesture/TLS tests use fake OS output. A separate isolated Linux
kernel test checks actual uinput movement, button and wheel events. The virtual
USB integration imports the synthetic DualSense through the real kernel; its
full mode also checks ALSA capture/playback without opening a physical microphone.
CI tests are distinct
from physical Linux controller acceptance and do not prove Bluetooth audio
throughput, latency or perceptual quality.

## Current verification results

- Windows: 93 app tests passed (one skipped), including gesture masking,
  paired TLS mouse traffic, audio/feature byte preservation, cancellation and
  Linux port-zero handling. The 0.5.0 Windows installer also built successfully.
- macOS: 93 app tests passed (one skipped), without touching
  the installed controller app. The virtual HID capability probe was denied.
- Linux ARM64/Debian 12 container: 93 app tests (one skipped), frozen GUI
  launch/icon/codec checks and 0.5.0 .deb build passed.
- LinuxKit 6.12.76 kernel: the helper imported and enumerated the synthetic
  Sony USB device, registered a gamepad input device and delivered 144 bytes of
  evdev axis events. Import and cleanup passed twice, including port zero.
  Actual uinput motion, left-button down/up and wheel events also passed.
- This VM lacks ALSA USB-audio drivers, so kernel audio tests still need a
  normal Linux system. No physical Linux controller acceptance is claimed.
- GitHub hosted jobs did not start: account billing/spending-limit rejection.
- Only test-owned fixtures were stopped; the existing Docker workload and
  existing private settings and saved pairings were preserved.

## 0.5.1 updates and live mouse investigation

- Windows: 102 app tests passed, one skipped. Frozen installer launch/icon/codec
  checks passed. The update helper installed 0.5.1 and reopened the app; the
  installed executable matched the tested build's SHA-256. Settings retained
  Server mode, the saved Client and enabled mouse control.
- GitHub: a real private 0.4.16 release installer was downloaded and its size
  and SHA-256 verified using an existing local test credential held in memory.
  Anonymous access produced the expected private-repository error. No credential
  is embedded or copied into the app. Newer development builds are not downgraded.
- Mac: 102 tests passed, one skipped, followed by frozen launch/icon/codec,
  bundle ID/version/signature verification and installation of 0.5.1. A second
  actual update-handoff exercise waited for the running app to quit, replaced
  the bundle and relaunched it with a new PID. Client mode, pairing and enabled
  audio were retained. Source-archive CRLF conversion found during installation
  was fixed with LF attributes and defensive script normalization.
- Mouse: native Windows pointer injection worked, and full endpoint addresses
  such as 0x84 are now covered by a paired TLS regression test. The live Windows
  trace actually used endpoint 4 and received empty interrupt-IN responses from
  the Mac. The user still reported no cursor movement after that endpoint fix.
  A direct native-backend probe connected but reported zero Bluetooth input;
  this is unresolved and must not be described as a working hardware mouse test.
  After installation, the Mac app could be queried but had no active controller
  connection. A physical reconnect/live touch test is still required.
- A local, same-user diagnostics IPC command reports version, attachment,
  mouse mode, backend counters and worker liveness. It includes no raw input or
  audio buffers. Temporary Python firewall access used for tracing was removed.
