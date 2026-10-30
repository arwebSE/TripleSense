# Relationship to ds5-virtual-cable

DSShine reuses the MIT-licensed DualSense USB emulator and Bluetooth protocol
implementation from [Macle57/ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable).
The exact vendored revision and local changes are recorded in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). This is not an independent
implementation of that engine or a new kernel driver.

Upstream focuses on using a Bluetooth DualSense as a virtual wired controller
on a Windows PC, with its own installed GUI, input shortcuts, microphone handling
and optional HidHide integration. DSShine adds a separate macOS controller client,
a paired authenticated network connection to a Windows server, discovery,
reconnection and desktop packaging for both endpoints. The Windows virtual bus
is still supplied by usbip-win2. Upstream improvements are not automatically
inherited by the pinned copy.

DSShine's controller link is independent of streaming software. Sunshine and
Moonlight are our current tested streaming setup, not runtime dependencies.
Other tools should be able to run alongside the virtual USB device, but need
separate validation; disable their controller forwarding where it creates duplicate
input. DSShine setup and repair do not configure streaming software.

The packaged apps include Python and runtime libraries. End users install no
Python, Git, SSH or build tools. Windows needs the included signed USB/IP driver
and administrator approval during setup; macOS needs Bluetooth/local-network
permissions. Current previews are Windows x64 and macOS Apple Silicon. Mac
Developer ID signing/notarization and continuous Bluetooth audio quality are
still outstanding release work.
