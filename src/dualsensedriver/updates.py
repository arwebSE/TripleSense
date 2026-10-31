"""GitHub release updates, verified before handing off to OS installers."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = "arwebSE/TripleSense"
API = f"https://api.github.com/repos/{REPOSITORY}"
SERVICE = "TripleSense GitHub updates"
MAX_DOWNLOAD = 512 * 1024 * 1024


class UpdateError(RuntimeError):
    pass


class GitHubAccessRequired(UpdateError):
    pass


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise UpdateError("The release has an unsupported version number.")
    return tuple(map(int, match.groups()))


def github_token():
    import keyring

    return keyring.get_password(SERVICE, REPOSITORY)


def save_github_token(token):
    import keyring

    if token:
        keyring.set_password(SERVICE, REPOSITORY, token.strip())
    else:
        try:
            keyring.delete_password(SERVICE, REPOSITORY)
        except keyring.errors.PasswordDeleteError:
            pass


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise UpdateError("The update server redirected to an insecure address.")
        result = super().redirect_request(request, fp, code, message, headers, url)
        if (
            result
            and urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(request.full_url).netloc
        ):
            result.remove_header("Authorization")
        return result


def open_github(url, token=None, *, binary=False):
    if not url.startswith(API + "/"):
        raise UpdateError("The release asset does not belong to this project.")
    headers = {
        "User-Agent": "TripleSense-Updater",
        "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        if not re.fullmatch(r"[A-Za-z0-9_]{10,512}", token):
            raise UpdateError("The GitHub token has an invalid format. Check it and try again.")
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    try:
        return urllib.request.build_opener(SafeRedirect()).open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 404):
            raise GitHubAccessRequired(
                "GitHub releases are unavailable. This repository may be private. "
                "Add GitHub access to check private releases."
            ) from None
        if exc.code == 403:
            raise UpdateError(
                "GitHub denied the request or its request limit was reached. Try later."
            ) from None
        raise UpdateError(f"GitHub returned HTTP {exc.code}. Try again later.") from None
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError(
            "Could not reach GitHub. Check your internet connection and retry."
        ) from exc


@dataclass(frozen=True)
class Release:
    version: str
    name: str
    url: str
    digest: str
    size: int


def select_release(data, current, *, system=None, machine=None):
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.removeprefix("v")
    system, machine = system or sys.platform, machine or platform.machine().lower()
    if system == "win32" and machine in ("amd64", "x86_64"):
        filename = f"TripleSense-Setup-{version}-Windows-x64.exe"
    elif system == "darwin" and machine in ("arm64", "aarch64"):
        filename = "TripleSense-macOS.dmg"
    elif system.startswith("linux") and machine in ("amd64", "x86_64", "aarch64", "arm64"):
        arch = "amd64" if machine in ("amd64", "x86_64") else "arm64"
        filename = f"TripleSense-{version}-Linux-{arch}.deb"
    else:
        raise UpdateError("This release has no installer for your operating system and processor.")
    for asset in data.get("assets", []):
        if asset.get("name") != filename or asset.get("state") != "uploaded":
            continue
        digest, size, url = asset.get("digest", ""), asset.get("size"), asset.get("url", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest or ""):
            raise UpdateError(
                "This release has no SHA-256 verification data. "
                "It cannot be installed automatically."
            )
        if type(size) is not int or not 0 < size <= MAX_DOWNLOAD:
            raise UpdateError("The release installer has an invalid size.")
        if not re.fullmatch(re.escape(API) + r"/releases/assets/\d+", url):
            raise UpdateError("The release installer has an unexpected download address.")
        return Release(version, filename, url, digest[7:], size)
    raise UpdateError("The new release is not packaged for this computer yet. Try again later.")


def check_release(current, token=None):
    with open_github(API + "/releases/latest", token) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise UpdateError("GitHub returned an oversized release description.")
    return select_release(json.loads(body), current)


def download_release(release, directory, token=None, progress=lambda *_: None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / release.name
    partial = destination.with_suffix(destination.suffix + ".partial")
    digest, total = hashlib.sha256(), 0
    try:
        with open_github(release.url, token, binary=True) as response, partial.open("wb") as stream:
            while block := response.read(256 * 1024):
                total += len(block)
                if total > release.size:
                    raise UpdateError("The installer is larger than its published size.")
                stream.write(block)
                digest.update(block)
                progress(total, release.size)
        if total != release.size or digest.hexdigest() != release.digest:
            raise UpdateError("The installer failed its SHA-256 check. Nothing was installed.")
        partial.replace(destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def stage_macos(package, version, executable=None):
    executable = Path(executable or sys.executable).resolve()
    target = executable.parents[2]
    if target.suffix != ".app" or not (target / "Contents/Info.plist").is_file():
        raise UpdateError("Install TripleSense in Applications before updating it.")
    directory = Path(tempfile.mkdtemp(prefix="triplesense-update-"))
    mount = directory / "mount"
    mount.mkdir()
    subprocess.run(
        [
            "/usr/bin/hdiutil",
            "attach",
            "-readonly",
            "-nobrowse",
            "-mountpoint",
            str(mount),
            str(package),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    try:
        source = mount / "TripleSense.app"
        with (source / "Contents/Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        if (
            info.get("CFBundleIdentifier") != "me.dsshine.app"
            or info.get("CFBundleShortVersionString") != version
        ):
            raise UpdateError("The downloaded app has an unexpected identity or version.")
        subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(source)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        staged = directory / "TripleSense.app"
        subprocess.run(["/usr/bin/ditto", str(source), str(staged)], check=True, timeout=60)
        return staged, target
    finally:
        subprocess.run(
            ["/usr/bin/hdiutil", "detach", str(mount)], check=True, capture_output=True, timeout=30
        )


def launch_installer(package, root, *, mac_stage=None):
    """Launch a detached helper; it waits for this app to exit before replacing files."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("Self-update is available in the installed application.")
    assets = Path(__file__).with_name("assets")
    log = Path(root) / "update-install.log"
    if sys.platform == "win32":
        script = Path(root) / "update-windows.ps1"
        script.write_bytes((assets / "update-windows.ps1").read_bytes())
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                str(os.getpid()),
                str(package),
                sys.executable,
                str(log),
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    else:
        script = Path(root) / "update-unix.sh"
        script.write_bytes((assets / "update-unix.sh").read_bytes())
        staged, target = mac_stage if mac_stage else (package, sys.executable)
        with log.open("ab") as output:
            subprocess.Popen(
                [
                    "/bin/sh",
                    str(script),
                    str(os.getpid()),
                    sys.platform,
                    str(staged),
                    str(target),
                ],
                stdout=output,
                stderr=output,
                start_new_session=True,
                close_fds=True,
            )
