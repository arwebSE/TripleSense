# Bluetooth audio release blocker

Bluetooth speaker, microphone and detailed haptics remain required features.
The current Mac path has not passed continuous full-duplex acceptance. Do not
remove the preview audio limitation or describe the current release as complete.
Touchpad mouse control is deferred to a future update.

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
that passes both actual playback and sustained microphone capture. Previous
direct L2CAP probes returned a not-permitted status; a fresh IOBluetooth
connection-mode probe timed out during framework initialization. No connection
mode change was applied.

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
