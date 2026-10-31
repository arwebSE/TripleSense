# Architecture

TripleSense forwards a Bluetooth DualSense as a virtual USB controller on another
computer, independently of streaming software.

```text
Bluetooth DualSense ⇄ Client / controller engine ⇄ paired TLS ⇄ Server
                                                             ⇅
                                                   loopback USB/IP
                                                             ⇅
                                              virtual USB controller + audio
                                                             ⇅
                                                            game
```

The pinned [ds5-virtual-cable engine](UPSTREAM.md) supplies USB descriptors,
Bluetooth report conversion and audio codecs. TripleSense adds desktop lifecycle,
paired remote transport, discovery, platform adapters and packaging. It does not
implement a new kernel bus driver.

## Application layers

| Modules | Responsibility |
| --- | --- |
| `app.py`, `desktop.py`, `app_support.py` | UI, worker/event lifecycle, settings and discovery coordination. |
| `pairing.py`, `credentials.py`, `server_identity.py`, `saved_servers.py` | Enrollment, identities and saved Server profiles. |
| `reverse.py`, `transport.py`, `runtime.py` | Authenticated connections, USB/IP forwarding and owned Windows attachment/cleanup. |
| `controller.py`, `macos_bluetooth.py`, `native/macos_bluetooth.m`, `latency.py` | Physical Bluetooth backend and platform scheduling/transport adapters. |
| `lan.py`, `vpn.py` | LAN advertisements and direct queries to known VPN peers. |
| `linux_vhci.py`, `packaging/linux/triplesense-vhci` | Linux kernel attachment through a scoped privileged helper. |
| `mouse_proxy.py`, `touchpad_mouse.py`, `mouse_output.py` | Optional touch filtering/gestures and OS pointer injection. |
| `updates.py`, `update_dialog.py`, `assets/update-*` | GitHub package selection, verification, staging and installation. |
| `setup.py`, `windows_taskbar.py` | Installed Windows setup repair and shell identity. |
| `cli.py`, `diagnostics.py` | Developer commands and controller/driver diagnostics. |

## Pairing and connection

The Server listens on TCP 3250. The Client initiates authenticated connections;
its physical controller does not need an incoming network listener. A loopback
USB/IP endpoint gives the Server's virtual bus access to the offered device.

PIN pairing on TCP 3251 uses SPAKE2, authenticated encryption and mutual key
confirmation. Codes are short-lived, rate-limited and single-use. Saved sessions
use mutual TLS 1.3 with a private CA and fixed peer identities. The CA private key
is not saved and the system trust store is not changed.

Discovery uses mDNS and UDP 3252 LAN broadcasts/direct queries to VPN peers.
Advertisements identify candidates; they do not authenticate a Server. Address
updates must preserve the paired identity and an explicitly selected VPN route.
No Moonlight credentials or stream session keys are read.

## Controller and audio contract

| Feature | Virtual USB | Bluetooth |
| --- | --- | --- |
| Buttons, touch, motion, battery | HID IN 0x84 | Input 0x31 |
| Rumble, triggers, LEDs | HID OUT/control | SetState 0x31 |
| Calibration, pairing, firmware | Feature GET_REPORT | Live features converted for USB |
| Speaker and detailed haptics | Iso OUT 0x01, four PCM channels | 0x39 audio/haptic payloads |
| Microphone | Iso IN 0x82 | Multiplexed microphone payloads |

This describes the inherited transport contract, not a game-compatibility claim.
Audio defaults on; disabling it prevents microphone arming and audio output.
TCP scheduling, packet loss and Bluetooth/audio buffers affect latency and quality.
See [status](STATUS.md) and [Bluetooth research](research/BLUETOOTH_AUDIO.md).

## Ownership and shutdown

Only one importer owns the physical backend. Disconnect releases trigger/rumble
effects, closes audio alternate settings and stops the backend. Quit waits for
pending attachment work and cleans up the owned virtual device.

Windows uses usbip-win2's returned port plus a session serial and loopback location
to verify ownership before detach. A private journal supports crash recovery; a
port reassigned to another device is left alone. Linux uses the kernel's
`vhci_hcd`; its root-owned helper validates the local device and owns one socket,
which is closed on cancellation/EOF. Neither path globally detaches devices.

The Polkit helper, Windows signed bus driver and installer elevation are distinct
from the ordinary unprivileged app. macOS Server has no working backend yet; its
virtual-device permission and audio requirements are recorded in [status](STATUS.md).

The retained manual developer `source`/`host` roles use the same TLS/device model
with explicit credentials. They are separate from the desktop connection flow.
