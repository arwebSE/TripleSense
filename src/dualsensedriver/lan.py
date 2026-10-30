"""Small LAN discovery fallback for networks that drop Bonjour multicast.

Discovery is untrusted. Pairing and mutual TLS still authenticate the peer.
No credentials or pairing codes are sent on this channel.
"""

from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import threading
import time

from . import vpn

PORT = 3252
MAGIC = b"DSShine discovery v1 "


def broadcast_addresses():
    import ifaddr

    addresses = {"255.255.255.255"}
    for adapter in ifaddr.get_adapters():
        for address in adapter.ips:
            if not address.is_IPv4:
                continue
            network = ipaddress.ip_network(f"{address.ip}/{address.network_prefix}", strict=False)
            if network.is_private and not network.is_loopback and network.prefixlen < 31:
                addresses.add(str(network.broadcast_address))
    return addresses


class LanDiscovery:
    def __init__(self, notify, identity, *, port=PORT, targets=None, scanning=True):
        self.notify, self.identity, self.port = notify, identity, port
        self.targets = targets
        self.vpn_targets = set()
        self.next_vpn_scan = 0
        self.scanning = scanning
        self.name = socket.gethostname()[:64]
        self.token = secrets.token_hex(16)
        self.game = False
        self.server = None
        self.stop_event = threading.Event()
        self.scan_event = threading.Event()
        self.client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.client.bind(("0.0.0.0", 0))
        self.client.settimeout(0.2)
        self.thread = threading.Thread(target=self._run, name="dsshine-discovery", daemon=True)
        self.thread.start()

    def advertise(self):
        if self.server is None:
            server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                server.bind(("0.0.0.0", self.port))
                server.setblocking(False)
            except BaseException:
                server.close()
                raise
            self.server = server
        self.game = True

    def withdraw(self):
        self.game = False

    def scan(self):
        self.next_vpn_scan = 0
        self.scan_event.set()

    def set_scanning(self, enabled):
        self.scanning = enabled
        if enabled:
            self.scan()

    def _receive_reply(self, packet, peer):
        if not packet.startswith(MAGIC):
            return
        value = json.loads(packet[len(MAGIC) :])
        if value.get("token") != self.token or value.get("kind") != "game":
            return
        identity, name = value.get("id"), value.get("name")
        if (
            not isinstance(identity, str)
            or not 1 <= len(identity) <= 64
            or not isinstance(name, str)
            or not 1 <= len(name) <= 64
        ):
            return
        self.notify(
            "computer",
            {
                "id": "dsshine:" + identity,
                "host_id": identity,
                "address": peer[0],
                "name": name,
                "dsshine": True,
            },
        )

    def _run(self):
        next_scan = 0
        while not self.stop_event.is_set():
            try:
                if (
                    self.scanning
                    and not self.game
                    and (time.monotonic() >= next_scan or self.scan_event.is_set())
                ):
                    self.scan_event.clear()
                    next_scan = time.monotonic() + 5
                    packet = MAGIC + json.dumps({"kind": "find", "token": self.token}).encode()
                    targets = self.targets
                    if targets is None:
                        if time.monotonic() >= self.next_vpn_scan:
                            self.vpn_targets = vpn.targets()
                            self.next_vpn_scan = time.monotonic() + 5
                        targets = broadcast_addresses() | self.vpn_targets
                    for target in targets:
                        try:
                            self.client.sendto(packet, (target, self.port))
                        except OSError:
                            continue
                if self.game and self.server:
                    try:
                        packet, peer = self.server.recvfrom(2048)
                        if packet.startswith(MAGIC):
                            value = json.loads(packet[len(MAGIC) :])
                            token = value.get("token")
                            if (
                                value.get("kind") == "find"
                                and isinstance(token, str)
                                and len(token) == 32
                            ):
                                response = {
                                    "kind": "game",
                                    "token": token,
                                    "id": self.identity,
                                    "name": self.name,
                                }
                                self.server.sendto(MAGIC + json.dumps(response).encode(), peer)
                    except BlockingIOError:
                        pass
                try:
                    packet, peer = self.client.recvfrom(2048)
                    self._receive_reply(packet, peer)
                except TimeoutError:
                    pass
            except (OSError, ValueError, TypeError, AttributeError):
                self.stop_event.wait(0.2)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
        self.client.close()
        if self.server:
            self.server.close()
