# macOS Moonlight client -> Windows Sunshine host

Target topology: standard DualSense paired to the Mac over Bluetooth, Moonlight
on the Mac, Sunshine plus the virtual USB driver on Windows. The Mac runs the
`source` companion; the Windows gaming PC runs `host`. The controller tunnel
includes HID, speaker/haptic audio, and microphone traffic. Moonlight continues
to carry normal game video/audio.

The Mac source is currently being hardware-validated. Windows local results do
not establish macOS controller access or two-computer audio quality.

## Mac

Use a local project directory, outside cloud-synced folders, and Python 3.11+:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[controller]'
.venv/bin/ds5driver doctor
.venv/bin/ds5driver devices
.venv/bin/ds5driver probe --seconds 3
.venv/bin/ds5driver pair --out .credentials/pair
.venv/bin/ds5driver source --credentials .credentials/pair/source --bind 0.0.0.0 --serial SERIAL_FROM_DEVICES
```

The `python3` interpreter must be 3.11 or newer; the Xcode-provided 3.9 is too
old. Use an existing newer interpreter's full path when creating the venv.
The Mac needs no USB/IP driver. Device transport is detected using HIDAPI's
`bus_type`, since macOS paths are opaque IOKit identifiers.

Exit Steam on the Mac before starting the source. Start the source before
Moonlight so the companion can open the physical controller first. HIDAPI's
macOS backend uses exclusive access by default; interaction with Moonlight and
macOS controller shortcuts still needs a live coexistence test. If macOS shows
an access prompt, allow the process used to run the companion; do not change
system protections. Bind port 3250 only on a trusted LAN and allow the Windows
host to reach it if the Mac's application firewall prompts.

## Windows

Securely transfer only `.credentials/pair/host/` from the Mac to the Windows
project's private credentials directory. Do not send either private key through
chat or sync credential folders to cloud storage.

```powershell
.venv/Scripts/ds5driver.exe host --credentials .credentials/pair/host --source MAC_IP --attach
```

The signed usbip-win2 driver is installed only on Windows. The Mac's IP must be
in the same reachable LAN (or an appropriate private tunnel); no internet-facing
USB/IP endpoint is needed. See [Sunshine hooks](SUNSHINE.md) to automate Windows
attachment around application launch. In Sunshine, disable ordinary forwarded
controller input to avoid creating a second DS4/Xbox pad.

Steam can run on Windows. For native DualSense game tests, disable Steam Input
for the game. The game's microphone selection is the virtual DualSense capture
endpoint on Windows. Games can send controller-speaker audio to its virtual
render endpoint; this does not replace the normal Moonlight audio output on
the Mac.

## Acceptance

Require real Mac Bluetooth input/feature reads; Windows enumeration/input;
adaptive-trigger mode readback; speaker/microphone signal checks; cleanup;
then a Moonlight session with source access maintained. LAN latency, long audio
stability, game haptics and sleep/reconnect behavior remain separate gates.
