import json
import socket
import subprocess
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from triplesense import vpn
from triplesense.lan import LanDiscovery


class VpnDiscoveryTests(unittest.TestCase):
    def test_discovery_is_silent_until_pairing_and_stops_when_leaving(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.settimeout(0.4)
            client = LanDiscovery(
                lambda *args: None,
                "client",
                port=listener.getsockname()[1],
                targets=["127.0.0.1"],
                scanning=False,
            )
            try:
                with self.assertRaises(TimeoutError):
                    listener.recvfrom(2048)
                client.set_scanning(True)
                self.assertIn(b'"kind": "find"', listener.recvfrom(2048)[0])
                client.set_scanning(False)
                client.scan()
                with self.assertRaises(TimeoutError):
                    listener.recvfrom(2048)
            finally:
                client.close()

    def test_provider_status_parsing_uses_peer_addresses_only(self):
        self.assertEqual(
            vpn.peer_addresses(
                "tailscale",
                {
                    "Self": {"TailscaleIPs": ["100.64.0.1"]},
                    "Peer": {"key": {"TailscaleIPs": ["100.83.84.57", "fd7a::1", "invalid"]}},
                },
            ),
            {"100.83.84.57"},
        )
        self.assertEqual(
            vpn.peer_addresses(
                "netbird",
                {
                    "peers": {
                        "details": [
                            {"netbirdIp": "100.127.30.8/16", "status": "Connecting"},
                            {"netbirdIp": "127.0.0.1"},
                            {"netbirdIp": ""},
                        ]
                    }
                },
            ),
            {"100.127.30.8"},
        )

    def test_stopped_vpn_does_not_break_other_provider(self):
        with (
            patch.object(vpn, "executable", side_effect=lambda name: name),
            patch.object(
                vpn.subprocess,
                "run",
                side_effect=[
                    subprocess.TimeoutExpired("tailscale", 2),
                    SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps({"peers": {"details": [{"netbirdIp": "100.127.30.8"}]}}),
                    ),
                ],
            ),
        ):
            self.assertEqual(vpn.targets(), {"100.127.30.8"})

    def test_vpn_peer_unicast_finds_server_without_broadcast(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        ready = threading.Event()
        found = []

        def notify(kind, value):
            found.append(value)
            ready.set()

        game = LanDiscovery(lambda *args: None, "vpn-game", port=port, targets=[])
        client = None
        try:
            game.advertise()
            with (
                patch("triplesense.lan.broadcast_addresses", return_value=set()),
                patch("triplesense.lan.vpn.routes", return_value={"127.0.0.1": "Tailscale"}),
            ):
                client = LanDiscovery(notify, "vpn-client", port=port)
                self.assertTrue(ready.wait(3))
                self.assertEqual(found[0]["host_id"], "vpn-game")
                self.assertEqual(found[0]["transport"], "Tailscale")
                client.close()
                client = None
        finally:
            if client:
                client.close()
            game.close()
