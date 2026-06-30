"""Runtime configuration, driven by environment variables with local defaults.

This is the single place that knows where things live on disk and which run
mode we are in. Edit here to change paths, the offline flag, or limits.
"""
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent


def _bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _path(name, default):
    return Path(os.environ.get(name, default)).expanduser()


class Config:
    # Run mode. The standalone launcher sets OFFLINE=1 to skip network probes.
    OFFLINE = _bool("TOOLBOX_OFFLINE", False)

    SECRET_KEY = os.environ.get("TOOLBOX_SECRET_KEY", "dev-local-only")
    MAX_CONTENT_LENGTH = int(os.environ.get("TOOLBOX_MAX_UPLOAD_MB", "60")) * 1024 * 1024

    # Working directories. Default to a per-user data dir so the standalone app
    # writes nothing inside the source tree.
    DATA_DIR = _path("TOOLBOX_DATA_DIR", "~/.local/share/sherwood-toolbox")
    UPLOAD_DIR = _path("TOOLBOX_UPLOAD_DIR", "~/.local/share/sherwood-toolbox/uploads")
    ATTACHMENTS_DIR = _path("TOOLBOX_ATTACHMENTS_DIR",
                            "~/.local/share/sherwood-toolbox/attachments")

    # EstimateEnhancer "Add Image Links Fork" helper (wired in step 3).
    FORK_PATH = _path("TOOLBOX_FORK_PATH",
                      str(PKG_DIR / "tools" / "estimate_enhancer" / "fork" / "add_image_links.py"))

    @classmethod
    def ensure_dirs(cls):
        for d in (cls.DATA_DIR, cls.UPLOAD_DIR, cls.ATTACHMENTS_DIR):
            Path(d).mkdir(parents=True, exist_ok=True)
