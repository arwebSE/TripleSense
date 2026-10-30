# DSShine

Use your DualSense with a gaming computer even when the controller is connected
to a different computer.
DSShine sends the controller connection between the two computers, including
adaptive triggers, vibration and touchpad input.

Use it alongside your preferred game-streaming app. Sunshine and Moonlight
are our tested setup, but are not required by DSShine.

**[Download DSShine](https://github.com/arwebSE/DSShine/releases)** ·
[Setup and troubleshooting](docs/STANDALONE.md)

> **Preview release:** controller input and adaptive triggers have been tested.
> Bluetooth speaker and microphone have passed Mac-to-Windows signal tests with
> the new native Mac transport. Detailed audio haptics and broader hardware/OS
> compatibility still need testing. Other streaming apps have not yet been tested.

## What you need

- A Windows gaming PC (64-bit).
- A controller computer running Windows or macOS, with a Bluetooth DualSense.
- Both computers on the same local network, or connected through your own
  private VPN such as Tailscale or NetBird.

The gaming computer runs **Server**; the computer beside your controller runs
**Client**. A Mac is optional. The current Mac download is for Apple Silicon.
Windows and macOS clients are implemented; Mac-to-Windows is the setup tested
with a real controller so far. macOS Server support is planned.

You do **not** need Python, SSH, a terminal or developer tools. Everything needed
by the apps is included; Windows asks for administrator permission to install
the controller driver. macOS and Linux gaming-PC support is planned.

## Get connected

1. **On Windows:** download and run the Windows installer, then open DSShine
   in **Server** mode.
2. **On the controller computer:** install DSShine and use **Client** mode.
   On macOS, drag the app from the disk image into Applications; it opens as
   Client automatically. Allow Bluetooth/local-network access when asked.
3. **On Windows:** Server shows a four-digit pairing code automatically.
4. **On the Client:** enter the Server address and code, then click **Connect**.
   The Client automatically finds servers on LAN and Tailscale/NetBird every five
   seconds while adding a server. You can also enter the address manually.
5. Turn on your DualSense and start your game or stream.

Pairing is saved, so you only need the code once. Newly requested codes copy automatically;
**Copy code** copies the displayed code again. Click any Server IP address to
copy that address.
While waiting, the Server renews expired codes automatically without changing
your clipboard or your existing pairing.
The Client keeps a saved-server list with online/offline indicators. Use
**Add server** to pair another computer, or **Remove** to forget an old one.

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
[credits and upstream project](docs/UPSTREAM.md) · [platform and feature plan](docs/PRODUCT.md)
