"""Azahar LayeredFS sandbox — wipe mod overlay and deploy one test profile."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from nlpp_paths import (
    AZAHAR_MOD_CODE,
    AZAHAR_MOD_EXEFS,
    AZAHAR_MOD_IMG,
    AZAHAR_MOD_ROOT,
    AZAHAR_MOD_ROMFS,
    BAKE_IMG,
    OUT,
    ROOT,
    find_vanilla_img,
    require_vanilla_code,
    require_vanilla_img,
)

BACKUP_ROOT = OUT / "azahar_sandbox_backups"
LATEST_LINK = BACKUP_ROOT / "latest"


@dataclass(frozen=True)
class DeployStep:
    script: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class SandboxProfile:
    name: str
    description: str
    seed_code: bool = True
    seed_img: str = "vanilla"  # vanilla | bake | none
    deploy: tuple[DeployStep, ...] = ()


PROFILES: dict[str, SandboxProfile] = {
    "vanilla": SandboxProfile(
        name="vanilla",
        description="Wipe mod; seed vanilla code.bin + img.bin only (no EN patches).",
        seed_code=True,
        seed_img="vanilla",
        deploy=(),
    ),
    "name_input": SandboxProfile(
        name="name_input",
        description="Profile First Name: Hepburn gojuon + direct romaji insert (no kanji list).",
        seed_code=True,
        seed_img="vanilla",
        deploy=(
            DeployStep("tools/deploy_name_input_en.py"),
        ),
    ),
    "name_input_keyboard": SandboxProfile(
        name="name_input_keyboard",
        description="name_input + EN mode-tab labels (Input pkg 5190).",
        seed_code=True,
        seed_img="vanilla",
        deploy=(
            DeployStep("tools/deploy_name_input_en.py"),
            DeployStep("tools/deploy_input_keyboard_en.py"),
        ),
    ),
}


def list_profiles() -> None:
    print("Azahar sandbox profiles:\n")
    for key in sorted(PROFILES):
        p = PROFILES[key]
        steps = ", ".join(s.script for s in p.deploy) or "(seed only)"
        print(f"  {key:22} {p.description}")
        print(f"{'':22} img={p.seed_img}  deploy: {steps}\n")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def archive_mod(mod_root: Path, dest: Path) -> Path | None:
    """Copy entire mod folder to dest. Returns dest if anything was archived."""
    if not mod_root.exists():
        return None
    has_content = any(mod_root.iterdir()) if mod_root.is_dir() else False
    if not has_content:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(mod_root, dest)
    return dest


def wipe_mod(mod_root: Path, *, dry_run: bool = False) -> list[str]:
    """Remove exefs/, romfs/, root code.bin, and all code.bin backups."""
    removed: list[str] = []

    def _rm_path(p: Path) -> None:
        if not p.exists():
            return
        removed.append(str(p))
        if dry_run:
            return
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()

    for name in ("exefs", "romfs"):
        _rm_path(mod_root / name)
    for p in sorted(mod_root.glob("code.bin*")):
        _rm_path(p)

    if not dry_run:
        mod_root.mkdir(parents=True, exist_ok=True)
        (mod_root / "exefs").mkdir(parents=True, exist_ok=True)
        (mod_root / "romfs").mkdir(parents=True, exist_ok=True)

    return removed


def seed_code(mod_root: Path, src: Path, *, dry_run: bool = False) -> None:
    exefs = mod_root / "exefs"
    dest = exefs / "code.bin"
    root_copy = mod_root / "code.bin"
    print(f"[sandbox] seed code.bin <- {src}", flush=True)
    if dry_run:
        return
    exefs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    shutil.copy2(src, root_copy)


def seed_img(mod_root: Path, src: Path, *, dry_run: bool = False) -> None:
    dest = mod_root / "romfs" / "img.bin"
    print(f"[sandbox] seed img.bin <- {src}", flush=True)
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def resolve_img_seed(kind: str) -> Path:
    if kind == "none":
        raise ValueError("seed_img=none skips img seeding")
    if kind == "vanilla":
        return require_vanilla_img()
    if kind == "bake":
        if not BAKE_IMG.is_file():
            raise FileNotFoundError(
                f"bake img missing: {BAKE_IMG}\nRun tools/rebuild_bake_img.py first."
            )
        return BAKE_IMG.resolve()
    raise ValueError(f"unknown seed_img: {kind!r}")


def run_deploy_step(step: DeployStep, *, dry_run: bool = False) -> None:
    script_path = ROOT / step.script
    if not script_path.is_file():
        raise FileNotFoundError(f"deploy script missing: {script_path}")
    cmd = [sys.executable, str(script_path), *step.args]
    print("[sandbox] deploy:", " ".join(cmd))
    if dry_run:
        return
    env = os.environ.copy()
    # Sandbox already targets Azahar; avoid mirroring into bake/release.
    env.setdefault("NLPP_ALSO_AZAHAR", "0")
    env.setdefault("NLPP_DEPLOY_IMG", str(AZAHAR_MOD_IMG))
    subprocess.check_call(cmd, cwd=ROOT, env=env)


def apply_profile(
    profile: SandboxProfile,
    *,
    mod_root: Path = AZAHAR_MOD_ROOT,
    archive: bool = True,
    dry_run: bool = False,
) -> Path | None:
    backup_dir: Path | None = None
    if archive:
        backup_dir = BACKUP_ROOT / _timestamp()
        print(f"[sandbox] archive -> {backup_dir}")
        archived = archive_mod(mod_root, backup_dir)
        if archived and not dry_run:
            BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
            if LATEST_LINK.exists() or LATEST_LINK.is_symlink():
                LATEST_LINK.unlink()
            try:
                LATEST_LINK.symlink_to(backup_dir.name, target_is_directory=True)
            except OSError:
                # Windows may need admin for symlinks; write pointer file instead.
                LATEST_LINK.write_text(backup_dir.name, encoding="utf-8")
        elif not archived:
            print("[sandbox] mod folder empty/missing; nothing archived")

    removed = wipe_mod(mod_root, dry_run=dry_run)
    if removed:
        print(f"[sandbox] wiped {len(removed)} path(s)")
    else:
        print("[sandbox] nothing to wipe (fresh mod folder)")

    if profile.seed_code:
        vanilla_code = require_vanilla_code()
        seed_code(mod_root, vanilla_code, dry_run=dry_run)

    if profile.seed_img != "none":
        img_src = resolve_img_seed(profile.seed_img)
        seed_img(mod_root, img_src, dry_run=dry_run)

    for step in profile.deploy:
        run_deploy_step(step, dry_run=dry_run)

    if not dry_run:
        print("\n[sandbox] done.")
        print(f"  mod root: {mod_root}")
        if profile.seed_code:
            print(f"  code.bin: {AZAHAR_MOD_CODE}")
        if profile.seed_img != "none":
            print(f"  img.bin:  {AZAHAR_MOD_IMG}")
        if backup_dir is not None:
            print(f"  backup:   {backup_dir}")
        print("  Fully quit Azahar before testing.")
    return backup_dir


def restore_mod(src: Path, *, mod_root: Path = AZAHAR_MOD_ROOT, dry_run: bool = False) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"backup not found: {src}")
    print(f"[sandbox] restore {src} -> {mod_root}")
    if dry_run:
        return
    wipe_mod(mod_root)
    mod_root.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        dest = mod_root / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    print("[sandbox] restore complete. Fully quit Azahar.")


def resolve_backup(path: str | None) -> Path:
    if path is None or path.lower() in ("latest", ""):
        if LATEST_LINK.is_symlink():
            return (BACKUP_ROOT / os.readlink(LATEST_LINK)).resolve()
        if LATEST_LINK.is_file():
            name = LATEST_LINK.read_text(encoding="utf-8").strip()
            return (BACKUP_ROOT / name).resolve()
        backups = sorted(BACKUP_ROOT.glob("*"), reverse=True) if BACKUP_ROOT.is_dir() else []
        if not backups:
            raise FileNotFoundError(f"no backups under {BACKUP_ROOT}")
        return backups[0]
    p = Path(path)
    if not p.is_absolute():
        p = BACKUP_ROOT / p
    return p.resolve()
