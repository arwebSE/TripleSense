# Bluetooth audio validation

Bluetooth speaker, microphone and detailed haptics remain required features.
The native Mac path has passed short installed-app speaker/microphone checks.
Keep preview status until broader hardware and sustained mixed haptics testing
are complete.
Touchpad mouse control is deferred to a future update.

## Owned-channel breakthrough

Opening the Bluetooth HID channels ourselves after releasing this controller's
system HID profile bypasses the slow IOHID output path. The working prototype
retains the actual `CBL2CAPChannel` objects from `CBClassicPeer` callbacks; it does
not use the legacy wrapper that disposes of them before asynchronous open
completion. This uses private macOS APIs, guarded at runtime, and needs Bluetooth
permission. It does not change pairing, firmware, or system protections.

The first ten-second trial sent 470 full-size audio packets with zero late writes
and decoded 1,000 complete microphone frames, with valid input CRCs and no
framing loss. A follow-up through the app's Python IPC adapter sent 470 reports
in 10.030 seconds, with zero late writes (maximum 11.950 ms); calibration,
firmware and identity feature reads also succeeded. Counts include startup and
shutdown traffic and are not an exact microphone oscillator-rate measurement.
The user subsequently confirmed clear, quiet speaker-tone playback through this
adapter. This is stronger evidence than a successful host write alone.

The native helper is bundled in the installed 0.4.15 Mac application. Through
the real Windows virtual audio device, the test tone rose 28 dB above baseline
at the controller microphone, capture returned nonzero audio with zero capture
overflows, and a separate ten-second run returned 480,000 samples with no capture
overflows. One 10 ms block was all zero; that alone does not establish its cause.
No microphone recording was saved. The user confirmed saved-pair reconnection
after updating both installed apps and restoring the matching server identity.
Longer sustained mixed haptics/audio and broader OS/hardware validation remain.

## Measurements on 2026-10-30

The DualSense was connected to the Mac over Bluetooth. The normal DSShine app
was stopped for local tests; no network or virtual USB driver was involved.
Microphone PCM was processed in memory and discarded. Only counts, timings and
signal levels were retained.

| Local output trial | Result | Required rate |
| --- | --- | --- |
| Native asynchronous 547-byte reports, four in flight | 80 completed in 8 seconds; mean completion latency 379 ms | 46.875 reports/s |
| Smaller 142-byte speaker packets, 32 kbps Opus | 34.51 reports/s | 46.875 reports/s |
| 206-byte packets carrying two haptic frames | 22.44 reports/s | 46.875 reports/s |
| 270-byte packets carrying speaker and haptic frames | 16.59 reports/s | 46.875 reports/s |
| Native asynchronous 142-byte packets | 140 completed in 4.246 seconds | 140 in about 2.99 seconds |
| Native asynchronous 206-byte packets | 140 completed in 6.359 seconds | 140 in about 2.99 seconds |

The smaller-packet trials used valid report lengths, output checksums and silent
audio. Successful writes establish host transport timings, not audible playback
or compatible controller decoding.

An experimental 78-byte format with 24 kbps Opus reached 46.83 writes/s with no
write exceeding its 21.33 ms period. Its quiet speaker-tone test failed: measured
tone-band power during playback was close to the following silent period. This
format must not be used as a working fallback. The microphone decoder produced
480-sample frames, with 347 frames received over approximately eight seconds.

The throughput gap exists below the network/USB bridge. Larger jitter buffers,
thread priority and merely queueing more native writes have not resolved it.
The next requirement is a Mac Bluetooth transport or connection-policy change
that passes both actual playback and sustained microphone capture.

## Native transport follow-up

The original L2CAP error was decoded incorrectly: `0xe00002bc` means a general
IOKit error, not permission denied. With Bluetooth permission confirmed
(`CBManager.authorization == 3`), the direct HID-channel open still fails. The
macOS Bluetooth log gives the specific reason: `CBInternalErrorDomain` code 24,
`L2CAP PSM already connected`. Neither the legacy nor modern peer object exposes
an open channel to this process. Registered channel-open notifications also
received no event during a physical controller reconnect. This establishes a
failure to share the existing HID channel, not that all native transports are
unavailable.

The same reconnect log identifies a separate lead: macOS applies a 15 ms sniff
interval to this DualSense (`ModeChange`, mode 2, interval 24 Bluetooth slots).
Changing the HID registry's `ReportInterval` from 8000 to 1000 did not improve
547-byte write throughput; the original value was restored. That registry
property must not be confused with the Bluetooth connection interval.

The legacy `BluetoothHCIRequestCreate`, `BluetoothHCISendRawCommand` and
`BluetoothHCISendRawACLData` entry points on this Mac are no-op stubs: their first
instructions are `mov w0, #0; ret` (`00008052c0035fd6`). A zero status from these
functions does **not** establish that an HCI command was submitted or that the
connection mode changed. A targeted Exit Sniff trial through that API showed no
mode-change event and achieved only 11.205 audio reports/s. Do not build a
connection-policy workaround on these entry points.

Starting Apple's `GCDeviceHaptics` / `CHHapticEngine` on the connected controller
and playing a very low-intensity continuous pattern also failed to lift the
limit: 10.927 reports/s for the normal 547-byte audio report. The engine and
pattern were stopped after the measurement. Keeping an otherwise unused Apple
haptics engine alive is not a verified workaround.

## Reproduce the current path

Stop DSShine on the controller computer, connect the controller over Bluetooth,
and use the developer environment:

```sh
python tools/profile_bt_audio.py --microphone --seconds 3 --out captures/bt-audio-capacity.json
```

This sends silence, drains input and saves scalar diagnostics. It attempts to
turn the microphone off on exit. A zero exit status means the API calls finished;
compare achieved and required rates before judging continuity. Reopen DSShine
after testing.

Acceptance still requires sustained speaker and microphone signal across the
real Mac-to-Windows bridge, simultaneous haptics and controls, and reconnect and
shutdown checks. USB audio and Windows Bluetooth require their own validation.
