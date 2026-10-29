# Validation record

Initial local development: 2026-10-29, Windows x64, Sunshine 2026.914.233613,
standard DualSense over Bluetooth.

| Gate | Evidence / status |
| --- | --- |
| Real detection | One standard DualSense enumerated through hidapi |
| Input / features | 1,348 extended reports in 3.008 s (448.2/s); calibration 41 B, pairing 20 B, firmware 64 B |
| Real input through TLS / USB-IP | 250 reports in 0.998 s; 250/250 matched except generated USB sequence counter |
| Features through TLS | 0x05 / 0x09 / 0x20 returned expected 41 / 20 / 64 B |
| New tests | 12 passed: identity/input, trigger bytes, exact four-channel PCM, importer release, idle USB, certificate rejection, port ownership and Sunshine export |
| Inherited tests | 331 run, 39 skipped (292 executed); skips concern omitted native echo-canceller DLL |
| Driver installer | 0.9.8.1 matched GitHub SHA-256; Authenticode Valid; installed locally; installer requested reboot, not performed |
| Windows HID / audio enumeration | Passed: 100 valid Windows HID reads, one native Sony HID, render + capture audio endpoints, owned virtual device removed after detach |
| Sunshine app commands | Live `session start` / `stop` passed: driver attached, ownership serial verified, port removed; exported commands not yet launched by Sunshine itself |
| Physical trigger mode | Passed: low-strength feedback sent through Windows HID and TLS; physical controller returned mode bits 0x11, then 0 after release |
| Windows four-channel audio | Passed: 192,000 silent PCM bytes traversed the Windows audio class driver to the Bluetooth backend |
| Physical audio haptic fidelity | Pending: silent PCM does not verify waveform fidelity or subjective feel |
| Two-PC game session | Pending second client and a representative game |

Hardware evidence remains under ignored `captures/` because it may contain
device identifiers. These measurements are distinct from upstream claims.

Driver installation requested a Windows restart. Local enumeration/input/PCM
tests passed before that restart, but post-restart verification remains required.
No automatic restart, Secure Boot change or test-signing change was performed.

## Acceptance procedure

1. Run `tools/verify_windows.py` with the verified driver installed. Require one
   new 054C:0CE6 HID, 100 valid Windows HID reads, render/capture audio endpoints,
   and removal of the owned device after explicit detach.
2. Exercise manual host/source roles, then Sunshine app hooks. Verify no extra
   DS4/Xbox pad, native game detection and cleanup when the app terminates.
3. Compare wired direct / local BT bridge / remote bridge in a game supporting
   DualSense: buttons, touch, motion, LEDs, independent triggers, rumble and
   detailed haptics. Record game, Steam Input setting, connection and firmware.
4. Measure latency, packet-loss behavior, audio underruns and 30-minute
   simultaneous input/haptics over LAN. Loopback does not establish LAN quality.
5. Test controller/source/host loss, app exit, network interruption,
   suspend/resume and restart. Require neutral input, released effects and
   confirmed device cleanup before another session.

Do not claim all-feature compatibility or production readiness before those
gates have recorded hardware evidence.
