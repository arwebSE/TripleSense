# Planned platform support

DSShine is a controller bridge between computers, independently of video-streaming
software. macOS is a supported Client platform, not a requirement. Windows Client
is implemented too; only Mac-to-Windows currently has live hardware acceptance
evidence in this project.

Before claiming a broadly useful release, validate Windows-to-Windows input,
feedback and cleanup, and fix continuous Bluetooth speaker/microphone/haptics
audio. These are functional release requirements alongside simple installation.

DSShine currently creates the virtual DualSense on Windows using usbip-win2.
This is a limitation of DSShine's current server backend, not Sunshine:
Sunshine itself supports Windows, macOS and Linux.

Future work: add macOS and Linux server backends that expose a native virtual
DualSense, including HID input/output, adaptive triggers and the speaker,
microphone and audio-haptics interfaces. Implement and validate each platform's
virtual-device path before enabling its Server interface.

The current macOS app is Client-only and has no mode selector. Windows can
change between Server and Client after disconnecting/stopping its active session.

For public Mac distribution, add Developer ID signing and Apple notarization
to the release process. Current preview bundles use local ad-hoc signatures,
so downloaded copies can require a Gatekeeper override on another Mac.
