"""Build a self-contained Windows application or macOS .app on that platform."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

from dualsensedriver import __version__
from dualsensedriver.app_support import DRIVER_HASH

ROOT = Path(__file__).resolve().parents[1]


def notices():
    destination = ROOT / "build" / "app-notices"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", destination / "TripleSense-LICENSE.txt")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")
    for path in (ROOT / "packaging").glob("Qt-*.txt"):
        shutil.copy2(path, destination / path.name)
    shutil.copy2(ROOT / "packaging" / "QT-LICENSES.md", destination / "QT-LICENSES.md")
    for filename in ("LICENSE", "NOTICE", "ATTRIBUTIONS.md"):
        shutil.copy2(
            ROOT / "vendor" / "ds5-virtual-cable" / filename,
            destination / ("ds5-virtual-cable-" + filename + ".txt"),
        )
    packages = []
    names = [
        "cryptography",
        "spake2",
        "zeroconf",
        "ifaddr",
        "numpy",
        "av",
        "hidapi",
        "PySide6-Essentials",
        "shiboken6",
        "pyinstaller",
        "keyring",
        "jaraco.classes",
        "jaraco.context",
        "jaraco.functools",
        "more-itertools",
    ]
    if sys.platform == "linux":
        names.extend(["evdev", "SecretStorage", "jeepney"])
    for name in names:
        distribution = importlib.metadata.distribution(name)
        folder = destination / name
        folder.mkdir(exist_ok=True)
        for item in distribution.files or []:
            if any(
                word in item.name.lower() for word in ("license", "copying", "copyright", "notice")
            ):
                path = distribution.locate_file(item)
                if path.is_file():
                    relative = Path(*(part for part in item.parts if part not in (".", "..")))
                    target = folder / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
        packages.append({"name": name, "version": distribution.version})
    python_licenses = (
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
    )
    python_license = next((path for path in python_licenses if path.is_file()), None)
    if python_license is None:
        raise RuntimeError("Could not find the bundled Python runtime license")
    shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    (destination / "DEPENDENCIES.json").write_text(json.dumps(packages, indent=2), encoding="utf-8")
    if sys.platform == "win32":
        # Retain the driver's BSD-2-Clause notice when distributing its unmodified installer.
        license_path = ROOT / "packaging" / "usbip-win2-LICENSE.txt"
        shutil.copy2(license_path, destination / license_path.name)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--installer", action="store_true", help="Also compile the Windows installer"
    )
    args = parser.parse_args()
    if sys.platform not in ("win32", "darwin", "linux"):
        parser.error("Build on Windows, macOS or Linux")
    license_dir = notices()
    # PyInstaller needs a physical package directory; setuptools maps our flat
    # src directory to the existing import name for normal/editable installs.
    package_root = ROOT / "build" / "python"
    package = package_root / "dualsensedriver"
    if package.exists():
        shutil.rmtree(package)
    shutil.copytree(
        ROOT / "src", package, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--icon",
        str(ROOT / "src/assets" / ("dsshine.icns" if sys.platform == "darwin" else "dsshine.ico")),
        "--add-data",
        str(ROOT / "src/assets") + ":dualsensedriver/assets",
        "--name",
        "TripleSense",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build"),
        "--paths",
        str(package_root),
        "--paths",
        str(ROOT / "vendor" / "ds5-virtual-cable" / "emulator"),
        "--paths",
        str(ROOT / "vendor" / "ds5-virtual-cable" / "prototype"),
        "--add-data",
        str(license_dir) + ":licenses",
        "--collect-binaries",
        "av",
        "--hidden-import",
        "ds5emu.bridge",
        "--hidden-import",
        "dualsensedriver.controller",
    ]
    if sys.platform == "win32":
        installer = ROOT / ".driver" / "USBip-0.9.8.1-x64.exe"
        if (
            not installer.is_file()
            or hashlib.sha256(installer.read_bytes()).hexdigest() != DRIVER_HASH
        ):
            parser.error(
                "Run scripts/Install-HostDriver.ps1 without -Install to verify the driver download"
            )
        command += ["--add-data", str(installer) + ":installers"]
    command.append(str(ROOT / "packaging" / "app_entry.py"))
    environment = os.environ.copy()
    if sys.platform == "win32":
        windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
        # Toolchains can put unrelated ICU/Windows compatibility DLLs on PATH.
        # Let the packager resolve Python/Qt dependencies and the real OS DLLs.
        environment["PATH"] = os.pathsep.join(
            map(
                str,
                (
                    Path(sys.executable).parent,
                    Path(sys.base_prefix),
                    windows / "System32",
                    windows,
                ),
            )
        )
    subprocess.run(command, cwd=ROOT, check=True, env=environment)
    if sys.platform == "darwin":
        # Native privacy metadata and local ad-hoc signing. Developer ID signing
        # and notarization are separate release steps, never simulated here.
        bundle = ROOT / "dist" / "TripleSense.app"
        import plistlib

        info_path = bundle / "Contents" / "Info.plist"
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
        info.update(
            {
                "CFBundleIdentifier": "me.dsshine.app",
                "CFBundleVersion": __version__,
                "CFBundleShortVersionString": __version__,
                "NSLocalNetworkUsageDescription": "Find and connect to your TripleSense server.",
                "NSBonjourServices": ["_dsshine._tcp"],
                "NSBluetoothAlwaysUsageDescription": "Connect your DualSense to your game PC.",
                "NSMicrophoneUsageDescription": (
                    "Forward the controller microphone when controller audio is enabled."
                ),
            }
        )
        with info_path.open("wb") as stream:
            plistlib.dump(info, stream)
        native_helper = bundle / "Contents/MacOS/dsshine-bluetooth"
        subprocess.run(
            [
                "clang",
                "-O2",
                "-Wall",
                "-Wextra",
                "-fobjc-arc",
                "-framework",
                "AppKit",
                "-framework",
                "CoreBluetooth",
                "-framework",
                "IOBluetooth",
                str(ROOT / "src/native/macos_bluetooth.m"),
                "-o",
                str(native_helper),
            ],
            check=True,
        )
        subprocess.run([str(native_helper), "--version"], check=True)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
        subprocess.run(
            [
                "ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(bundle),
                str(ROOT / "dist" / "TripleSense-macOS.zip"),
            ],
            check=True,
        )
        image_root = ROOT / "build" / "mac-installer"
        if image_root.exists():
            shutil.rmtree(image_root)
        image_root.mkdir(parents=True)
        shutil.copytree(bundle, image_root / "TripleSense.app", symlinks=True)
        (image_root / "Applications").symlink_to("/Applications", target_is_directory=True)
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                "TripleSense",
                "-srcfolder",
                str(image_root),
                "-format",
                "UDZO",
                "-ov",
                str(ROOT / "dist" / "TripleSense-macOS.dmg"),
            ],
            check=True,
        )
    elif sys.platform == "linux":
        from package_linux import package_linux

        package_linux()
    elif args.installer:
        compiler = shutil.which("ISCC.exe")
        for base in (Path.home() / "AppData/Local/Programs", Path("C:/Program Files (x86)")):
            candidate = base / "Inno Setup 6" / "ISCC.exe"
            if not compiler and candidate.is_file():
                compiler = str(candidate)
        if not compiler:
            parser.error("Install Inno Setup 6 to compile the Windows setup")
        subprocess.run(
            [
                compiler,
                "/DBundleDir=" + str(ROOT / "dist" / "TripleSense"),
                "/DProjectRoot=" + str(ROOT),
                "/DAppVersion=" + __version__,
                str(ROOT / "packaging" / "windows.iss"),
            ],
            check=True,
        )
    executable = (
        ROOT / "dist" / "TripleSense.app/Contents/MacOS/TripleSense"
        if sys.platform == "darwin"
        else ROOT
        / "dist"
        / "TripleSense"
        / ("TripleSense.exe" if sys.platform == "win32" else "TripleSense")
    )
    # Validate the frozen dependency stack and GUI, not just PyInstaller's exit
    # status. No hardware is opened; each smoke run uses isolated temporary data.
    with tempfile.TemporaryDirectory(prefix="dsshine-build-") as temporary:
        preview = Path(temporary) / "window.png"
        smoke_environment = environment.copy()
        smoke_environment["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
        subprocess.run(
            [
                str(executable),
                "--data-dir",
                str(Path(temporary) / "data"),
                "--smoke-test",
                str(preview),
            ],
            check=True,
            timeout=30,
            env=smoke_environment,
        )
        if not preview.is_file():
            raise RuntimeError("The packaged application did not complete its launch check")
        metadata = json.loads(preview.with_suffix(".json").read_text())
        if not metadata.get("icon_valid"):
            raise RuntimeError("The packaged application icon is missing")
        if sys.platform == "win32" and metadata.get("windows_app_id") != "me.dsshine.app":
            raise RuntimeError("The packaged Windows taskbar identity is incorrect")
        if sys.platform == "win32":
            shell = metadata.get("window_shell", {})
            if (
                shell.get("app_id") != "me.dsshine.app"
                or not shell.get("relaunch_icon", "").endswith("dsshine.ico,0")
                or not Path(shell["relaunch_icon"][:-2]).is_file()
                or "TripleSense.exe" not in shell.get("relaunch_command", "")
                or shell.get("display_name") != "TripleSense"
            ):
                raise RuntimeError("The packaged taskbar icon/relaunch properties are incorrect")


if __name__ == "__main__":
    main()
