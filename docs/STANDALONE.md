# Standalone app

DSShine handles the whole controller alongside stock Sunshine and Moonlight.
Install it on the Windows game PC and on the computer with the Bluetooth
DualSense. Moonlight continues to handle video, ordinary game audio, keyboard
and mouse. No paid virtual-controller driver or Sunshine fork is required.

## First setup

1. **Windows:** run `DSShine-Setup-0.2.0-Windows-x64.exe`. The installer includes
   the signed USB/IP driver, adds app-specific Private-network firewall rules,
   and offers to disable Sunshine controller forwarding. It backs up the
   Sunshine setting and does not restart Windows or Sunshine automatically.
   Restart Sunshine after changing its controller setting.
2. **Mac:** unzip `DSShine-macOS.zip`, move `DSShine.app` into Applications,
   and open it. Allow local-network access if macOS asks. The current preview
   is locally signed, not Developer ID signed/notarized; a downloaded preview
   may require macOS's Open Anyway action once.
3. On Windows, select **Game PC** and click **Pair a controller computer**.
4. On the Mac, select **Controller PC**, choose the discovered game PC, and
   click **Pair with this PC**. Enter the code shown on Windows. The code is
   needed once; identities are exchanged and stored automatically.
5. Pair the DualSense to the Mac over Bluetooth and turn it on. Exit Steam on
   the physical-controller computer. Stream an ordinary Desktop/game entry
   through Moonlight. The old CLI Sunshine preparation hooks are unnecessary.

The Windows installer offers to disable ordinary Sunshine controller
forwarding so games see one controller. If using the portable app or a Sunshine
installation in a different location, use **Open Sunshine controller settings**
and switch controller input off once. DSShine does not hide the physical pad
from macOS. Moonlight may still use it for local UI navigation.

## Daily use

Open DSShine on both computers and turn on the controller. Paired computers
reconnect automatically. Enable **Open DSShine when I log in** to avoid opening
it manually. Closing the window leaves it in the tray/menu bar; **Quit DSShine**
releases effects and removes its owned virtual controller.

Disconnect works independently of the video stream. A network loss releases
controller effects; the app reconnects and recreates its virtual controller.
Some games need to be restarted after a controller is recreated.

## Controller audio

Input, ordinary vibration and adaptive triggers use the previously validated
controller backend. **Experimental controller audio is off by default.** Enable
it before connecting to try controller speaker/microphone and detailed audio
haptics. Mac Bluetooth audio still has measured stalls and dropouts, and this
setting does not imply clean audio or game-specific haptic compatibility.

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
while a code is active; discovery uses mDNS. Installer firewall exceptions are
restricted to the DSShine executable, Private networks and the local subnet.
Both computers must be reachable on the same LAN. Router client isolation,
multicast filtering or a Public Windows network profile can prevent discovery
or connection; entering the game PC's LAN address bypasses discovery only.

Identities expire after a year; pair again to renew them. App data is stored
under `%LOCALAPPDATA%/DSShine` on Windows and
`~/Library/Application Support/DSShine` on macOS. Do not share identity files.
Logs contain connection diagnostics, not microphone recordings.

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
