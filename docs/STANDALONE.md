# Standalone app

DSShine forwards a whole DualSense between computers independently of streaming software.
Install it on the Windows game PC and on the computer with the Bluetooth
DualSense. Your streaming app handles video, ordinary game audio, keyboard
and mouse separately. No streaming app or paid controller driver is required.
The packaged apps include Python and their runtime libraries: users do not need
Python, Git, SSH or developer tools. Windows setup installs the included signed
USB/IP driver and needs administrator permission. The current packages target
Windows x64 and Apple Silicon Macs.

A Mac is optional: Windows can run Client as well as Server. macOS currently
runs Client only, with Server support planned. Mac-to-Windows is the combination
tested with a real controller; Windows-to-Windows still needs live validation.

## First setup

1. **Windows:** run `DSShine-Setup-0.4.13-Windows-x64.exe`. The installer includes
   the signed USB/IP driver and adds app-specific LAN and private-VPN firewall rules.
   It does not change your streaming software or restart Windows automatically.
2. **Mac:** open `DSShine-macOS.dmg` and drag DSShine into Applications,
   and open it. Allow local-network access if macOS asks. The current preview
   is locally signed, not Developer ID signed/notarized; a downloaded preview
   may require macOS's Open Anyway action once.
3. On Windows, choose **Server**. A four-digit pairing code appears automatically
   and copies to the clipboard.
4. On the Client, enter the Server address and its code, then click **Connect**.
   The Client finds LAN and Tailscale/NetBird servers automatically, or you can
   enter the Server address manually. Pairing is saved automatically.
5. Pair the DualSense to the Mac over Bluetooth and turn it on. Exit Steam on
   the physical-controller computer. Stream an ordinary Desktop/game entry
   through your preferred streaming app, if you use one.

Disable your streaming app's controller forwarding if it would expose a second
controller on the game PC. For example, with Sunshine/Moonlight, disable
Sunshine's controller forwarding in its configuration. DSShine does not change
that setting automatically. Other streaming software has not yet been validated.
**Settings → Repair Windows setup** repairs DSShine's driver and firewall rules
without a terminal. DSShine does not hide the physical controller from macOS;
a streaming client may still use it for local UI navigation.

## Daily use

Open DSShine on both computers and turn on the controller. Paired computers
reconnect automatically. **Settings → Start DSShine when I log in** is enabled on first
launch and can be disabled in the app. Closing the main window releases effects,
removes its owned virtual controller and quits DSShine. Minimize the window to
keep the controller connected. There is no tray or menu-bar icon.

Disconnect works independently of the video stream. A network loss releases
controller effects; the app reconnects and recreates its virtual controller.
Some games need to be restarted after a controller is recreated.

## Controller audio

Input, ordinary vibration and adaptive triggers use the previously validated
controller backend. **Controller audio is on by default.** Its compact switch
controls the controller speaker/microphone and detailed audio haptics.
Mac Bluetooth audio still has measured stalls and dropouts, and this
setting does not imply clean audio or game-specific haptic compatibility.

Disconnect before changing audio. During a connection the switch is disabled;
hover over it to see that a disconnect is needed.
Audio status reports Bluetooth output stalls instead of claiming audio is healthy.

With this option off, the app does not arm the microphone or send Bluetooth
audio packets. Ordinary game sound still plays through your streaming app.

## Pairing and networking

DSShine discovers its own servers on the LAN; no streaming app discovery or
pairing records are required.
The Windows app listens for the controller connection; the Mac makes outgoing
connections, so it needs no incoming firewall exception or SSH login.

New codes are copied to the Server clipboard automatically; **Copy code** copies
the displayed code again. Codes expire after two minutes and allow five attempts.

The four-digit pairing code uses SPAKE2 password-authenticated key exchange,
with authenticated encryption and key confirmation for the credential transfer.
Pairing allows at most five attempts, expires after two minutes, and enrols one
controller computer per code. Subsequent connections use mutual TLS 1.3.
Moonlight's private keys, pairing records and live session keys are not read.
The underlying USB/IP listener is bound only to Windows loopback.

The normal connection uses TCP 3250. The pairing listener uses TCP 3251 only
while a code is active; discovery uses mDNS and UDP 3252 broadcast.
Installer firewall exceptions restrict TCP access to the DSShine executable,
local subnets and `100.64.0.0/10`, used by Tailscale and default NetBird networks.
Discovery uses local broadcasts plus direct UDP queries to peers listed by the
installed Tailscale and NetBird apps. No router port forwarding is needed.
Custom VPN address ranges need a matching firewall rule.

Both computers must be reachable on the LAN or through your private VPN. VPN
access policies must allow the connection. While adding a server, discovery checks the LAN and known VPN peers every five
seconds. Discovery stops after pairing or leaving that screen and resumes only
when you return to add a server. Saved-server online/offline checks are separate.
The VPN app must be installed and signed in, with a policy allowing UDP 3252
and TCP 3250�3251 between the computers. If discovery is blocked, enter the
Server's VPN address directly. Click a Server IP address to copy it. Manual addresses are retained even
when LAN discovery finds another address for the same server. Tailscale controller
input and adaptive-trigger feedback have passed a live test; NetBird's firewall
peer discovery and firewall scope are covered, but live NetBird controller
forwarding remains unverified.

The Client saves paired servers with online/offline indicators. Select one and
click **Connect**; **Add server** pairs another, and **Remove** forgets the selected
server and its credentials. Disconnect before changing the selected server.

Identities expire after a year; pair again to renew them. App data is stored
under `%LOCALAPPDATA%/DSShine` on Windows and
`~/Library/Application Support/DSShine` on macOS. Do not share identity files.
Logs contain connection diagnostics, not microphone recordings.

## If setup needs attention

- **No server found:** wait for automatic discovery, or enter the Server address directly. Make sure
  DSShine is open on Windows. On the Mac, use **Settings → Network permissions**
  and allow DSShine.
- **Windows refuses a connection:** click **Settings → Repair Windows setup**
  and accept its administrator prompt. This repairs the driver and LAN/private-VPN
  firewall rules only.
- **Controller asleep:** press PS. DSShine waits for it and reconnects.
- **Steam owns the controller:** close Steam on the Mac. Steam can remain open
  on the Windows game PC.
- **Update:** use **Settings → Downloads and updates**, quit DSShine, and run the newer
  Windows installer or replace the Mac app in Applications. Pairing is kept.

Opening DSShine again brings its existing window forward instead of starting a
competing controller instance.

## Interface

**Change mode** on Windows opens explicit **Server** and **Client** choices.
Disconnect before changing modes; hover over the disabled
button for help. The macOS app is Client-only and has no mode selector.
Server runs on the Windows game PC; Client runs beside the controller.
macOS and Linux Server support is [planned](ROADMAP.md). The connection view
shows status, the paired computer, controller audio on the Client, and the main
connection action. **Disconnect** stops the controller connection on either computer. Neither action stops your streaming software.

Server pairing codes appear automatically in the main status card. The small
copy and refresh icons copy the current code or create another. Existing paired
clients can still reconnect while a code is displayed. Client pairing has its own
screen. Discovered servers are listed by name and address;
there is no dropdown. Settings and Logs open in separate windows. The connection
and pairing screens do not scroll; only the server list and log contents can scroll.
Those scrollbars use the platform's native widget style.

For building or contributing, see the [development guide](DEVELOPMENT.md).
