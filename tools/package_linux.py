"""Package the frozen application for Debian/Ubuntu; no user Python setup."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from dualsensedriver import __version__

ROOT = Path(__file__).resolve().parents[1]


def package_linux():
    staging = ROOT / "build/linux-package"
    if staging.exists():
        shutil.rmtree(staging)
    app = staging / "opt/triplesense"
    shutil.copytree(ROOT / "dist/TripleSense", app, symlinks=True)
    helper = app / "triplesense-vhci"
    shutil.copy2(ROOT / "packaging/linux/triplesense-vhci", helper)
    helper.write_bytes(helper.read_bytes().replace(b"\r\n", b"\n"))
    helper.chmod(0o755)

    def write(path, content, mode=0o644):
        target = staging / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        target.chmod(mode)

    architecture = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
    write(
        "DEBIAN/control",
        f"""Package: triplesense
Version: {__version__}
Section: games
Priority: optional
Architecture: {architecture}
Maintainer: TripleSense contributors
Depends: python3, pkexec, kmod, libudev1, libgl1, libegl1, libglib2.0-0,
 libdbus-1-3, libxkbcommon0, libfontconfig1, libxcb-cursor0
Description: Share a DualSense controller between computers
 Bundled desktop client and Linux USB/IP server, including controller audio.
 Uses the distribution's vhci_hcd module; no custom kernel module is installed.
""",
    )
    write(
        "usr/share/applications/triplesense.desktop",
        """[Desktop Entry]
Type=Application
Name=TripleSense
Comment=Share your DualSense between computers
Exec=/opt/triplesense/TripleSense
Icon=triplesense
Terminal=false
Categories=Game;Utility;
""",
    )
    icon = staging / "usr/share/icons/hicolor/512x512/apps/triplesense.png"
    icon.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "src/dualsensedriver/assets/dsshine.png", icon)
    write(
        "usr/lib/udev/rules.d/70-triplesense.rules",
        """# Access only for the active local desktop seat.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="0ce6", TAG+="uaccess"
SUBSYSTEM=="hidraw", KERNELS=="0005:054C:0CE6.*", TAG+="uaccess"
SUBSYSTEM=="misc", KERNEL=="uinput", TAG+="uaccess", OPTIONS+="static_node=uinput"
""",
    )
    write("usr/lib/modules-load.d/triplesense.conf", "vhci_hcd\nuinput\n")
    write(
        "usr/share/polkit-1/actions/me.triplesense.vhci.policy",
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig><vendor>TripleSense</vendor>
 <action id="me.triplesense.vhci">
  <description>Connect a TripleSense virtual controller</description>
  <message>Authorize TripleSense to connect its virtual DualSense controller</message>
  <defaults><allow_any>no</allow_any><allow_inactive>no</allow_inactive>
   <allow_active>auth_admin_keep</allow_active></defaults>
  <annotate key="org.freedesktop.policykit.exec.path">/opt/triplesense/triplesense-vhci</annotate>
 </action>
</policyconfig>
""",
    )
    write(
        "DEBIAN/postinst",
        """#!/bin/sh
set -e
udevadm control --reload-rules || true
udevadm trigger --subsystem-match=hidraw || true
modprobe vhci_hcd || true
modprobe uinput || true
udevadm trigger --subsystem-match=misc --sysname-match=uinput || true
""",
        0o755,
    )
    write(
        "DEBIAN/postrm",
        """#!/bin/sh
set -e
udevadm control --reload-rules || true
""",
        0o755,
    )
    os.chmod(app / "TripleSense", 0o755)
    output = ROOT / f"dist/TripleSense-{__version__}-Linux-{architecture}.deb"
    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(staging), str(output)], check=True
    )
    return output


if __name__ == "__main__":
    print(package_linux())
