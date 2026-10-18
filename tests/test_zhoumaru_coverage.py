"""Vanilla-rebuilt packages must pack every Zhoumaru ``.check`` master.

These deploys rebuild an ARC from vanilla, so a master they do not list
ships Japanese even though it sits in the pack (Album Search, Mail compose
tabs, 所持リッチ, the WEB header). Each test compares the whole ``.check``
folder against the stems its last-writers touch plus a reviewed exclusion
list. A new master fails here until it is packed or excluded with a reason.
"""

from __future__ import annotations

from pathlib import Path

from conftest import ROOT, TOOLS, load_module

ASSETS = ROOT / "assets" / "images"


def _masters(folder: str) -> set[str]:
    return {
        p.stem
        for p in (ASSETS / folder / "timg").glob("*.png")
        if not p.stem.startswith("new_")
    }


def _stem(path: str) -> str:
    return Path(path).stem


def test_myroom_header_5575_writers_cover_every_master():
    """5575 last-writers: schedule header, then options / map / mini-game."""
    sched = load_module("deploy_schedule_header_en", TOOLS / "deploy_schedule_header_en.py")
    covered = {_stem(p) for p, _en in sched.LABELS}
    later = ("deploy_myroom_options_en", "deploy_map_hub_en", "deploy_minigame_hub_en")
    text = "\n".join((TOOLS / f"{name}.py").read_text(encoding="utf-8") for name in later)
    covered |= {s for s in _masters("MyroomHeader.check") if f"{s}.bclim" in text}
    assert _masters("MyroomHeader.check") - covered == set()


def test_header_masters_skipped_only_when_unusable():
    sched = load_module("deploy_schedule_header_en", TOOLS / "deploy_schedule_header_en.py")
    # Letter-spaced "M y D a t a" / mislabeled "i n b o x".
    assert sched.SKIP_UI_PNG == frozenset({"mydata_toptex_RGBA4", "album_top_tex"})
    assert ("timg/web_toptex_RGBA4.bclim", "WEB") in sched.LABELS


def test_mail_5207_writers_cover_every_master():
    home = load_module("deploy_mail_home_en", TOOLS / "deploy_mail_home_en.py")
    sort = load_module("deploy_mail_sort_en", TOOLS / "deploy_mail_sort_en.py")
    covered = set(home.ZHOUMARU_BUTTONS)
    covered |= {_stem(p) for p, _en in home.CATEGORY_LABELS}  # rendered: bad masters
    covered |= {_stem(p) for p, _en in sort.ETC1_LABELS}
    covered |= {_stem(p) for p in sort.CANCEL_PATHS}
    excluded = {
        "C_Com_icon_Repry2",  # 送信 Send, Zhoumaru painted "Reply"
        "Sel_Tex_ma15_00", "Sel_Tex_ma15_10", "Sel_Tex_ma15_20", "Sel_Tex_ma15_30",
        "Sel_Tex_te05",  # 1x1 stubs
    }
    assert _masters("Mail.check") - covered == excluded


def test_mail_sort_guards_the_zhoumaru_chrome():
    home = load_module("deploy_mail_home_en", TOOLS / "deploy_mail_home_en.py")
    sort = load_module("deploy_mail_sort_en", TOOLS / "deploy_mail_sort_en.py")
    assert {p for p, _en in home.ZHOUMARU_ONLY} <= set(sort.PRESERVE_HOME_PATHS)


def test_mail_home_no_longer_writes_the_header():
    """5575 belongs to deploy_schedule_header_en; mail_home's blue render clobbered it."""
    home = load_module("deploy_mail_home_en", TOOLS / "deploy_mail_home_en.py")
    assert not hasattr(home, "HEADER_LABELS")


def test_album_4149_lists_every_master():
    ui = load_module("deploy_ui_buttons_en", TOOLS / "deploy_ui_buttons_en.py")
    group = next(g for g in ui.GROUPS if g["pkg"] == 4149)
    assert _masters("Album.check") == set(group["stems"])


def test_status_5255_5501_list_every_master():
    stats = load_module("deploy_status_stats_en", TOOLS / "deploy_status_stats_en.py")
    listed = {_stem(p) for _pkg, labels in stats.PKG_LABELS for p, _en in labels}
    excluded = {
        "Scd_Result_FP_Parts01",  # vanilla already reads "Friend Part"
        "main_status", "main_left_bg",  # reference screenshots, identical to vanilla
    }
    masters = _masters("ScdStatus.check") | _masters("KareshiPower.check")
    assert masters - listed == excluded


def test_mydata_5380_buttons_all_zhoumaru():
    mydata = load_module("deploy_mydata_en", TOOLS / "deploy_mydata_en.py")
    mcmn = {s for s in _masters("Myroom.check") if s.startswith("mcmn_tex_")}
    # 5380 is patched live, so pack_images' Tutorial master survives untouched.
    assert mcmn - mydata.ZHOUMARU_BUTTONS == {"mcmn_tex_tutorial_RGBA4"}
