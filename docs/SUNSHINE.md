# Sunshine integration

This integration uses built-in `prep-cmd` `do` / `undo` application hooks. `do`
blocks until USB/IP reports attachment; failures return a nonzero exit code.
`undo` asks the worker to detach its owned USB port and confirms shutdown.

## Configure

1. Copy `examples/sunshine-session.json` to a private local configuration, e.g.
   `.credentials/sunshine-session.json`. Set the controller PC's address and
   absolute host-credentials / `usbip.exe` paths. Relative paths resolve against
   the config file's directory.
2. Generate an entry for review:

   ```powershell
   .venv/Scripts/ds5driver.exe sunshine --config .credentials/sunshine-session.json --out .credentials/sunshine-app.json
   ```

3. Create a Desktop app in Sunshine's web UI and copy the entry's preparation
   command pair. To use an existing game app, add the pair to its prep commands
   and retain its game command. This JSON is one app entry, not a replacement
   `apps.json` file.
4. Disable Sunshine's ordinary forwarded controller input (`controller = disabled`)
   for this setup, using its web UI. The native controller reaches games through
   Windows USB. Keyboard and mouse forwarding remain available.
5. Start the source on the controller PC before launching the app in Moonlight.
   The generated hook requests elevated execution through Sunshine's service
   mechanism for access to the installed USB/IP driver.

Commands contain absolute Python/config paths and handle spaces. This tool does
not edit installed Sunshine configuration or restart its service. This is an
application integration, not a native gamepad-backend selector.

## Lifecycle limits

These are **application lifetime** hooks. Disconnecting a stream can leave a
game running, so `undo` is not guaranteed on every client disconnect. Stop the
app in Moonlight/Sunshine, or run:

```powershell
.venv/Scripts/ds5driver.exe session stop --config .credentials/sunshine-session.json
```

The worker writes logs and readiness/cleanup records in a unique `run-*` folder
beside the config. An exclusive `.session.json` record prevents concurrent
starts. Stop never kills a PID or detaches another USB/IP device. After a hard
crash, inspect its log and `usbip port` before removing a stale ownership record.
Network-drop reattachment is manual: stop, inspect cleanup errors, then start.

For a one-PC trial use `127.0.0.1` as the source. The physical Bluetooth pad
remains visible locally; a remote Sunshine host does not have that duplicate.
Keep the virtual controller separate from the system's default audio output;
its four-channel endpoint is for the game's controller speaker/haptic stream.

## Fork decision

Stock Sunshine with app hooks is the first target. A fork may be needed for
per-stream lifecycle, native UI backend selection, automatic client discovery,
or a dedicated lower-latency haptic channel. Changes to the feedback protocol
also require a compatible client: a driver alone cannot make Moonlight support
a new audio-haptics transport.

Reference: [Sunshine application preparation commands](https://github.com/LizardByte/Sunshine/blob/master/docs/app_examples.md).
