"""Packaged Windows setup repair, launched by the app with UAC elevation."""

from __future__ import annotations

import configparser
import ctypes
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .app_support import bundled_installer
from .diagnostics import find_usbip


def disable_forwarding(text):
    lines, found = [], False
    for line in text.splitlines():
        key, separator, _ = line.partition("=")
        if separator and key.strip().lower() == "controller":
            if not found:
                lines.append("controller = disabled")
            found = True
        else:
            lines.append(line)
    if not found:
        lines.append("controller = disabled")
    return "\n".join(lines) + "\n"


def repair_windows():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("Setup repair requires the installed Windows application")
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Windows administrator permission is needed to repair setup")
    if not find_usbip():
        installer = bundled_installer()
        if not installer:
            raise RuntimeError("Reinstall DSShine to restore its bundled controller driver")
        result = subprocess.run(
            [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False
        )
        if result.returncode not in (0, 3010):
            raise RuntimeError("The controller driver installer could not finish")
    netsh = str(Path(os.environ["SystemRoot"]) / "System32/netsh.exe")
    for name, protocol, ports in (
        ("Controller", "TCP", "3250-3251"),
        ("Discovery", "UDP", "5353,3252"),
    ):
        rule = "DSShine - " + name
        subprocess.run(
            [netsh, "advfirewall", "firewall", "delete", "rule", "name=" + rule],
            capture_output=True,
        )
        subprocess.run(
            [
                netsh,
                "advfirewall",
                "firewall",
                "add",
                "rule",
                "name=" + rule,
                "dir=in",
                "action=allow",
                "program=" + sys.executable,
                "protocol=" + protocol,
                "localport=" + ports,
                "profile=private,public",
                "remoteip=localsubnet",
            ],
            capture_output=True,
            check=True,
        )
    config = Path(os.environ["ProgramFiles"]) / "Sunshine/config/sunshine.conf"
    changed = False
    if config.is_file():
        text = config.read_text(encoding="utf-8-sig")
        previous = "__missing__"
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip().lower() == "controller":
                previous = value.strip()
        if previous != "disabled":
            state_path = Path(sys.executable).parent / "sunshine-setting.ini"
            if not state_path.exists():
                state = configparser.ConfigParser()
                state["Sunshine"] = {"Previous": previous, "Config": str(config)}
                with state_path.open("w", encoding="utf-8") as stream:
                    state.write(stream)
            backup = config.with_name(
                config.name + ".dsshine-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S")
            )
            shutil.copy2(config, backup)
            temporary = config.with_suffix(".dsshine.tmp")
            temporary.write_text(disable_forwarding(text), encoding="utf-8")
            temporary.replace(config)
            changed = True
    return changed


def request_repair():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("Install DSShine to use automatic setup repair")
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, "--repair-setup", None, 0
    )
    if result <= 32:
        raise RuntimeError("Setup repair was cancelled or could not start")
