"""Discover VPN peer addresses through installed agents, without subnet scanning."""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def executable(provider):
    candidates = [shutil.which(provider)]
    if sys.platform == "win32":
        folder = "Tailscale" if provider == "tailscale" else "Netbird"
        candidates.append(
            str(
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / folder
                / (provider + ".exe")
            )
        )
    else:
        candidates.extend(
            [f"/usr/local/bin/{provider}", f"/opt/homebrew/bin/{provider}", f"/usr/bin/{provider}"]
        )
        if provider == "tailscale":
            candidates.append("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    return next((path for path in candidates if path and Path(path).is_file()), None)


def peer_addresses(provider, status):
    if provider == "tailscale":
        peers = (status.get("Peer") or {}).values()
        addresses = [address for peer in peers for address in peer.get("TailscaleIPs", [])]
    else:
        peers = (status.get("peers") or {}).get("details") or []
        addresses = [peer.get("netbirdIp", "") for peer in peers]
    result = set()
    for value in addresses:
        try:
            address = ipaddress.ip_interface(value).ip
        except (ValueError, TypeError):
            continue
        if address.version == 4 and not (
            address.is_loopback or address.is_multicast or address.is_unspecified
        ):
            result.add(str(address))
    return result


def routes():
    addresses = {}
    for provider in ("tailscale", "netbird"):
        path = executable(provider)
        if not path:
            continue
        try:
            result = subprocess.run(
                [path, "status", "--json"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                for address in peer_addresses(provider, json.loads(result.stdout)):
                    addresses[address] = "Tailscale" if provider == "tailscale" else "NetBird"
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError):
            continue  # An absent/stopped VPN must not break LAN discovery.
    return addresses


def targets():
    return set(routes())
