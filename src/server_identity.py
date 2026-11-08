"""Keep the accepted server identity independent of ordinary UI preferences."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


def _folder(root, relative):
    relative = Path(relative)
    if (
        relative.is_absolute()
        or len(relative.parts) != 3
        or relative.parts[0] != "identities"
        or not relative.parts[1].startswith("game-")
        or relative.parts[2] != "credentials"
    ):
        raise ValueError("Invalid saved server identity path")
    folder = root / relative
    for directory in (root / "identities", folder.parent, folder):
        if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
            raise ValueError("Invalid saved server identity path")
    if not all((folder / name).is_file() for name in ("ca.pem", "cert.pem", "key.pem")):
        raise ValueError("Saved server identity is incomplete")
    return folder


def remember(root, credentials, controller_name):
    root = Path(root).resolve()
    # Windows app-data virtualization can resolve a child into a package cache
    # while leaving its parent logical. Validate the exact relative layout and
    # reject links instead of comparing those inconsistent resolved paths.
    relative = Path(credentials).absolute().relative_to(root)
    folder = _folder(root, relative)
    value = {
        "credentials": str(relative),
        "ca_sha256": hashlib.sha256((folder / "ca.pem").read_bytes()).hexdigest(),
        "controller_name": str(controller_name)[:64],
    }
    fd, temporary = tempfile.mkstemp(prefix="server-identity-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / "server-identity.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def load(root):
    root = Path(root).resolve()
    try:
        value = json.loads((root / "server-identity.json").read_text("utf-8"))
        folder = _folder(root, value["credentials"])
        if hashlib.sha256((folder / "ca.pem").read_bytes()).hexdigest() != value["ca_sha256"]:
            return None
        return {
            "game_credentials": str(folder),
            "controller_name": str(value["controller_name"])[:64],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None
