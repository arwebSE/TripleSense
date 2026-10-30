# Planned platform support

DSShine currently creates the virtual DualSense on Windows using usbip-win2.
This is a limitation of DSShine's current server backend, not Sunshine:
Sunshine itself supports Windows, macOS and Linux.

Future work: add macOS and Linux server backends that expose a native virtual
DualSense, including HID input/output, adaptive triggers and the speaker,
microphone and audio-haptics interfaces. Implement and validate each platform's
virtual-device path before enabling its Server interface.

The current macOS app is Client-only and has no mode selector. Windows can
change between Server and Client after disconnecting/stopping its active session.
