#!/usr/bin/env python3
"""Boot the post-bake LayeredFS build in Azahar and fail on a crash.

Lays out release/ the way ``ab_test/make.ps1 seed-*`` does (img.bin,
name_input_code.bin, romfs_overlay, EN .dbin2) in a throwaway portable Azahar
user folder, boots the ROM, and watches azahar_log.txt.

Fails on: an ARM exception report, unmapped memory access, ERR:f fatal, the
emulator exiting early, or the mod not loading. With --inject, the patched
Azahar (ab_test/patches/azahar-nlpp-emu.patch) replays a real hardware crash
and the run passes only once that hook fired and the game kept going.

  # Windows (A/B Azahar build)
  python tools/smoke_boot_azahar.py --azahar ab_test/azahar_instances/a/azahar.exe --rom path\\to\\game.3ds

  # Headless Linux runner: Xvfb + Mesa llvmpipe software OpenGL
  python3 tools/smoke_boot_azahar.py --azahar /opt/nlpp/azahar/azahar --rom /opt/nlpp/vanilla/rom.3ds \\
      --inject name-walk --seconds 900

Exit code 0 = pass, 1 = fail, 2 = setup problem.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TITLE_ID = "00040000000F4E00"

# name -> (env var for the patched Azahar, log line once the hook fired)
INJECTIONS = {
    "name-walk": ("NLPP_EMU_NAME_WALK_ABORT", "NLPP name-walk: one-shot"),
    "pane-flag": ("NLPP_EMU_PANE_FLAG", "NLPP pane-flag: one-shot"),
    "menu-vt": ("NLPP_EMU_MENU_VT", "NLPP menu-vt: one-shot"),
}

FAILURES = [
    (re.compile(r"Exception Type:"), "ARM exception (data/prefetch abort)"),
    (re.compile(r"NLPP name-walk data abort"), "name-walk guard missing (hardware data abort)"),
    (re.compile(r"[Uu]nmapped (Read|Write)"), "unmapped memory access (crashes on hardware)"),
    (re.compile(r"Service\.ERR <Critical>"), "game raised ERR:f fatal"),
]

REQUIRED = [
    ("overriding built-in ExeFS file", "patched code.bin was not loaded"),
    ("LayeredFS replacement file in use for /img.bin", "bake img.bin was not loaded"),
]

RENDERERS = {"software": 0, "opengl": 1, "vulkan": 2}


@dataclass
class Result:
    failures: list[str] = field(default_factory=list)
    fired: set[str] = field(default_factory=set)
    exited: int | None = None
    seconds: float = 0.0


def install_mod(user: Path, release: Path) -> None:
    for name in ("bake_img.bin", "name_input_code.bin"):
        if not (release / name).is_file():
            raise SystemExit(f"missing {release / name} (bake first, or fetch_release_bake.py)")
    if not (release / "romfs_overlay").is_dir():
        raise SystemExit(f"missing {release / 'romfs_overlay'}")
    mod = user / "load" / "mods" / TITLE_ID
    exefs, romfs = mod / "exefs", mod / "romfs"
    exefs.mkdir(parents=True, exist_ok=True)
    romfs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release / "bake_img.bin", romfs / "img.bin")
    shutil.copyfile(release / "name_input_code.bin", exefs / "code.bin")
    shutil.copyfile(release / "name_input_code.bin", mod / "code.bin")
    shutil.copytree(release / "romfs_overlay", romfs, dirs_exist_ok=True)
    subprocess.run(
        [sys.executable, str(ROOT / "src" / "script_inject.py"), "--layeredfs", str(romfs)],
        check=True,
    )


def write_config(user: Path, renderer: str) -> None:
    cfg = user / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "qt-config.ini").write_text(
        "\n".join(
            [
                "[Miscellaneous]",
                "check_for_update_on_start\\default=false",
                "check_for_update_on_start=false",
                "[UI]",
                "confirmClose\\default=false",
                "confirmClose=false",
                "firstStart\\default=false",
                "firstStart=false",
                # Off by default, and then an abort never writes "Exception Type:".
                "[Debugging]",
                "enable_exception_handler\\default=false",
                "enable_exception_handler=true",
                "[Renderer]",
                "graphics_api\\default=false",
                f"graphics_api={RENDERERS[renderer]}",
                "[Audio]",
                "output_type\\default=false",
                "output_type=1",  # null sink: the runner has no sound card
                "",
            ]
        ),
        encoding="utf-8",
    )


def prepare_exe(azahar: Path, work: Path) -> tuple[Path, Path]:
    """Return (exe, cwd) such that Azahar uses work/user as its user folder.

    Windows reads <exe dir>/user, so the exe folder is copied into work/.
    Linux reads <cwd>/user, so the binary or AppImage runs from work/.
    """
    if os.name == "nt":
        for item in azahar.parent.iterdir():
            if item.name == "user" or item.suffix in (".bat", ".txt"):
                continue
            dest = work / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copyfile(item, dest)
        return work / azahar.name, work
    return azahar, work


def launch_cmd(exe: Path, rom: Path) -> list[str]:
    cmd = [str(exe), str(rom)]
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        if shutil.which("xvfb-run") is None:
            raise SystemExit("no DISPLAY and no xvfb-run (sudo apt-get install xvfb)")
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", *cmd]
    return cmd


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass


def scan(text: str, inject: list[str], result: Result) -> None:
    for pat, why in FAILURES:
        m = pat.search(text)
        if m and not any(f.startswith(why + ":") for f in result.failures):
            line = text[text.rfind("\n", 0, m.start()) + 1 : text.find("\n", m.end())]
            result.failures.append(f"{why}: {line.strip()[:200]}")
    for name in inject:
        if INJECTIONS[name][1] in text:
            result.fired.add(name)


def run(args) -> tuple[Result, str]:
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    user = work / "user"
    user.mkdir(parents=True)
    install_mod(user, args.release.resolve())
    write_config(user, args.renderer)
    if args.seed_user:
        # Without a save the game waits on its create-save prompt forever.
        for sub in ("sdmc", "nand"):
            if (args.seed_user / sub).is_dir():
                shutil.copytree(args.seed_user / sub, user / sub, dirs_exist_ok=True)
    exe, cwd = prepare_exe(args.azahar.resolve(), work)

    env = dict(os.environ)
    if args.dll_dir:
        env["PATH"] = str(args.dll_dir) + os.pathsep + env.get("PATH", "")
    for name in args.inject:
        env[INJECTIONS[name][0]] = "1"
    if args.renderer == "opengl" and os.name != "nt" and not os.environ.get("DISPLAY"):
        env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")  # Mesa llvmpipe under Xvfb

    log = user / "log" / "azahar_log.txt"
    cmd = launch_cmd(exe, args.rom.resolve())
    print(f"[smoke] {' '.join(cmd)}  (inject: {', '.join(args.inject) or 'none'})", flush=True)
    result = Result()
    start = time.monotonic()
    all_fired_at: float | None = None
    with open(work / "azahar_stdout.txt", "wb") as out:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        try:
            while True:
                time.sleep(2)
                elapsed = time.monotonic() - start
                text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
                scan(text, args.inject, result)
                if result.failures:
                    break
                if proc.poll() is not None:
                    result.exited = proc.returncode
                    break
                if args.inject and len(result.fired) == len(args.inject):
                    all_fired_at = all_fired_at or elapsed
                    if elapsed - all_fired_at >= args.settle:
                        break
                if elapsed >= args.seconds:
                    break
        finally:
            stop(proc)
    result.seconds = time.monotonic() - start
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    scan(text, args.inject, result)
    if log.is_file():
        shutil.copyfile(log, work / "azahar_log.txt")
    return result, text


def verdict(result: Result, text: str, inject: list[str]) -> list[str]:
    problems = list(result.failures)
    if result.exited is not None:
        problems.append(f"Azahar exited early (code {result.exited}); see azahar_stdout.txt")
    if not text:
        problems.append("no azahar_log.txt was written")
    for marker, why in REQUIRED:
        if text and marker not in text:
            problems.append(why)
    for name in inject:
        if name not in result.fired:
            problems.append(
                f"{name} hook never fired (boot did not reach it in time, or this "
                "Azahar lacks ab_test/patches/azahar-nlpp-emu.patch)"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--azahar", type=Path, required=True, help="azahar.exe, Linux binary, or AppImage")
    ap.add_argument("--rom", type=Path, default=Path(os.environ["NLPP_ROM"]) if os.environ.get("NLPP_ROM") else None)
    ap.add_argument("--release", type=Path, default=ROOT / "release")
    ap.add_argument("--work", type=Path, default=ROOT / "out" / "smoke")
    ap.add_argument("--seconds", type=float, default=300, help="wall-clock budget (slow CPUs need more)")
    ap.add_argument("--settle", type=float, default=30, help="keep running this long after all hooks fired")
    ap.add_argument("--inject", default="", help=f"comma list: {', '.join(INJECTIONS)}")
    ap.add_argument("--renderer", choices=sorted(RENDERERS), default="opengl")
    ap.add_argument(
        "--seed-user",
        type=Path,
        default=Path(os.environ["NLPP_SMOKE_SEED_USER"]) if os.environ.get("NLPP_SMOKE_SEED_USER") else None,
        help="Azahar user folder whose sdmc/ + nand/ (title save) are copied in first",
    )
    ap.add_argument(
        "--dll-dir",
        type=Path,
        default=Path(os.environ["NLPP_MSYS_BIN"]) if os.environ.get("NLPP_MSYS_BIN") else None,
        help="prepended to PATH for Azahar only (Windows MSYS2 Qt DLLs; default NLPP_MSYS_BIN)",
    )
    args = ap.parse_args(argv)

    args.inject = [s for s in (x.strip() for x in args.inject.split(",")) if s]
    unknown = [s for s in args.inject if s not in INJECTIONS]
    if unknown:
        ap.error(f"unknown --inject {unknown}")
    if args.rom is None or not args.rom.is_file():
        print(f"[smoke] ROM not found: {args.rom} (pass --rom or set NLPP_ROM)", file=sys.stderr)
        return 2
    if not args.azahar.is_file():
        print(f"[smoke] Azahar not found: {args.azahar}", file=sys.stderr)
        return 2

    result, text = run(args)
    problems = verdict(result, text, args.inject)
    work = args.work.resolve()
    if problems:
        print(f"[smoke] FAIL after {result.seconds:.0f}s (log: {work / 'azahar_log.txt'})")
        for p in problems:
            print(f"  - {p}")
        return 1
    fired = f"; hooks fired: {', '.join(sorted(result.fired))}" if result.fired else ""
    print(f"[smoke] PASS after {result.seconds:.0f}s{fired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
