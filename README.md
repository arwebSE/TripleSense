# DSShine

Use a DualSense connected to your Mac with games on your Windows PC.
DSShine carries the controller connection independently of your streaming software.
It uses the free signed USB/IP driver and does not require a streaming app or fork.

## Install

- **Windows:** run the DSShine installer. It includes the controller driver and
  configures local-network access. It does not change your streaming software.
- **Mac:** open the DSShine disk image and drag the app into Applications.
  Open it and allow local-network access when macOS asks.
- In the Windows **Server** app, click **Pair client**, then **Generate code**.
  In the Mac **Client** app, click **Pair server**, select the server and enter
  the code. Turn on your Bluetooth DualSense.

After pairing, DSShine reconnects automatically and opens at login. Closing its
window disconnects the controller and quits the app. Minimize it to keep it
running. Use your preferred streaming app for video and ordinary game sound;
disable its controller forwarding if it creates duplicate input. No terminal,
SSH, Python or certificate setup is required.

[Setup and troubleshooting](docs/STANDALONE.md) ·
[Downloads](https://github.com/arwebSE/DSShine/releases)

## Current status

**Development preview.** The installed Windows/Mac apps have passed live pairing,
native DualSense enumeration, input and adaptive-trigger feedback/release checks.
Vibration and touchpad input were confirmed in the earlier browser test.

Controller speaker, microphone and full audio-driven haptics are requirements.
Their transport exists, but Mac Bluetooth audio currently stalls and drops out;
it is not a completed feature. The app exposes the audio switch and reports
streaming stalls. Controller audio is on by default and can be switched off.

The Mac preview is locally signed and not Apple notarized. macOS may require
Open Anyway for a downloaded build. No game-specific or long-session quality
claim is made. See [validation evidence](docs/VALIDATION.md).

## Development

[Upstream comparison](docs/UPSTREAM.md) · [Architecture](docs/ARCHITECTURE.md) · [Developer tools and CLI](docs/DEVELOPMENT.md)
· [Planned platform support](docs/ROADMAP.md)

The bridge builds on the MIT-licensed
[ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable), pinned under
`vendor/`, and [usbip-win2](https://github.com/vadimgrn/usbip-win2).
Dependency and distribution licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
