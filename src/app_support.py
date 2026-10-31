"""Desktop preferences, LAN discovery and the bundled driver installer."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import plistlib
import socket
import subprocess
import sys
from pathlib import Path

SERVICE = "_dsshine._tcp.local."
DRIVER_HASH = "38cad6d4432b52d5bb9409d9ad03b72fdffc4ada4cd3a48fbeca1a2752a8518a"


def app_directory():
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    # Keep the existing private data directory so renaming preserves pairings.
    folder = root / "DSShine"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def load_preferences(root):
    try:
        data = json.loads((root / "settings.json").read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    from .server_identity import load

    identity = load(root)
    if identity:
        data.update(identity)
    return data


def save_preferences(root, preferences):
    temporary = root / "settings.tmp"
    temporary.write_text(json.dumps(preferences, indent=2) + "\n", encoding="utf-8")
    temporary.replace(root / "settings.json")


def local_addresses():
    addresses = set()
    preferred = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # UDP connect only selects a route; no packet is transmitted.
            probe.connect(("192.0.2.1", 9))
            preferred = probe.getsockname()[0]
            addresses.add(preferred)
    except OSError:
        pass
    try:
        addresses.update(
            item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        )
    except OSError:
        pass
    return sorted(
        (
            address
            for address in addresses
            if ipaddress.ip_address(address).is_private
            and not ipaddress.ip_address(address).is_loopback
        ),
        key=lambda address: (address != preferred, address),
    )


class Discovery:
    def __init__(self, notify, identity):
        from zeroconf import IPVersion, Zeroconf

        from .lan import LanDiscovery

        self.notify = notify
        self.identity = identity
        self.service_ids = {}
        self.lan = LanDiscovery(notify, identity, scanning=False)
        self.scanning = False
        self.zeroconf = self.browser = None
        try:
            self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        except OSError:
            pass  # Broadcast discovery remains available without Bonjour.
        self.advertisement = None

    def _changed(self, zeroconf, service_type, name, state_change):
        from zeroconf import ServiceStateChange

        if not self.scanning:
            return
        if state_change is ServiceStateChange.Removed:
            self.notify("computer_removed", self.service_ids.pop(name, name))
            return
        info = zeroconf.get_service_info(service_type, name, timeout=1500)
        if info:
            identity = info.properties.get(b"id", b"").decode("ascii", errors="ignore")
            identifier = "dsshine:" + identity if identity else name
            self.service_ids[name] = identifier
            for address in info.parsed_addresses():
                if ipaddress.ip_address(address).version == 4:
                    self.notify(
                        "computer",
                        {
                            "id": identifier,
                            "host_id": identity,
                            "address": address,
                            "name": name.removesuffix("." + service_type)[:64],
                            "dsshine": service_type == SERVICE,
                            "transport": "LAN",
                        },
                    )
                    break

    def advertise(self):
        from zeroconf import ServiceInfo

        self.withdraw()
        self.lan.advertise()
        if not self.zeroconf:
            return
        addresses = local_addresses()
        if not addresses:
            raise RuntimeError("No LAN connection found")
        name = socket.gethostname().replace(".", "-")[:48]
        self.advertisement = ServiceInfo(
            SERVICE,
            name + "." + SERVICE,
            addresses=[socket.inet_aton(addresses[0])],
            port=3250,
            properties={b"version": b"1", b"pair_port": b"3251", b"id": self.identity.encode()},
        )
        try:
            self.zeroconf.register_service(self.advertisement, allow_name_change=True)
        except OSError:
            self.advertisement = None

    def withdraw(self):
        self.lan.withdraw()
        if self.advertisement:
            self.zeroconf.unregister_service(self.advertisement)
            self.advertisement = None

    def close(self):
        self.set_scanning(False)
        self.withdraw()
        self.lan.close()
        if self.browser:
            self.browser.cancel()
        if self.zeroconf:
            self.zeroconf.close()

    def scan(self):
        self.lan.scan()

    def set_scanning(self, enabled):
        from zeroconf import ServiceBrowser

        if enabled == self.scanning:
            return
        self.scanning = enabled
        self.lan.set_scanning(enabled)
        if enabled and self.zeroconf:
            self.browser = ServiceBrowser(self.zeroconf, [SERVICE], handlers=[self._changed])
        elif self.browser:
            self.browser.cancel()
            self.browser = None


def bundled_installer():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    path = root / "installers" / "USBip-0.9.8.1-x64.exe"
    if not path.is_file():
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != DRIVER_HASH:
        raise RuntimeError("The bundled controller driver failed its integrity check")
    return path


def set_launch_at_login(enabled):
    """Register only the packaged app, under the current user's account."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Launch at login is available in the packaged application")
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
        ) as key:
            try:
                winreg.DeleteValue(key, "DSShine")
            except FileNotFoundError:
                pass
            if enabled:
                winreg.SetValueEx(
                    key,
                    "TripleSense",
                    0,
                    winreg.REG_SZ,
                    subprocess.list2cmdline([sys.executable]),
                )
            else:
                try:
                    winreg.DeleteValue(key, "TripleSense")
                except FileNotFoundError:
                    pass
    elif sys.platform == "darwin":
        path = Path.home() / "Library/LaunchAgents/me.dsshine.app.plist"
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as stream:
                plistlib.dump(
                    {
                        "Label": "me.dsshine.app",
                        "ProgramArguments": [sys.executable],
                        "RunAtLoad": True,
                        "LimitLoadToSessionType": "Aqua",
                    },
                    stream,
                )
        else:
            path.unlink(missing_ok=True)
    elif sys.platform.startswith("linux"):
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        path = path / "autostart/triplesense.desktop"
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            executable = sys.executable.replace("\\", "\\\\").replace('"', '\\"')
            # Desktop Entry Exec expands percent field codes, even inside quotes.
            executable = executable.replace("%", "%%")
            path.write_text(
                "[Desktop Entry]\nType=Application\nName=TripleSense\n"
                f'Exec="{executable}"\nIcon=triplesense\nTerminal=false\n',
                encoding="utf-8",
            )
        else:
            path.unlink(missing_ok=True)
