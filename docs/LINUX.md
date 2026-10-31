# Linux preview

This describes the unreleased 0.5.0 development build. The current 0.4.16
download does not include Linux support.

## Installation and use

The Debian/Ubuntu package includes the app, Python runtime, audio codecs and
desktop launcher. Open the `.deb` in your software installer and install it,
then open **TripleSense** from your applications. Package dependencies install
automatically; users do not need developer tools or terminal commands.

- Choose **Client** on the Linux computer beside your Bluetooth DualSense.
  Pair the controller in your desktop's Bluetooth settings, then choose or add
  the gaming computer in TripleSense and enter its four-digit code.
- Choose **Server** on the Linux gaming computer. Start the server, then use
  the displayed address and code on the Client. Authorize the system prompt
  when the controller connects; the app itself stays unprivileged.

The Server uses the distribution's `vhci_hcd` kernel module. No custom kernel
driver is built. The package grants controller and virtual-mouse access to the
active local desktop session. If installed while the controller was connected,
reconnect it before retrying.

LAN, Tailscale and NetBird use the same pairing and encrypted controller
connection. If a Linux firewall is enabled, allow TripleSense from your LAN
and trusted VPN peers: TCP 3250–3251 and UDP 3252. The package does not modify
your firewall. Its local USB/IP endpoint listens on loopback only.

## Touchpad mouse

Disconnect the Server, open **Settings**, enable **Use touchpad as mouse**, then
connect again. One finger moves the pointer; tap clicks; pressing the touchpad
holds the left button for dragging. Two fingers scroll or tap/click for right
click. Touchpad input is consumed while mouse mode is enabled; other controller
input continues to the game. Windows Servers have the same setting.

## What still needs testing

The ARM64 package has passed frozen-app launch, icon and codec checks on
Debian 12. Synthetic controller input and virtual-mouse output have passed
real Linux kernel tests. The available test VM has no USB audio drivers, so
Linux speaker/microphone enumeration and playback/capture still require a
normal Linux machine. Physical Linux Bluetooth audio, desktop permissions and
Wayland/X11 use need hardware acceptance. AMD64 packaging is configured but
has not been built locally. Physical USB controller forwarding is not available.

Do not treat this preview as validated Linux support until these checks pass.
