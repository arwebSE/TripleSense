# Planned platform support

TripleSense is a controller bridge between computers, independently of video-streaming
software. macOS is a supported Client platform, not a requirement. Windows Client
is implemented too; only Mac-to-Windows currently has live hardware acceptance
evidence in this project.

Next milestone: Linux and macOS Server support, including virtual DualSense HID
and audio devices. Linux Client support and USB controller connections are also
required for full platform coverage. Keep the existing Windows Server and Mac
Bluetooth audio path working while adding these backends.

Before expanding support claims, validate Windows-to-Windows input, feedback
and cleanup, and extended Bluetooth speaker/microphone/haptics audio sessions.

TripleSense currently creates the virtual DualSense on Windows using usbip-win2.
This is a limitation of TripleSense's current server backend, not Sunshine:
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
