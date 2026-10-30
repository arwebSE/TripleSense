# Standalone app

DSShine handles the whole controller alongside stock Sunshine and Moonlight.
Install it on the Windows game PC and on the computer with the Bluetooth
DualSense. Moonlight continues to handle video, ordinary game audio, keyboard
and mouse. No paid virtual-controller driver or Sunshine fork is required.

## First setup

1. **Windows:** run `DSShine-Setup-0.4.1-Windows-x64.exe`. The installer includes
   the signed USB/IP driver, adds app-specific local-subnet firewall rules,
   and offers to disable Sunshine controller forwarding. It backs up the
   Sunshine setting and does not restart Windows or Sunshine automatically.
   Restart Sunshine after changing its controller setting.
2. **Mac:** open `DSShine-macOS.dmg` and drag DSShine into Applications,
   and open it. Allow local-network access if macOS asks. The current preview
   is locally signed, not Developer ID signed/notarized; a downloaded preview
   may require macOS's Open Anyway action once.
3. On Windows, **Server** is selected. Click **Pair client**, then **Generate code**.
4. On the Mac, **Client** is selected. Click **Pair server**, select the discovered
   server, enter the code shown on Windows and click **Pair and connect**. The code is
   needed once; identities are exchanged and stored automatically.
5. Pair the DualSense to the Mac over Bluetooth and turn it on. Exit Steam on
   the physical-controller computer. Stream an ordinary Desktop/game entry
   through Moonlight. The old CLI Sunshine preparation hooks are unnecessary.

The Windows installer offers to disable ordinary Sunshine controller
forwarding so games see one controller. If using the portable app or a Sunshine
installation in a different location, configure its controller setting once.
**Settings → Repair Windows setup** repairs a standard installation without a
terminal. DSShine does not hide the physical pad
from macOS. Moonlight may still use it for local UI navigation.

## Daily use

Open DSShine on both computers and turn on the controller. Paired computers
reconnect automatically. **Settings → Start DSShine when I log in** is enabled on first
launch and can be disabled in the app. Closing the window leaves it in the
tray/menu bar; **Quit DSShine**
releases effects and removes its owned virtual controller.

Disconnect works independently of the video stream. A network loss releases
controller effects; the app reconnects and recreates its virtual controller.
Some games need to be restarted after a controller is recreated.

## Controller audio

Input, ordinary vibration and adaptive triggers use the previously validated
controller backend. **Controller audio is on by default.** Its compact switch
controls the controller speaker/microphone and detailed audio haptics.
Mac Bluetooth audio still has measured stalls and dropouts, and this
setting does not imply clean audio or game-specific haptic compatibility.

Disconnect before changing audio. During a connection the switch is read-only;
clicking it explains that a disconnect is needed, without restarting the session.
Audio status reports Bluetooth output stalls instead of claiming audio is healthy.

With this option off, the app does not arm the microphone or send Bluetooth
audio packets. Ordinary game sound still plays through Moonlight.

## Pairing and networking

DSShine discovers both DSShine and Sunshine advertisements on the LAN. A
Sunshine-only advertisement is labelled with a reminder to open DSShine there.
The Windows app listens for the controller connection; the Mac makes outgoing
connections, so it needs no incoming firewall exception or SSH login.

The eight-digit pairing code uses SPAKE2 password-authenticated key exchange,
with authenticated encryption and key confirmation for the credential transfer.
Pairing allows at most five attempts, expires after two minutes, and enrols one
controller computer per code. Subsequent connections use mutual TLS 1.3.
Moonlight's private keys, pairing records and live session keys are not read.
The underlying USB/IP listener is bound only to Windows loopback.

The normal connection uses TCP 3250. The pairing listener uses TCP 3251 only
while a code is active; discovery uses mDNS and UDP 3252 broadcast.
Installer firewall exceptions are
restricted to the DSShine executable, the local subnet on Private and Public networks.
Both computers must be reachable on the same LAN. Router client isolation,
multicast/broadcast filtering can prevent discovery or connection. Use
**Refresh** on the Client pairing screen to retry. **Enter address** offers a
manual address field without replacing the discovered-server list.
Paired PCs track IP changes through discovery while retaining their TLS identity.

Identities expire after a year; pair again to renew them. App data is stored
under `%LOCALAPPDATA%/DSShine` on Windows and
`~/Library/Application Support/DSShine` on macOS. Do not share identity files.
Logs contain connection diagnostics, not microphone recordings.

## If setup needs attention

- **No server found:** click **Refresh** on the Client pairing screen. Make sure
  DSShine is open on Windows. On the Mac, use **Settings → Network permissions**
  and allow DSShine.
- **Windows refuses a connection:** click **Settings → Repair Windows setup**
  and accept its administrator prompt. This repairs the driver and local-subnet
  firewall rules and configures Sunshine forwarding.
- **Controller asleep:** press PS. DSShine waits for it and reconnects.
- **Steam owns the controller:** close Steam on the Mac. Steam can remain open
  on the Windows game PC.
- **Update:** use **Settings → Downloads and updates**, quit DSShine, and run the newer
  Windows installer or replace the Mac app in Applications. Pairing is kept.

Opening DSShine again brings its existing window forward instead of starting a
competing controller instance.

## Interface

**Change mode** opens explicit **Server** and **Client** choices and remains
available while connected. Selecting another mode stops the current session
and saves the new mode. Server runs on
the Windows Sunshine PC; Client runs beside the controller. The connection view
shows status, the paired computer, controller audio on the Client, and the main
connection action. **Stop server** stops accepting the controller; **Disconnect**
disconnects the Client. Neither action stops the Moonlight video stream.

Pairing has its own screen. Discovered servers are listed by name and address;
there is no dropdown. Settings and Logs open in separate windows. The connection
and pairing screens do not scroll; only the server list and log contents can scroll.
Those scrollbars use the platform's native widget style.

## Building

Build on the target platform with Python 3.11+:

```text
python -m pip install -e ".[controller,app,build]"
python tools/build_app.py
```

On Windows, first run `scripts/Install-HostDriver.ps1` without `-Install` to
download and verify the pinned driver installer. Install Inno Setup 6 and use
`python tools/build_app.py --installer` to create the setup executable. Neither
Python nor Inno Setup is needed on users' computers.

The app bundle includes dependency licenses. Shared Qt libraries remain
replaceable. Developer ID signing and notarization require release credentials
and are not simulated by the build. GitHub Actions builds downloadable desktop
artifacts with the **Build desktop app** workflow.
