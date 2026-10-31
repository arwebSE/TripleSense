from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .credentials import generate_pair
from .runtime import host, run_role, source


def port(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("TCP port must be between 1 and 65535")
    return number


def duration(value: str) -> float:
    number = float(value)
    if not 0 < number <= 86400:
        raise argparse.ArgumentTypeError("Duration must be between 0 and 86400 seconds")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="DualSense USB bridge for Sunshine/Moonlight")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--verbose", action="store_true")
    sub = root.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair", help="Generate private source/host TLS credentials")
    pair.add_argument("--out", type=Path, default=Path(".credentials/pair"))
    sub.add_parser("devices", help="List physical standard DualSense controllers")
    probe = sub.add_parser("probe", help="Read real features and input without force effects")
    probe.add_argument("--serial")
    probe.add_argument("--seconds", type=duration, default=3)
    probe.add_argument("--out", type=Path)
    doctor = sub.add_parser("doctor", help="Check runtime, controller and driver executable")
    doctor.add_argument("--usbip")
    src = sub.add_parser("source", help="Run on the PC with the Bluetooth DualSense")
    src.add_argument("--credentials", type=Path, required=True)
    src.add_argument("--bind", default="127.0.0.1")
    src.add_argument("--port", type=port, default=3250)
    src.add_argument("--serial")
    src.add_argument(
        "--mic-mode",
        choices=("pad", "studio"),
        default="pad",
        help="Pad echo cancellation (default), or raw microphone for acoustic measurements",
    )
    src.add_argument("--stats-out", type=Path, help="Write scalar bridge counters on shutdown")
    src.add_argument("--stop-file", type=Path, help="Stop gracefully when this file appears")
    src.add_argument("--synthetic", action="store_true", help="No controller; protocol tests only")
    src.add_argument("--duration", type=duration)
    dst = sub.add_parser("host", help="Run on the Sunshine PC to receive the controller")
    dst.add_argument("--credentials", type=Path, required=True)
    dst.add_argument("--source", required=True, help="Controller PC's address")
    dst.add_argument("--port", type=port, default=3250)
    dst.add_argument("--local-port", type=port, default=3247)
    dst.add_argument(
        "--attach", action="store_true", help="Attach/detach through installed usbip-win2"
    )
    dst.add_argument("--usbip", help="Path to usbip.exe (0.9.8.1 command interface)")
    dst.add_argument("--duration", type=duration)
    dst.add_argument(
        "--ssh", help="Forward to source loopback through an existing user@host SSH login"
    )
    dst.add_argument("--ssh-identity", type=Path)
    dst.add_argument("--ssh-known-hosts", type=Path)
    sun = sub.add_parser("sunshine", help="Export an application entry with start/stop hooks")
    sun.add_argument("--config", type=Path, required=True)
    sun.add_argument("--name", default="Desktop (DualSense)")
    sun.add_argument("--out", type=Path, required=True)
    sun.add_argument(
        "--elevated", action="store_true", help="Request elevated Sunshine prep commands"
    )
    session = sub.add_parser("session", help="Sunshine prep-command session lifecycle")
    session.add_argument("action", choices=("start", "stop", "worker"))
    session.add_argument("--config", type=Path, required=True)
    session.add_argument("--run-dir", type=Path, help=argparse.SUPPRESS)
    return root


def main(argv=None) -> int:
    root = parser()
    args = root.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "pair":
            generate_pair(args.out)
            print(f"Credentials created in {args.out.resolve()}")
            print("Keep source/ on the controller PC; securely copy host/ to the Sunshine PC.")
            print("Keep both private keys private. Certificates expire after one year.")
        elif args.command in ("devices", "probe", "doctor"):
            from .diagnostics import devices, find_usbip, probe

            if args.command == "devices":
                result = devices()
            elif args.command == "doctor":
                try:
                    physical = devices()
                except ImportError:
                    physical = "Controller dependencies absent (install .[controller] on source PC)"
                result = {
                    "python": sys.version.split()[0],
                    "controllers": physical,
                    "usbip": find_usbip(args.usbip),
                }
            else:
                result = probe(args.serial, args.seconds)
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, indent=2))
        elif args.command == "source":
            run_role(source(args))
        elif args.command == "host":
            run_role(host(args))
        elif args.command == "sunshine":
            from .sunshine import export_app

            entry = export_app(args.config, name=args.name, elevated=args.elevated)
            with args.out.open("x", encoding="utf-8") as stream:
                json.dump(entry, stream, indent=2)
                stream.write("\n")
            print(f"Sunshine application entry written to {args.out.resolve()}")
        elif args.command == "session":
            from .sunshine import start_session, stop_session, worker

            if args.action == "start":
                start_session(args.config)
            elif args.action == "stop":
                stop_session(args.config)
            elif args.run_dir:
                worker(args.config, args.run_dir)
            else:
                root.error("session worker requires --run-dir")
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, ImportError, TimeoutError) as exc:
        print(f"ds5driver: {exc}", file=sys.stderr)
        return 1
