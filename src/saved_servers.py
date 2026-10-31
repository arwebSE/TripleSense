"""Saved paired servers and authenticated reachability checks."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from .credentials import SERVER_NAME, tls_context
from .transport import close_writer


def migrate(preferences):
    servers = preferences.setdefault("servers", {})
    profile = preferences.get("controller_profile")
    selected = preferences.get("selected_server")
    if profile and selected not in servers:
        selected = next(
            (
                key
                for key, value in servers.items()
                if value.get("credentials") == profile.get("credentials")
            ),
            profile.get("host_id") or uuid.uuid4().hex,
        )
        servers[selected] = profile
        preferences["selected_server"] = selected
    if selected in servers:
        preferences["controller_profile"] = servers[selected]
    return servers


def remember(preferences, profile):
    servers = migrate(preferences)
    identifier = profile.get("host_id") or uuid.uuid4().hex
    servers[identifier] = profile
    select(preferences, identifier)
    return identifier


def select(preferences, identifier):
    profile = preferences["servers"][identifier]
    preferences["selected_server"] = identifier
    preferences["controller_profile"] = profile
    preferences["game_address"] = profile["address"]


def forget(preferences, identifier, root):
    servers = migrate(preferences)
    profile = servers.pop(identifier)
    if preferences.get("selected_server") == identifier:
        preferences.pop("selected_server", None)
        preferences.pop("controller_profile", None)
        preferences.pop("game_address", None)
        if servers:
            select(preferences, next(iter(servers)))
    credentials = Path(profile.get("credentials", "")).resolve()
    identities = (root / "identities").resolve()
    shared = any(
        Path(value.get("credentials", "")).resolve() == credentials for value in servers.values()
    )
    if (
        not shared
        and credentials.parent == identities
        and credentials.name.startswith("controller-")
        and credentials.is_dir()
    ):
        shutil.rmtree(credentials)


async def probe(profile, *, timeout=2.5):
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(
                profile["address"],
                profile["port"],
                ssl=tls_context(Path(profile["credentials"]), server=False),
                server_hostname=SERVER_NAME,
                ssl_handshake_timeout=timeout,
                ssl_shutdown_timeout=1,
            ),
            timeout,
        )
        return "online"
    except (OSError, ValueError, TimeoutError):
        return "offline"
    finally:
        if writer:
            await close_writer(writer)
