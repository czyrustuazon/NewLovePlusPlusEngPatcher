"""Best-effort scratch deletion so Drop CIA does not hold GB-scale temps until the end."""

from __future__ import annotations

import shutil
import sys
import tempfile
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


def park_outside(path: Path, parent: Path) -> Path:
    """Copy ``path`` out of ``parent`` when it lives there. Otherwise return it.

    From-scratch deletes ``cache/``. A ROM or ``img.bin`` that still sits in
    that tree has to be copied first or the wipe removes the only source.
    """
    path = path.resolve()
    if not path.exists() or not path_is_under(path, parent):
        return path
    hold = Path(tempfile.mkdtemp(prefix="nlpp_from_scratch_"))
    dest = hold / path.name
    print(f"[wipe] parking {path} -> {dest}", flush=True)
    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)
    return dest


def wipe_cia_build_dirs(preserve_rom: Path | None = None) -> Path | None:
    """Delete repo ``out/``, ``release/``, and ``cache/`` before a from-scratch CIA build.

    Returns a parked copy of ``preserve_rom`` when that file lived under one of
    the wiped trees. ``--skip-pack`` must not call this: it still needs ``cache/``.
    """
    from nlpp_paths import CACHE, OUT, RELEASE, ROOT

    parked: Path | None = None
    if preserve_rom is not None and preserve_rom.exists():
        for parent in (CACHE, OUT, RELEASE):
            if path_is_under(preserve_rom, parent):
                parked = park_outside(preserve_rom, parent)
                break

    for path in (OUT, RELEASE, CACHE):
        wipe_directory(path, root=ROOT)
    return parked


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
        help="Delete out/, release/, and cache/ and recreate them empty",
    )
    parser.add_argument(
        "--preserve-rom",
        type=Path,
        default=None,
        help="If this file sits under out/, release/, or cache/, copy it out before the wipe",
    )
    parser.add_argument(
        "--preserve-out",
        type=Path,
        default=None,
        help="Write the parked ROM path here when --preserve-rom had to be copied",
    )
    args = parser.parse_args()
    if not args.wipe_cia_build:
        parser.error("pass --wipe-cia-build")
    parked = wipe_cia_build_dirs(args.preserve_rom)
    if parked is not None and args.preserve_out is not None:
        args.preserve_out.write_text(str(parked), encoding="utf-8")
