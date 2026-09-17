"""Best-effort scratch deletion so Drop CIA does not hold GB-scale temps until the end."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def is_reparse_dir(path: Path) -> bool:
    """True for symlinks / Windows directory junctions (Py3.10-safe)."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            return bool(is_junction())
        except OSError:
            return False
    if sys.platform == "win32" and path.is_dir():
        try:
            import ctypes

            GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
            GetFileAttributesW.argtypes = (ctypes.c_wchar_p,)
            GetFileAttributesW.restype = ctypes.c_uint32
            attrs = GetFileAttributesW(str(path))
            FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            INVALID = 0xFFFFFFFF
            return attrs != INVALID and bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return False
    return False


def path_is_under(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or a descendant (resolved)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def remove_scratch(path: Path | None, *, label: str | None = None) -> None:
    """Delete a scratch file or directory. Never raises."""
    if path is None:
        return
    try:
        if not path.exists():
            return
    except OSError:
        return

    name = label or str(path)
    try:
        if is_reparse_dir(path):
            print(f"[cleanup] removing {name}", flush=True)
            try:
                path.unlink()
            except OSError:
                path.rmdir()
            return
        if path.is_file():
            print(f"[cleanup] removing {name}", flush=True)
            path.unlink()
            return
        if not path.is_dir():
            return
        # Drop nested junctions first so rmtree does not walk an external RomFS.
        romfs = path / "romfs"
        if romfs.exists() and is_reparse_dir(romfs):
            try:
                romfs.unlink()
            except OSError:
                try:
                    romfs.rmdir()
                except OSError:
                    pass
        print(f"[cleanup] removing {name}", flush=True)
        shutil.rmtree(path, ignore_errors=True)
    except OSError as exc:
        print(f"[cleanup] warning: {name}: {exc}", flush=True)
