"""Foreground roles and bounded USB/IP attach/detach ownership."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path

from ds5emu.backend import SyntheticBackend
from ds5emu.timing import TimerResolution

from .credentials import tls_context
from .diagnostics import choose_controller, find_usbip, require_controller_isolation
from .latency import controller_activity, interactive_thread
from .ssh import SshForward
from .transport import HostTunnel, SecureSource

log = logging.getLogger(__name__)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def run_usbip(executable: str, *args: str) -> str:
    kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {}
    process = await asyncio.create_subprocess_exec(
        executable,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), 20)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if process.returncode:
        detail = (err + out).decode(errors="replace").strip()
        raise RuntimeError(f"USB/IP command failed ({process.returncode}): {detail}")
    return out.decode(errors="replace").strip()


def attached_port(output: str) -> int:
    # --terse is upstream's stable, numeric result; do not infer from global port lists.
    if not re.fullmatch(r"[1-9][0-9]{0,4}", output) or int(output) > 65535:
        raise RuntimeError(f"Unexpected USB/IP --terse result: {output!r}")
    return int(output)


async def detach_owned(executable: str, port: int, tcp_port: int, serial: str) -> bool:
    listing = await run_usbip(executable, "port")
    blocks = re.findall(r"(?ms)^Port (\d+):.*?(?=^Port \d+:|\Z)", listing)
    if listing and not blocks:
        raise RuntimeError("Unable to verify USB/IP port ownership before cleanup")
    match = re.search(rf"(?ms)^Port 0*{port}:.*?(?=^Port \d+:|\Z)", listing)
    if not match:
        log.info("Owned USB/IP port is already absent")
        return False
    block = match.group()
    if f"-> usbip://127.0.0.1:{tcp_port}/1-1" not in block or not re.search(
        rf"(?m)^\s*-> serial: {re.escape(serial)}\s*$", block
    ):
        log.warning("USB/IP port %d has been reassigned; leaving it alone", port)
        return False
    await run_usbip(executable, "detach", "--port", str(port))
    return True


async def wait_until_stopped(duration: float | None, stop_file: Path | None = None) -> None:
    deadline = asyncio.get_running_loop().time() + duration if duration is not None else None
    while True:
        if stop_file and stop_file.exists():
            return
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            return
        await asyncio.sleep(0.1)


async def source(args) -> None:
    context = tls_context(Path(args.credentials), server=True)
    if args.synthetic:
        backend = SyntheticBackend()
    else:
        require_controller_isolation()
        from .controller import ControllerBackend

        selected = choose_controller(args.serial)
        backend = ControllerBackend(serial=selected.serial, mic_mode=args.mic_mode)
    server = SecureSource(backend, context, host=args.bind, port=args.port)
    try:
        await server.start()
        print(
            f"DualSense source ready on {args.bind}:{server.port} "
            f"({'SYNTHETIC: no hardware' if args.synthetic else 'Bluetooth controller'}; TLS 1.3)",
            flush=True,
        )
        await wait_until_stopped(args.duration, args.stop_file)
    finally:
        await server.stop()
        if args.stats_out and not args.synthetic:
            args.stats_out.parent.mkdir(parents=True, exist_ok=True)
            write_json(
                args.stats_out,
                {
                    "bridge_counters": dict(backend.stats),
                    "bluetooth_clock_seam": backend.clock_seam(),
                    "microphone_mode": args.mic_mode,
                },
            )
        log.info("Source stopped")


async def host(args, *, run_dir: Path | None = None) -> None:
    context = tls_context(Path(args.credentials), server=False)
    forward = None
    if getattr(args, "ssh", None):
        if args.source != "127.0.0.1":
            raise ValueError("With --ssh, --source must be 127.0.0.1 (on the SSH destination)")
        forward = SshForward(
            args.ssh, args.port, identity=args.ssh_identity, known_hosts=args.ssh_known_hosts
        )
    tunnel = None
    usbip = find_usbip(args.usbip) if args.attach else None
    if args.attach and not usbip:
        raise RuntimeError("Install usbip-win2 on the Sunshine host first, or provide --usbip.")
    owned_port = None
    serial = "DS5D" + uuid.uuid4().hex[:11]
    try:
        if forward:
            await forward.start()
        tunnel = HostTunnel(
            args.source, forward.port if forward else args.port, context, port=args.local_port
        )
        await tunnel.start()
        if usbip:
            output = await run_usbip(
                usbip,
                "--tcp-port",
                str(tunnel.port),
                "attach",
                "--remote",
                "127.0.0.1",
                "--bus-id",
                "1-1",
                "--terse",
                "--once",
                "--serial",
                serial,
            )
            owned_port = attached_port(output)
        print(
            f"Host bridge ready: 127.0.0.1:{tunnel.port} -> {args.source}:{args.port}; "
            f"USB port {owned_port if owned_port else 'not attached'}",
            flush=True,
        )
        if not usbip:
            print(
                f"usbip --tcp-port {tunnel.port} list --remote 127.0.0.1\n"
                f"usbip --tcp-port {tunnel.port} attach --remote 127.0.0.1 "
                "--bus-id 1-1 --terse --once",
                flush=True,
            )
        if run_dir:
            write_json(run_dir / "ready.json", {"tcp_port": tunnel.port, "usb_port": owned_port})
        if usbip:

            async def watch_tunnel():
                while True:
                    await asyncio.sleep(0.25)
                    if not tunnel.handlers:
                        detail = tunnel.last_error or "The controller connection ended."
                        raise RuntimeError(
                            f"USB device disconnected: {detail} Restart the session."
                        )

            watch = asyncio.create_task(watch_tunnel())
            stop = asyncio.create_task(
                wait_until_stopped(args.duration, run_dir / "stop" if run_dir else None)
            )
            try:
                done, _ = await asyncio.wait([watch, stop], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                watch.cancel()
                stop.cancel()
                await asyncio.gather(watch, stop, return_exceptions=True)
        else:
            await wait_until_stopped(args.duration, run_dir / "stop" if run_dir else None)
    finally:
        # Only detach our returned positive port. Never use "detach --all".
        try:
            if owned_port and usbip:
                await detach_owned(usbip, owned_port, tunnel.port, serial)
        finally:
            try:
                if tunnel:
                    await tunnel.stop()
            finally:
                if forward:
                    await forward.stop()
        if run_dir:
            write_json(run_dir / "cleanup.json", {"confirmed": True})


def run_role(coroutine) -> None:
    async def with_loop_policy():
        loop = asyncio.get_running_loop()

        def exception_handler(active_loop, context):
            exception = context.get("exception")
            if (
                isinstance(exception, ConnectionResetError)
                and getattr(exception, "winerror", None) == 10054
                and "_ProactorBasePipeTransport._call_connection_lost" in context.get("message", "")
            ):
                # CPython's Windows pipe cleanup can raise again after an
                # ordinary driver detach. Session errors are reported separately.
                log.debug("Windows transport reset during connection cleanup")
                return
            active_loop.default_exception_handler(context)

        loop.set_exception_handler(exception_handler)
        await coroutine

    with controller_activity(), interactive_thread(), TimerResolution(1):
        asyncio.run(with_loop_policy())
