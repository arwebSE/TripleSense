# Upstream code and scope

TripleSense uses the MIT-licensed DualSense USB emulator and Bluetooth engine from
[Macle57/ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable), pinned under
`vendor/`. The exact revision, local changes and required notices are in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

TripleSense's added layer connects separate computers: paired authentication,
LAN/VPN discovery, saved servers, reconnect/cleanup, desktop apps and updates.
It operates independently of streaming software. Sunshine/Moonlight is the tested
streaming combination, not a runtime dependency.

The Windows virtual USB bus is supplied by the separately installed, signed
usbip-win2 driver. Experimental Linux Server uses the existing kernel USB/IP host
controller. The native Mac Client transport adapts Bluetooth access to macOS;
macOS Server is still planned. See [platform and feature status](STATUS.md).

The controller protocol, USB device model and remote controller concept are not
new inventions of this project. Reusing the engine does not establish better
latency, haptics or reliability than upstream. Upstream changes are not inherited
automatically: our vendored revision and local adaptations must be maintained.

## Keeping the vendored files

The emulator, Bluetooth prototype package, inherited tests, descriptor reference
data and license/provenance documents remain relevant. They are runtime code or
regression fixtures, not old TripleSense setup instructions. Keep upstream notices
when changing or redistributing that subset. Omitted upstream GUI, drivers,
installer and native echo-canceller DLL are not supplied by TripleSense.
