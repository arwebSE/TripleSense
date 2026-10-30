"""Packaged Windows setup repair, launched by the app with UAC elevation."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from .app_support import bundled_installer
from .diagnostics import find_usbip


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
                "remoteip=localsubnet,100.64.0.0/10",
            ],
            capture_output=True,
            check=True,
        )


def request_repair():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("Install DSShine to use automatic setup repair")
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, "--repair-setup", None, 0
    )
    if result <= 32:
        raise RuntimeError("Setup repair was cancelled or could not start")
