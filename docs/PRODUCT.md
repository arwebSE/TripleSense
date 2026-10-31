# Product target

TripleSense is an open-source DualSense connection between computers. The computer
beside the controller runs Client; the gaming computer runs Server. It works
independently of the video-streaming app. A Mac is optional.

## Required platform and controller coverage

The target is Windows, macOS and Linux in **both** Client and Server roles,
with physical DualSense connections over **Bluetooth and USB**. Do not label
a combination supported until it has a working backend and hardware acceptance.

Release 0.5.1: Windows Server; Windows/macOS Client with Bluetooth, plus experimental Linux Client/Server.
Mac-to-Windows has live hardware evidence. Windows-to-Windows still needs live
acceptance. Version 0.5.1 includes Linux Client packaging and a Linux Server
backend using the existing kernel USB/IP host controller. Virtual gamepad input
has passed a real Linux kernel test; Linux audio and physical Bluetooth still
need hardware acceptance. Physical USB forwarding remains unimplemented.
macOS Server needs an Apple-approved virtual-device backend, including audio;
see [platform work and evidence](PLATFORM_WORK.md).

## Required controller features

- Buttons, sticks, touchpad, battery and motion sensors (gyro/accelerometer).
- Adaptive triggers, ordinary rumble and detailed audio-driven haptics.
- Controller microphone and speaker, including continuous full-duplex operation.
- Pairing, saved servers, online/offline status, reconnection and forgetting servers.
- LAN and private VPN connections, including Tailscale and NetBird. VPN access
  retains paired authentication; discovery must not silently replace a VPN address.

The native Mac Bluetooth audio path has passed live speaker and microphone
signal tests. Extended mixed haptics/audio sessions still need validation.
Current measurements and failed approaches are recorded in
[the Bluetooth audio investigation](BLUETOOTH_AUDIO.md).

## Optional couch controls

Configurable controller combinations should open a controller menu, open the
system's on-screen keyboard, or toggle touchpad mouse/gesture control. Use the
OS/desktop keyboard rather than creating a custom one. Touchpad movement and
clicks should operate it. Linux launch adapters depend on the desktop environment.

Mouse mode should support pointer movement, clicking and gestures such as
two-finger scrolling. Consume menu/keyboard/mouse-mode combinations before
forwarding input to games; closing a menu restores normal controller input.
Version 0.5.1 includes experimental opt-in touchpad mouse output on Windows and Linux
Servers: pointer movement, tap/click, dragging, right click and two-finger
scrolling. Menu/keyboard shortcuts and macOS pointer output remain planned.

## Release priorities

Finish the current pairing/VPN/error-state and saved-server flow, validate actual
controller traffic over each VPN, then close the functional audio and platform
gaps. Add couch controls using native platform adapters. Published support claims
must distinguish implemented paths, hardware-tested paths and planned work.
