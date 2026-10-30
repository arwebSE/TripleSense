# DSShine

Use a DualSense on your Mac with games on your Windows Sunshine PC.
DSShine carries the controller connection; Moonlight carries the game stream.
It uses the free signed USB/IP driver, with no paid Sunshine driver or fork.

## Install

- **Windows:** run the DSShine installer. It includes the controller driver,
  configures local-network access and offers to configure Sunshine.
- **Mac:** open the DSShine disk image and drag the app into Applications.
  Open it and allow local-network access when macOS asks.
- In the Windows **Server** app, click **Pair client**, then **Generate code**.
  In the Mac **Client** app, click **Pair server**, select the server and enter
  the code. Turn on your Bluetooth DualSense.

After pairing, DSShine reconnects automatically and opens at login. Closing its
window disconnects the controller and quits the app. Minimize it to keep it running. Use your normal Moonlight
Desktop or game entry. No terminal, SSH, Python or certificate setup is required.

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

[Architecture](docs/ARCHITECTURE.md) · [Developer tools and CLI](docs/DEVELOPMENT.md)
· [Planned platform support](docs/ROADMAP.md)

The bridge builds on the MIT-licensed
[ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable), pinned under
`vendor/`, and [usbip-win2](https://github.com/vadimgrn/usbip-win2).
Dependency and distribution licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
