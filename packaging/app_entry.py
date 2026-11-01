import traceback

from triplesense.app_support import app_directory

try:
    from triplesense.app import main

    # Do not leave a stale failure report after a successful later launch.
    root = app_directory()
    (root / "startup-error.log").unlink(missing_ok=True)
    raise SystemExit(main())
except Exception:
    root = app_directory()
    root.mkdir(parents=True, exist_ok=True)
    (root / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
    raise
