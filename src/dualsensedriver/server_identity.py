"""Keep the accepted server identity independent of ordinary UI preferences."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


def _folder(root, relative):
    folder = (root / relative).resolve()
    identities = (root / "identities").resolve()
    if (not folder.is_relative_to(identities) or folder.name != "credentials"
            or not folder.parent.name.startswith("game-")):
        raise ValueError("Invalid saved server identity path")
    if not all((folder / name).is_file() for name in ("ca.pem", "cert.pem", "key.pem")):
        raise ValueError("Saved server identity is incomplete")
    return folder


def remember(root, credentials, controller_name):
    root = Path(root).resolve()
    folder = _folder(root, Path(credentials).resolve().relative_to(root))
    value = {
        "credentials": str(folder.relative_to(root)),
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
        return {"game_credentials": str(folder), "controller_name": str(value["controller_name"])[:64]}
    except (OSError, ValueError, KeyError, TypeError):
        return None
