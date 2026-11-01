# TripleSense user guide

Start with the [README](../README.md) for downloads and first pairing. This guide
covers daily use, permissions, networking, updates and troubleshooting. No Python,
SSH or terminal setup is needed for the desktop downloads.

## Client and Server

- **Client:** the computer connected to the physical Bluetooth DualSense.
- **Server:** the computer running the game and receiving a virtual DualSense.

Windows can run either role. The Apple Silicon Mac app runs Client only and hides
the mode selector. Linux ARM64 has experimental Client and Server support. See
[compatibility and current limits](STATUS.md).

Open both apps and turn on the controller. Saved pairings reconnect without a new
code; select a saved Server and click **Connect** if needed. **Add server** pairs
another computer; **Remove** forgets the selected Server. Disconnect before
changing modes, selecting another Server or changing controller audio.

Closing the window quits the app and disconnects the controller. Minimize it to
keep playing. There is no tray or menu-bar icon. Automatic launch at login can be
changed in Settings.

## Pairing

Start the Server to show its four-digit code. On the Client, choose a discovered
Server or enter its address, enter the code and connect. The Client discovers
servers automatically while adding one; discovery stops after pairing or leaving
that screen. Saved-server online/offline checks are separate.

Click a Server address to copy it. New codes copy automatically; the copy icon
copies the current code, and the refresh icon generates a new one. Codes expire
after two minutes, allow five attempts and renew automatically while waiting.
Automatic renewal leaves the clipboard and existing pairings alone.

If a saved pairing is rejected, disconnect and pair that Server again. Pairing
identities expire after a year. A temporary pairing-code expiry does not revoke
an existing pairing.

## LAN, Tailscale and NetBird

Both computers need to reach each other on the same LAN or through your own
private VPN. Install and sign into the VPN on both computers. Discovery can query
known Tailscale/NetBird peers; if it finds nothing, enter the Server's VPN address.
A manually selected VPN address is retained when LAN discovery finds the same PC.

The Server receives TCP **3250** for the controller and TCP **3251** for pairing.
Discovery uses UDP **3252** and mDNS **5353**. VPN access policies must allow the
connection. No router port forwarding is needed.

Windows setup creates app-specific firewall rules for local subnets and
`100.64.0.0/10`, covering Tailscale and default NetBird address ranges, on Private
and Public network profiles. Custom VPN ranges need matching firewall rules.
Use **Settings → Windows setup → Repair** to restore the included driver and rules.

Linux packaging does not change your firewall. Permit the same ports from your
LAN and trusted VPN peers. Tailscale input and trigger feedback have passed live
testing; NetBird still needs a full live controller test.

## Permissions and installation

**Windows:** use the x64 installer and accept its administrator prompt. It includes
the signed USB/IP driver. Setup and repair do not configure streaming software.

**macOS:** open the DMG and drag TripleSense into Applications. Allow Bluetooth
and local-network access when prompted. The preview is locally signed, not
notarized; downloaded copies may need Apple's
[Open Anyway](https://support.apple.com/en-gb/102445) action once.

**Linux, experimental:** install the ARM64 Debian/Ubuntu `.deb` using your package
manager. Dependencies, a desktop launcher and active-session controller/mouse
permissions are included. Reconnect a controller that was already connected
during installation. Server mode uses the distribution's `vhci_hcd` module and
asks for administrator authorization through Polkit when attaching the controller;
the app stays unprivileged. A kernel with USB/IP and USB audio support is needed.
No Linux x64 download is currently published.

## Audio and streaming software

Controller audio is on by default. It carries the controller speaker, microphone
and audio-driven haptics, separately from the streaming app's normal sound. Your
game or OS may need to select the virtual controller's audio device. Support for
these effects also depends on the game.

Disconnect before toggling **Controller audio**. With it off, TripleSense does not
arm the microphone or send Bluetooth audio packets. Input, ordinary rumble and
adaptive triggers stay available. Sustained mixed audio/haptics still needs
validation; successful short signal tests do not establish continuous quality.

Disable your streaming app's controller forwarding if it creates duplicate
input. TripleSense does not change that setting. Close Steam on the Client if it
owns the physical controller; Steam can remain open on a separate Server. For a
game's native DualSense support, its Steam Input setting may also matter.

## Experimental touchpad mouse

On a Windows or Linux Server, disconnect and enable **Use touchpad as mouse** in
Settings, then reconnect. Intended gestures are one-finger motion, tap to click,
press to drag, and two-finger scrolling/right click. Touchpad input is consumed
while enabled; other controller input is still forwarded to the game.

The live Mac-to-Windows cursor test remains unresolved. Treat this option as
experimental, not a reliable replacement for a mouse. Controller shortcuts and
opening the OS on-screen keyboard are still planned.

## Updates

From version 0.5.1, both roles check GitHub's latest stable release on startup.
Open **Update available**, download it, then choose **Install and restart**.
**Settings → App updates → Check** checks manually; automatic checks can be disabled.
Installation disconnects the controller, keeps settings/pairings and reopens the
app. Normal administrator authorization may be required.

Versions before 0.5.1 need one manual update: quit the app and run the Windows
installer or replace the Mac app. Linux updates use the system package installer.
Updates do not automatically install prereleases or downgrade development builds.

In-app updates use publicly accessible GitHub releases without a login.
Private-repository releases cannot be checked or downloaded in the app.
Downloads must match the release asset's published SHA-256 digest before installation.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| No Server found | Enter its LAN/VPN address manually. Check that the Server is running, network permissions are allowed and VPN policies permit communication. |
| Connection refused on Windows | Use **Settings → Windows setup → Repair** and accept the administrator prompt. |
| Controller unavailable | Press PS and confirm Bluetooth is connected. Close other software using the physical controller, particularly Steam on the Client. |
| Duplicate input | Disable the streaming app's controller forwarding. |
| Audio stalls | Disconnect and disable **Controller audio** to isolate input. Continuous audio remains preview functionality. |
| Saved pairing rejected | Disconnect and pair that Server again. An expired display code alone does not invalidate saved pairing. |
| Game misses a recreated controller | Restart the game after reconnecting. |
| Update fails | Check internet access, release availability and OS authorization. The helper attempts to reopen the installed app; details are in `update-install.log`. |

Open **Logs** for connection diagnostics. Logs do not contain microphone recordings.
Private app data is stored in `%LOCALAPPDATA%/TripleSense` on Windows,
`~/Library/Application Support/TripleSense` on macOS and
`~/.local/share/TripleSense` on Linux (or your `XDG_DATA_HOME`). Do not share identity files or private keys.

TripleSense uses its own installation, app data and pairing identities. It does
not import settings or pairings from earlier differently named applications.
