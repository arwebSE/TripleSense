# DSShine

Use the DualSense connected to your Mac to play games on your Windows PC.
DSShine sends the controller connection between the two computers, including
adaptive triggers, vibration and touchpad input.

Use it alongside your preferred game-streaming app. Sunshine and Moonlight
are our tested setup, but are not required by DSShine.

**[Download DSShine](https://github.com/arwebSE/DSShine/releases)** ·
[Setup and troubleshooting](docs/STANDALONE.md)

> **Preview release:** controller input and adaptive triggers have been tested.
> Controller speaker, microphone and detailed audio haptics are still experimental;
> Bluetooth audio can drop out. Other streaming apps have not yet been tested.

## What you need

- A Windows gaming PC (64-bit).
- An Apple Silicon Mac and a DualSense connected to it over Bluetooth.
- Both computers on the same local network.

You do **not** need Python, SSH, a terminal or developer tools. Everything needed
by the apps is included; Windows asks for administrator permission to install
the controller driver. macOS and Linux gaming-PC support is planned.

## Get connected

1. **On Windows:** download and run the Windows installer, then open DSShine
   in **Server** mode.
2. **On your Mac:** download the Mac disk image, drag DSShine into Applications
   and open it. Allow Bluetooth and local-network access when asked.
3. **On Windows:** click **Pair client**, then **Generate code**.
4. **On your Mac:** click **Pair server**, select your Windows PC, enter its
   four-digit code and click **Pair and connect**.
5. Turn on your DualSense and start your game or stream.

Pairing is saved, so you only need the code once. New codes copy automatically;
**Copy code** copies the displayed code again.

If your streaming app also forwards controllers, disable that feature if it
causes duplicate input. DSShine does not change your streaming app's settings.

## Everyday use

Open DSShine on both computers and turn on your controller. It reconnects
automatically. Minimize the window to keep playing; closing it disconnects the
controller and quits the app.

Controller audio is enabled by default. If it causes dropouts, disconnect,
uncheck **Controller audio**, then connect again. Ordinary game sound through
your streaming app is separate.

If macOS blocks the downloaded preview, see
[Apple's instructions for opening it](https://support.apple.com/en-gb/102445).
For connection problems, see [setup and troubleshooting](docs/STANDALONE.md).

---

For contributors: [development guide](docs/DEVELOPMENT.md) ·
[credits and upstream project](docs/UPSTREAM.md)
