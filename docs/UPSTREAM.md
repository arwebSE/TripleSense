# Relationship to ds5-virtual-cable

TripleSense reuses the MIT-licensed DualSense USB emulator and Bluetooth protocol
implementation from [Macle57/ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable).
The exact vendored revision and local changes are recorded in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). This is not an independent
implementation of that engine or a new kernel driver.

Upstream focuses on using a Bluetooth DualSense as a virtual wired controller
on a Windows PC, with its own installed GUI, input shortcuts, microphone handling
and optional HidHide integration. TripleSense adds Windows/macOS controller clients,
a paired authenticated network connection to a Windows server, discovery,
reconnection and desktop packaging for both endpoints. The Windows virtual bus
is still supplied by usbip-win2. Upstream improvements are not automatically
inherited by the pinned copy.

TripleSense's controller link is independent of streaming software. Sunshine and
Moonlight are our current tested streaming setup, not runtime dependencies.
Other tools should be able to run alongside the virtual USB device, but need
separate validation; disable their controller forwarding where it creates duplicate
input. TripleSense setup and repair do not configure streaming software.

The packaged apps include Python and runtime libraries. End users install no
Python, Git, SSH or build tools. Windows needs the included signed USB/IP driver
and administrator approval during setup; macOS needs Bluetooth/local-network
permissions. Current previews are Windows x64 and macOS Apple Silicon. Mac
Developer ID signing/notarization and continuous Bluetooth audio quality are
still outstanding release work.

## What TripleSense is for

TripleSense is a controller-only connection between computers. A Mac is an optional
client platform, not a product requirement. The game-side Server currently
requires Windows; macOS and Linux Server backends are planned. Windows Client
support is implemented, but only Mac-to-Windows has had live controller acceptance
testing in this project so far.

The intended benefit is using a Bluetooth DualSense beside you while games run
elsewhere, independently of the video-streaming application. For a controller
already connected to the gaming PC, upstream's local bridge already addresses
that use case. TripleSense does not establish a new controller protocol, a new kernel
driver, better latency, or better haptics than upstream. Much of the recent work
has been installation, pairing, UI and safe cleanup. Continuous Bluetooth audio
is still failing acceptance, so full-fidelity remote use remains unfinished.

## Related tools

Remote controller forwarding is not a new idea. These projects overlap with it:

| Tool | Documented focus | Relationship to TripleSense |
| --- | --- | --- |
| [ds5-virtual-cable](https://github.com/Macle57/ds5-virtual-cable) | Bluetooth DualSense to virtual USB on Windows, with its own GUI | Supplies our controller engine; our added layer connects separate computers |
| [DualSense Client](https://dualsenseclient.github.io/DualSenseClient/) | Controller management on Windows/Linux and virtual controllers on Windows | Covers local controller customization and emulation; its documented feature list is not a paired controller-to-gaming-PC bridge |
| [VirtualHere](https://www.virtualhere.com/usb_server_software) | Share USB devices over a network | Already solves generic USB forwarding; TripleSense focuses on synthesizing a USB DualSense from a Bluetooth controller on the client |
| [Parsec](https://support.parsec.app/hc/en-us/articles/32381705301908-Setup-Gamepad) | Controller forwarding integrated with its streaming app; full DualSense support documented for USB on a Windows client | Already provides another remote DualSense path; TripleSense aims to work independently of the streaming app, including Bluetooth clients |

Those are scope comparisons from the linked documentation, not performance or
reliability comparisons. A useful TripleSense release must prove reliable input,
feedback and audio across its supported client/server combinations.
