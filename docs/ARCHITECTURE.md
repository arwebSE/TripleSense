# Architecture and reference research

ViGEmBus emulates Xbox 360 / DS4, not native DualSense. Current Sunshine has
since added libvirtualhid and a separately licensed Windows driver. Moonlight
common-c already exposes `ConnListenerSetAdaptiveTriggers`; trigger rumble and
adaptive-trigger effect payloads must not be confused.

The open-source libvirtualgamepad VHF DS5 profile is another HID foundation.
Its documentation identifies the absent USB audio function as a limitation for
audio-driven HD haptics. A virtual HID descriptor here would have that limit.

This prototype instead reuses a complete USB/IP DualSense device model and
Bluetooth bridge. Windows' ordinary HID/audio class drivers bind through the
separately installed usbip-win2 virtual USB bus. New code stays in user mode.
Maintaining a new kernel bus driver would not alone solve the network/audio gap.

| Feature | Virtual USB path | Bluetooth path |
| --- | --- | --- |
| Buttons, touch, IMU, battery | HID IN 0x84 | Input 0x31 |
| Rumble, adaptive triggers, LEDs | HID OUT 0x03 / control | SetState 0x31 |
| Calibration, pairing, firmware | Feature GET_REPORT | Live features, converted for USB |
| Speaker and detailed haptics | Iso OUT 0x01, 4 PCM channels | 0x39: Opus plus haptic samples |
| Microphone | Iso IN 0x82 | Multiplexed microphone payloads |

This table describes the inherited contract; game acceptance is separate.
The current physical-source profile is standard 054C:0CE6 over Bluetooth.

## Ownership and security

The source requires a paired client certificate over TLS 1.3. The host verifies
the private CA and fixed server identity. Certificates have distinct server /
client usages; the CA private key is never saved. No system trust store changes.

Plain USB/IP is exposed only on host loopback. The tunnel moves bytes with
backpressure and TCP_NODELAY without reducing the device to DS4/XInput. Only one
importer owns the source. Closing its connection queues trigger/rumble release
and closes audio alternate settings. Source shutdown drains network tasks and
stops the physical backend. Host shutdown detaches only the positive port
returned by `usbip attach --terse`.
Before detaching, it rechecks both the loopback location and the unique session
serial so a reassigned port is left untouched. Inactive USB devices stay attached;
TCP keepalive handles broken links, while transfer payload reads have a timeout.

TCP head-of-line blocking and remote USB scheduling remain constraints. Existing
Bluetooth PCM/Opus buffers add latency. The ~250 Hz local virtual input rate is
not an end-to-end latency measurement. LAN and perceptual tests are required.

## Primary sources

- [LibrePadPS5](https://github.com/arwebSE/LibrePadPS5): ownership, recovery and
  diagnostics lessons. Its PS5 input service layer is platform-specific; published
  limitations exclude game-driven rumble and audio. No source copied.
- [ViGEmBus](https://github.com/nefarius/ViGEmBus): existing emulation scope.
- [Sunshine](https://github.com/LizardByte/Sunshine): app hooks, input disable
  setting, platform backend structure.
- [New Sunshine input stack](https://app.lizardbyte.dev/2026-08-16-introducing-libvirtualhid-and-virtual-hid-driver/): official alternative.
- [Moonlight common-c](https://github.com/moonlight-stream/moonlight-common-c):
  adaptive-trigger callback and streaming protocol.
- [libvirtualgamepad DS5](https://github.com/Nonary/libvirtualgamepad/blob/main/docs/DS5_USB_COMPATIBILITY.md): native HID requirements and USB audio limitation.
- [ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable): selected
  USB/audio/BT foundation, exact revision in THIRD_PARTY_NOTICES.md.
- [usbip-win2 0.9.8.1](https://github.com/vadimgrn/usbip-win2/releases/tag/v.0.9.8.1):
  separately installed driver and CLI contract.
