import os
import sys
import traceback
from pathlib import Path

try:
    from dualsensedriver.app import main

    # Do not leave a stale failure report after a successful later launch.
    root = (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DSShine"
        if sys.platform == "win32"
        else Path.home() / "Library/Application Support/DSShine"
    )
    (root / "startup-error.log").unlink(missing_ok=True)
    raise SystemExit(main())
except Exception:
    root = (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DSShine"
        if sys.platform == "win32"
        else Path.home() / "Library/Application Support/DSShine"
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
    raise
