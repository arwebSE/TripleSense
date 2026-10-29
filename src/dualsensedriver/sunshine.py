"""Sunshine prep-command integration without changing its installed configuration."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .runtime import host, run_role, write_json

WINDOWS_HOST = os.name == "nt"


def load_config(path: Path) -> argparse.Namespace:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"source", "credentials", "usbip"}
    allowed = required | {"port", "local_port"}
    if required - data.keys() or data.keys() - allowed:
        raise ValueError(f"Session config requires {required}; allowed keys: {allowed}")
    for key in required:
        if not isinstance(data[key], str) or not data[key]:
            raise ValueError(f"Session config {key} must be a nonempty string")
    for key in ("credentials", "usbip"):
        value = Path(data[key])
        data[key] = str((path.parent / value).resolve() if not value.is_absolute() else value)
    for key, default in (("port", 3250), ("local_port", 3247)):
        value = data.setdefault(key, default)
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError(f"Invalid TCP port in session config: {key}")
    return argparse.Namespace(**data, attach=True, duration=None)


def state_path(config: Path) -> Path:
    return config.with_suffix(".session.json")


def start_session(config: Path) -> None:
    config = config.resolve()
    load_config(config)  # Validate before creating a lock or child process.
    state = state_path(config)
    run_dir = config.parent / ("run-" + uuid.uuid4().hex)
    run_dir.mkdir(mode=0o700)
    # Exclusive lock: never overwrite another session's ownership record.
    try:
        with state.open("x", encoding="utf-8") as stream:
            json.dump({"run_dir": str(run_dir)}, stream)
    except FileExistsError as exc:
        run_dir.rmdir()
        raise RuntimeError(
            f"Session already exists. Run 'session stop --config {config}' first."
        ) from exc
    command = [
        sys.executable,
        "-m",
        "dualsensedriver",
        "session",
        "worker",
        "--config",
        str(config),
        "--run-dir",
        str(run_dir),
    ]
    options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        with (run_dir / "session.log").open("ab") as logfile:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=logfile, stderr=logfile, **options
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if (run_dir / "done.json").exists():
                raise RuntimeError((run_dir / "done.json").read_text(encoding="utf-8"))
            if (run_dir / "ready.json").exists():
                print(f"DualSense attached for Sunshine. Session log: {run_dir / 'session.log'}")
                return
            if process.poll() is not None:
                raise RuntimeError(
                    f"Bridge exited before attachment. See {run_dir / 'session.log'}"
                )
            time.sleep(0.1)
        raise TimeoutError(f"Bridge did not attach within 30s. See {run_dir / 'session.log'}")
    except BaseException:
        # Request graceful cleanup; do not kill a possibly reused PID.
        (run_dir / "stop").touch()
        # Preserve the ownership file unless shutdown is positively observed.
        if (run_dir / "done.json").exists():
            state.unlink(missing_ok=True)
        raise


def stop_session(config: Path) -> None:
    state = state_path(config.resolve())
    if not state.exists():
        print("No DualSense session to stop.")
        return
    run_dir = Path(json.loads(state.read_text(encoding="utf-8"))["run_dir"])
    (run_dir / "stop").touch()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if (run_dir / "done.json").exists():
            result = json.loads((run_dir / "done.json").read_text(encoding="utf-8"))
            if result.get("error"):
                raise RuntimeError(f"Session cleanup needs inspection: {result['error']}")
            state.unlink(missing_ok=True)
            print("DualSense session stopped and its USB port detached.")
            return
        time.sleep(0.1)
    raise TimeoutError(f"Session has not confirmed cleanup. Inspect {run_dir / 'session.log'}")


def worker(config: Path, run_dir: Path) -> None:
    error = None
    try:
        run_role(host(load_config(config.resolve()), run_dir=run_dir))
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        write_json(run_dir / "done.json", {"error": error})


def export_app(config: Path, *, name: str) -> dict:
    config = config.resolve()
    load_config(config)
    if not WINDOWS_HOST:
        raise RuntimeError("Sunshine command generation currently targets Windows hosts.")

    def command(action):
        return subprocess.list2cmdline(
            [sys.executable, "-m", "dualsensedriver", "session", action, "--config", str(config)]
        )

    return {
        "name": name,
        "cmd": "",
        "image-path": "",
        "prep-cmd": [{"do": command("start"), "undo": command("stop"), "elevated": True}],
    }
