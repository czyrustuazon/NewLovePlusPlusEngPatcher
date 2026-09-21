#!/usr/bin/env python3
"""Rebuild release/bake_img.bin from vanilla + PNG pack + TRB + deploy chrome + SMS.

Self-contained (no Azahar required):

  vanilla img.bin
    → pack_images (assets/images)           # stamp mismatch: from-scratch (--no-cache)
    → rebuild textresource_jpn.trb from assets/textresource/translations.json
    → ordered deploy_*_en.py chrome (+ day-counter resident TRB)
    → sync TRBs into release/romfs_overlay
    → release/bake_img.bin
    → release/bake_stamp.txt (PATCHER_RELEASE + UI PNG fingerprint; Drop ignores leftover bake if mismatch)
    → release/name_input_code.bin (Profile romaji stack; drop-bat --inject-code)

Usage:
  python tools/rebuild_bake_img.py
  python tools/rebuild_bake_img.py --rom game.cia|.3ds|.cci   # extract vanilla from ROM
  python tools/rebuild_bake_img.py --skip-pack          # keep bake; re-run TRB/deploys/SMS
  python tools/rebuild_bake_img.py --reseed-from-pack   # force bake <- cache/new_img.bin
  python tools/rebuild_bake_img.py --use-cache          # reuse cache/img_pack (off during RC)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from extract_vanilla_from_rom import resolve_vanilla_img  # noqa: E402
from nlpp_paths import (  # noqa: E402
    ASSETS_TEXTRESOURCE,
    BAKE_IMG,
    CACHE,
    CACHE_NEW_IMG,
    NAME_INPUT_CODE,
    OUT_CIA,
    OVERLAY_TRB_DIR,
    RELEASE,
    TEXTRESOURCE,
    TRANSLATIONS_JSON,
    find_vanilla_code,
    find_vanilla_main_trb,
    find_vanilla_resident_trb,
    require_translations_json,
)
from patch_cia import PatchError, cleanup_out_dir  # noqa: E402
from patcher_version import PATCHER_RELEASE, write_bake_stamp  # noqa: E402
from run_timer import RunTimer  # noqa: E402
from scratch_cleanup import remove_scratch  # noqa: E402

# Shared-ARC-safe order (canonical last-writers for 5238/5190/5237/5380/5245/…).
DEPLOY_SCRIPTS: list[str] = [
    "deploy_msel_options_en.py",
    "deploy_msel_opt_plates_en.py",
    "deploy_msel_menus_en.py",
    "deploy_confirm_btn_en.py",
    "deploy_softkey_back_next_en.py",  # 5238 after Confirm OK
    "deploy_softkey_quit_en.py",  # 5238 やめる → Quit
    "deploy_softkey_defaults_en.py",  # 5238 last-writer: 初期設定 → Restore Default
    "deploy_display_settings_en.py",
    "deploy_optionpassword_en.py",  # 5251 Pass_Win01 (unique pkg; after Options chrome)
    # sound_settings is a subset of display_settings — skip by default
    "deploy_profile_en.py",
    "deploy_card_flist_en.py",
    "deploy_status_stats_en.py",
    "deploy_myroom_main_en.py",
    # NLPP English UI Buttons bundle (keyboard 5190, SysPopup, scoped Back, Album delete).
    "deploy_ui_buttons_en.py",
    "deploy_mail_home_en.py",
    "deploy_mydata_en.py",
    "deploy_todo_en.py",
    "deploy_todo_hist_en.py",
    "deploy_schedule_header_en.py",
    "deploy_day_counter_en.py",
    "deploy_datadelete_en.py",  # 4187 + 5237 Text05
    "deploy_multiwin_headers_en.py",  # 5237 after datadelete (keeps Text05)
    "deploy_gallery_common_en.py",  # 5153
    "deploy_ui_buttons_en.py",  # 5190/5259/5380/4149 after myroom/mydata
    "deploy_input_keyboard_en.py",  # 5190 mode tabs (last-writer vs ui_buttons)
    "deploy_myroom_options_en.py",  # 5380+5575 in-room Options overlay (after shared-ARC writers)
    # Hub main-menu rows + Eng Patch badge (Title.arc) — replaces labels-only deploy.
    "deploy_title_engpatch_en.py",
    "deploy_cesa_en.py",
]


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("\n==>", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(ROOT), env=env)


def sync_trb_overlay() -> None:
    """Copy durable TRBs into the RomFS overlay used by patch_cia."""
    OVERLAY_TRB_DIR.mkdir(parents=True, exist_ok=True)
    TEXTRESOURCE.mkdir(parents=True, exist_ok=True)
    names = (
        "textresource_jpn.trb",
        "textresource_resident_jpn.trb",
        "textresource_config.trb",
        "translations.json",
    )
    for name in names:
        src = TEXTRESOURCE / name
        if not src.is_file():
            continue
        dest = OVERLAY_TRB_DIR / name
        shutil.copy2(src, dest)
        print(f"[trb] overlay <- {src.name}", flush=True)


def rebuild_main_trb(*, env: dict[str, str] | None = None) -> None:
    """Regenerate textresource_jpn.trb (+ config) from translations.json.

    Uses the name-input filter (skip single kana/CJK keys) so gojūon cells stay
    JP glyphs for DrawCell/romaji — full EN TRB blanks the Profile keyboard.
    See tools/deploy_name_kanji_trb.py / technical.md §17.
    """
    translations = require_translations_json()
    vanilla_trb = find_vanilla_main_trb()
    if vanilla_trb is None:
        raise SystemExit(
            "vanilla textresource_jpn.trb not found.\n"
            "Pass --rom path\\to\\game.cia|.3ds|.cci, or set NLPP_VANILLA_TRB."
        )

    TEXTRESOURCE.mkdir(parents=True, exist_ok=True)
    ASSETS_TEXTRESOURCE.mkdir(parents=True, exist_ok=True)

    # Keep commit-worthy source and release working copy in sync.
    if translations.resolve() != TRANSLATIONS_JSON.resolve():
        shutil.copy2(translations, TRANSLATIONS_JSON)
        translations = TRANSLATIONS_JSON
    shutil.copy2(translations, TEXTRESOURCE / "translations.json")

    # Name-input-safe rebuild (filters kana/CJK single-glyph EN glosses).
    # Pass env so NLPP_VANILLA_TRB from --rom / cache/vanilla_from_rom is visible.
    run(
        [
            sys.executable,
            str(ROOT / "tools" / "deploy_name_kanji_trb.py"),
        ],
        env=env,
    )
    namekanji = ROOT / "out" / "textresource_jpn_namekanji.trb"
    namekanji_cfg = ROOT / "out" / "textresource_config_namekanji.trb"
    if not namekanji.is_file():
        raise SystemExit(f"name-kanji TRB rebuild did not write {namekanji}")
    out_trb = TEXTRESOURCE / "textresource_jpn.trb"
    out_cfg = TEXTRESOURCE / "textresource_config.trb"
    shutil.copy2(namekanji, out_trb)
    if namekanji_cfg.is_file():
        shutil.copy2(namekanji_cfg, out_cfg)
    print(f"[trb] name-kanji main TRB -> {out_trb}", flush=True)
    remove_scratch(namekanji, label="name-kanji TRB temp")
    remove_scratch(namekanji_cfg, label="name-kanji TRB config temp")

    # Resident TRB is not rebuilt from translations.json; seed virgin bytes for
    # deploy_day_counter_en.py (日目 → Day) when release/ lacks it.
    resident_out = TEXTRESOURCE / "textresource_resident_jpn.trb"
    if not resident_out.is_file():
        vanilla_resident = find_vanilla_resident_trb()
        if vanilla_resident is None:
            raise SystemExit(
                "vanilla textresource_resident_jpn.trb not found.\n"
                "Pass --rom path\\to\\game.cia|.3ds|.cci, or set NLPP_VANILLA_RESIDENT_TRB."
            )
        shutil.copy2(vanilla_resident, resident_out)
        print(f"[trb] seeded resident TRB -> {resident_out}", flush=True)


def pack_ui(
    vanilla: Path,
    *,
    workers: int | None,
    fine_tune: bool,
    no_cache: bool = False,
    cache_dir: Path | None = None,
    pkg_workers: int | None = None,
    keep_work: bool = False,
) -> Path:
    """PNG pack → cache/new_img.bin (optional intermediate), then copy to bake."""
    CACHE.mkdir(parents=True, exist_ok=True)
    RELEASE.mkdir(parents=True, exist_ok=True)
    work = ROOT / "out" / "rebuild_bake_img_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(ROOT / "src" / "pack_images.py"),
        "--img-bin",
        str(vanilla),
        "--images",
        str(ROOT / "assets" / "images"),
        "--out",
        str(CACHE_NEW_IMG),
        "--work",
        str(work),
    ]
    if workers is not None:
        cmd.extend(["--workers", str(workers)])
    if pkg_workers is not None:
        cmd.extend(["--pkg-workers", str(pkg_workers)])
    if fine_tune:
        cmd.append("--fine-tune")
    if no_cache:
        cmd.append("--no-cache")
    elif cache_dir is not None:
        cmd.extend(["--cache-dir", str(cache_dir)])
    try:
        run(cmd)
        if not CACHE_NEW_IMG.is_file():
            raise SystemExit(f"pack_images did not write {CACHE_NEW_IMG}")
        shutil.copy2(CACHE_NEW_IMG, BAKE_IMG)
        print(f"[bake] seeded from PNG pack -> {BAKE_IMG}", flush=True)
        if not keep_work:
            # Durable copy is release/bake_img.bin; the cache duplicate is ~680MB.
            remove_scratch(CACHE_NEW_IMG, label="duplicate cache/new_img.bin")
        return BAKE_IMG
    finally:
        if not keep_work:
            remove_scratch(work, label="rebuild_bake_img_work")


def vanilla_bake_bak(bake: Path) -> Path:
    """Sidecar bak used by several deploys for virgin ARC bytes."""
    return bake.with_suffix(".bin.bak_pre_msel5245")


def seed_vanilla_bak(vanilla: Path, bake: Path) -> None:
    """Sidecar bak used by several deploys for virgin ARC bytes."""
    bak = vanilla_bake_bak(bake)
    shutil.copy2(vanilla, bak)
    print(f"[bake] vanilla bak -> {bak}", flush=True)


def cleanup_rebuild_scratch(*, keep_work: bool) -> None:
    """Wipe deploy/pack temps under out/ after each rebuild step."""
    if keep_work:
        return
    cleanup_out_dir(out_cia=OUT_CIA, quiet=True)


def format_rebuild_ok_lines(
    *,
    bake: Path,
    cache_new: Path | None,
    main_trb: Path,
    overlay: Path,
    name_code: Path,
    stamp: Path,
    elapsed: str,
    started_at: str,
) -> list[str]:
    """Final gold-rebuild summary printed to the terminal and the rebuild log."""
    lines = [
        "[rebuild] OK",
        f"  gold bake:     {bake}",
    ]
    if cache_new is not None:
        lines.append(f"  PNG optional:  {cache_new}")
    lines.extend(
        [
            f"  main TRB:      {main_trb}",
            f"  TRB overlay:   {overlay}",
            f"  name-input:    {name_code}",
            f"  bake stamp:    {stamp} ({PATCHER_RELEASE})",
            f"  time:          {elapsed}  (started {started_at})",
            "Drop a CIA on the bat to build the EN CIA.",
        ]
    )
    return lines


def write_rebuild_log(
    lines: list[str],
    *,
    elapsed: str,
    started_at: str,
    logs_dir: Path | None = None,
    when: datetime | None = None,
) -> Path | None:
    """Write gold-rebuild summary to ``out/logs/rebuild_*.txt`` + ``rebuild_latest.txt``.

    Survives ``cleanup_out_dir`` (``logs/`` is kept). Never raises.
    """
    dest = logs_dir if logs_dir is not None else ROOT / "out" / "logs"
    now = when or datetime.now()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"rebuild_{now.strftime('%Y%m%d_%H%M%S')}.txt"
        header = [
            f"New Love Plus+ English Patcher  {PATCHER_RELEASE}",
            "Gold rebuild",
            f"Logged:  {now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Started: {started_at}",
            f"Time:    {elapsed}",
            "",
        ]
        text = "\n".join(header + lines).rstrip() + "\n"
        path.write_text(text, encoding="utf-8")
        latest = dest / "rebuild_latest.txt"
        if path.resolve() != latest.resolve():
            latest.write_text(text, encoding="utf-8")
        return path
    except OSError as exc:
        print(f"[log] warning: could not write rebuild log: {exc}", flush=True)
        return None


def build_name_input_code(*, rom: Path | None) -> Path:
    """Patch vanilla ExeFS code.bin → release/name_input_code.bin for CIA inject.

    Always required for a complete gold bake. Retries extract + deploy; never soft-skips.
    """
    from extract_vanilla_from_rom import ensure_vanilla_code_from_rom  # noqa: PLC0415

    def _resolve_src() -> Path:
        src = find_vanilla_code()
        if src is not None:
            return src
        if rom is None:
            raise SystemExit(
                "vanilla exefs/code.bin not found.\n"
                "Pass --rom path\\to\\game.cia|.3ds|.cci (required for from-scratch), "
                "or set NLPP_VANILLA_CODE."
            )
        return ensure_vanilla_code_from_rom(rom, force=False)

    last_exc: BaseException | None = None
    for attempt in range(1, 4):
        try:
            src = _resolve_src()
            RELEASE.mkdir(parents=True, exist_ok=True)
            if NAME_INPUT_CODE.is_file():
                NAME_INPUT_CODE.unlink()
            run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "deploy_name_input_en.py"),
                    "--src",
                    str(src),
                    "--out",
                    str(NAME_INPUT_CODE),
                ]
            )
            if not NAME_INPUT_CODE.is_file():
                raise SystemExit(
                    f"name-input code build did not write {NAME_INPUT_CODE}"
                )
            print(f"[name-input] -> {NAME_INPUT_CODE}", flush=True)
            return NAME_INPUT_CODE
        except (SystemExit, PatchError, OSError, subprocess.CalledProcessError) as exc:
            last_exc = exc
            print(
                f"[retry] name-input code.bin attempt {attempt}/3 failed: {exc}",
                flush=True,
            )
            if attempt < 3:
                # Force re-extract code on next try when ROM is available.
                if rom is not None:
                    try:
                        ensure_vanilla_code_from_rom(rom, force=True)
                    except (PatchError, OSError) as extract_exc:
                        print(
                            f"[retry] force code extract failed: {extract_exc}",
                            flush=True,
                        )
                time.sleep(2.0 * attempt)
    raise SystemExit(
        f"required release/name_input_code.bin failed after 3 attempts: {last_exc}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--vanilla",
        type=Path,
        default=None,
        help="vanilla romfs/img.bin (default: sibling extracted/ or NLPP_VANILLA_IMG)",
    )
    ap.add_argument(
        "--rom",
        type=Path,
        default=None,
        help="extract vanilla img.bin + TRBs from this .cia / .3ds / .cci when needed",
    )
    ap.add_argument(
        "--skip-pack",
        action="store_true",
        help="skip PNG pack; keep existing bake, or seed from cache/new_img.bin if bake missing",
    )
    ap.add_argument(
        "--reseed-from-pack",
        action="store_true",
        help="force-copy cache/new_img.bin over bake before deploys (destructive)",
    )
    ap.add_argument(
        "--skip-deploys",
        action="store_true",
        help="skip deploy_* chrome (still rebuilds main TRB unless --skip-trb)",
    )
    ap.add_argument(
        "--include-sms",
        action="store_true",
        help="deploy English SMS maildic (assets/sms_en/; off by default for JP audit)",
    )
    ap.add_argument(
        "--skip-trb",
        action="store_true",
        help="skip regenerating textresource_jpn.trb from translations.json",
    )
    ap.add_argument(
        "--include-sound-settings",
        action="store_true",
        help="also run deploy_sound_settings_en.py (subset; usually redundant)",
    )
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument(
        "--pkg-workers",
        type=int,
        default=None,
        help="parallel packages for pack_images ProcessPool (default: cpu/2, max 8)",
    )
    ap.add_argument(
        "--fine-tune",
        action="store_true",
        help="opt-in pack_images fine-tune (very slow)",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="from-scratch PNG pack (default during RC; ignore cache/img_pack)",
    )
    ap.add_argument(
        "--use-cache",
        action="store_true",
        help="reuse cache/img_pack (faster). Off by default while we are RC.",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="override pack cache dir (default: cache/img_pack)",
    )
    ap.add_argument(
        "--also-azahar",
        action="store_true",
        help="mirror deploy splices into Azahar LayeredFS when present",
    )
    ap.add_argument(
        "--keep-work",
        action="store_true",
        help="keep pack/deploy scratch under out/ and cache/new_img.bin",
    )
    args = ap.parse_args(argv)

    timer = RunTimer("gold rebuild", heartbeat_s=60.0)
    try:
        return _main_rebuild(args, timer)
    except SystemExit:
        timer.finish(f"gold rebuild stopped (elapsed {timer.elapsed_str()})")
        raise
    except Exception:
        timer.finish("gold rebuild failed")
        raise
    except KeyboardInterrupt:
        timer.finish("gold rebuild aborted")
        raise


def _main_rebuild(args: argparse.Namespace, timer: RunTimer) -> int:
    RELEASE.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    if args.vanilla is not None:
        vanilla = args.vanilla.resolve()
    else:
        try:
            vanilla = resolve_vanilla_img(rom=args.rom.resolve() if args.rom else None)
        except (FileNotFoundError, PatchError, OSError) as exc:
            raise SystemExit(str(exc)) from exc
    if not vanilla.is_file():
        raise SystemExit(f"vanilla img.bin missing: {vanilla}")

    # If we extracted from --rom, also point TRB lookup at the same cache tree.
    env = os.environ.copy()
    env["NLPP_VANILLA_IMG"] = str(vanilla)
    env["NLPP_DEPLOY_IMG"] = str(BAKE_IMG)
    if find_vanilla_main_trb() is None and args.rom is not None:
        raise SystemExit(
            "vanilla textresource_jpn.trb missing after ROM extract. "
            "Re-run with --rom, or set NLPP_VANILLA_TRB."
        )
    trb = find_vanilla_main_trb()
    if trb is not None:
        env["NLPP_VANILLA_TRB"] = str(trb)
    if args.also_azahar:
        env["NLPP_ALSO_AZAHAR"] = "1"
    else:
        env.pop("NLPP_ALSO_AZAHAR", None)

    print(f"[rebuild] vanilla: {vanilla}", flush=True)
    print(f"[rebuild] bake:    {BAKE_IMG}", flush=True)
    keep_work = bool(args.keep_work)

    if args.reseed_from_pack:
        if not CACHE_NEW_IMG.is_file():
            raise SystemExit(f"--reseed-from-pack needs {CACHE_NEW_IMG}")
        shutil.copy2(CACHE_NEW_IMG, BAKE_IMG)
        print(f"[bake] reseeded from PNG pack -> {BAKE_IMG}", flush=True)
        timer.mark("reseeded bake from cache/new_img.bin")
    elif args.skip_pack:
        if BAKE_IMG.is_file():
            print(f"[bake] keeping existing gold bake: {BAKE_IMG}", flush=True)
        elif CACHE_NEW_IMG.is_file():
            shutil.copy2(CACHE_NEW_IMG, BAKE_IMG)
            print(f"[bake] seeded from PNG pack (bake was missing) -> {BAKE_IMG}", flush=True)
            if not keep_work:
                remove_scratch(CACHE_NEW_IMG, label="duplicate cache/new_img.bin")
        else:
            raise SystemExit(
                "no bake and no cache/new_img.bin — run without --skip-pack "
                "or provide release/bake_img.bin"
            )
        timer.mark("skipped PNG pack")
    else:
        print(
            f"[rebuild] RC {PATCHER_RELEASE}: PNG pack is from-scratch "
            "(cache/img_pack ignored). Pass --use-cache to reuse a warm pack.",
            flush=True,
        )
        print(
            "[rebuild] PNG pack starting (historically ~16h; now typically under an hour, "
            "measured ~27 min on a high-thread desktop — empty-block-first + package "
            "ProcessPool + zopfli pad; see technical.md §12.5.3). Watch [timer] lines "
            "for live elapsed.",
            flush=True,
        )
        timer.mark("PNG pack starting")
        timer.stop_heartbeat()  # pack_images has its own [timer] heartbeat
        pack_ui(
            vanilla,
            workers=args.workers,
            pkg_workers=args.pkg_workers,
            fine_tune=args.fine_tune,
            no_cache=(not args.use_cache) or args.no_cache,
            cache_dir=args.cache_dir,
            keep_work=keep_work,
        )
        timer.start_heartbeat()
        timer.mark("PNG pack done")
        cleanup_rebuild_scratch(keep_work=keep_work)

    seed_vanilla_bak(vanilla, BAKE_IMG)

    if not args.skip_trb:
        timer.mark("rebuilding main TRB")
        rebuild_main_trb(env=env)
    sync_trb_overlay()
    cleanup_rebuild_scratch(keep_work=keep_work)

    if not args.skip_deploys:
        scripts = list(DEPLOY_SCRIPTS)
        if args.include_sound_settings:
            idx = scripts.index("deploy_display_settings_en.py") + 1
            scripts.insert(idx, "deploy_sound_settings_en.py")
        timer.mark(f"running {len(scripts)} deploy scripts")
        for name in scripts:
            script = ROOT / "tools" / name
            if not script.is_file():
                raise SystemExit(f"missing deploy script: {script}")
            extra = (
                ["--full"] if name == "deploy_multiwin_headers_en.py" else []
            )
            run([sys.executable, str(script)] + extra, env=env)
            timer.mark(f"deploy done: {name}")
            if name == "deploy_multiwin_headers_en.py":
                # Girlfriend Communication etc. on the live ARC. Pad short zopfli
                # (exact_zlib); do not combine extras into the vanilla --full pass.
                run([sys.executable, str(script)], env=env)
                timer.mark("deploy done: deploy_multiwin_headers_en.py extras")
            cleanup_rebuild_scratch(keep_work=keep_work)

    if args.include_sms:
        en_dir = ROOT / "assets" / "sms_en"
        if not (en_dir / "maildic_m.en.xml").is_file():
            raise SystemExit(
                "assets/sms_en/ missing — run tools/translate_sms_en.py first, "
                "or omit --include-sms"
            )
        timer.mark("SMS maildic deploy")
        run(
            [
                sys.executable,
                str(ROOT / "tools" / "deploy_sms_maildic_en.py"),
                "--img",
                str(BAKE_IMG),
                "--no-backup",
            ],
            env=env,
        )
        cleanup_rebuild_scratch(keep_work=keep_work)

    sync_trb_overlay()
    if not keep_work:
        remove_scratch(vanilla_bake_bak(BAKE_IMG), label="vanilla bake bak")

    timer.mark("building name-input code.bin")
    name_code = build_name_input_code(rom=args.rom.resolve() if args.rom else None)
    if not NAME_INPUT_CODE.is_file():
        raise SystemExit(f"required name-input missing: {NAME_INPUT_CODE}")

    if not BAKE_IMG.is_file():
        raise SystemExit(f"bake missing after rebuild: {BAKE_IMG}")
    main_trb = TEXTRESOURCE / "textresource_jpn.trb"
    if not args.skip_trb and not main_trb.is_file():
        raise SystemExit(f"main TRB missing after rebuild: {main_trb}")
    stamp = write_bake_stamp(packed_assets=not args.skip_pack)
    elapsed = timer.elapsed_str()
    summary = format_rebuild_ok_lines(
        bake=BAKE_IMG,
        cache_new=CACHE_NEW_IMG if CACHE_NEW_IMG.is_file() else None,
        main_trb=main_trb,
        overlay=OVERLAY_TRB_DIR,
        name_code=name_code,
        stamp=stamp,
        elapsed=elapsed,
        started_at=timer.started_at,
    )
    print("\n" + "\n".join(summary), flush=True)
    log_path = write_rebuild_log(
        summary,
        elapsed=elapsed,
        started_at=timer.started_at,
    )
    if log_path is not None:
        print(f"  rebuild log:   {log_path}", flush=True)
    cleanup_rebuild_scratch(keep_work=keep_work)
    timer.finish("gold rebuild OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"error: step failed with exit {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        raise SystemExit(130) from None
