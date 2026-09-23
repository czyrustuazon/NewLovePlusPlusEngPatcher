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


def wipe_directory(path: Path, *, root: Path) -> None:
    """Delete ``path`` and recreate it empty. Refuses anything outside ``root``."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or not path_is_under(resolved, root_resolved):
        raise SystemExit(f"[wipe] refusing to delete {resolved}")

    label = resolved.name
    if not resolved.exists():
        resolved.mkdir(parents=True, exist_ok=True)
        print(f"[wipe] {label}/ created empty", flush=True)
        return

    print(f"[wipe] removing {label}/", flush=True)
    try:
        if is_reparse_dir(resolved):
            try:
                resolved.unlink()
            except OSError:
                resolved.rmdir()
        elif resolved.is_file():
            resolved.unlink()
        else:
            romfs = resolved / "romfs"
            if romfs.exists() and is_reparse_dir(romfs):
                try:
                    romfs.unlink()
                except OSError:
                    romfs.rmdir()
            shutil.rmtree(resolved)
    except OSError as exc:
        raise SystemExit(f"[wipe] {label}/: {exc}") from exc

    if resolved.exists():
        raise SystemExit(f"[wipe] {label}/ still exists after delete")
    resolved.mkdir(parents=True, exist_ok=True)
    leftovers = list(resolved.iterdir())
    if leftovers:
        raise SystemExit(f"[wipe] {label}/ not empty: {leftovers[0].name}")
    print(f"[wipe] {label}/ is empty", flush=True)


def wipe_cia_build_dirs() -> None:
    """Delete repo ``out/`` and ``release/`` before a CIA build starts."""
    from nlpp_paths import OUT, RELEASE, ROOT

    for path in (OUT, RELEASE):
        wipe_directory(path, root=ROOT)


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Drop CIA scratch cleanup")
    parser.add_argument(
        "--wipe-cia-build",
        action="store_true",
        help="Delete out/ and release/ and recreate both empty",
    )
    args = parser.parse_args()
    if not args.wipe_cia_build:
        parser.error("pass --wipe-cia-build")
    wipe_cia_build_dirs()
