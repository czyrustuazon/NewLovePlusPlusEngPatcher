"""UI PNGs we edited ourselves must survive a new Zhoumaru drop.

``assets/images/LOCAL_EDITS.json`` lists every ``*.check`` PNG EngPatcher
changed after the Zhoumaru import (7ce3dd3). The d201351 pack update silently
put back Zhoumaru's "Apply" camera tab, the "Youth Story" Drama Gallery bar,
and the old Camera Settings note. A changed blob fails here; re-apply our edit
or, if the new Zhoumaru file is better, update the entry with a reason.
"""

from __future__ import annotations

import hashlib
import json

from conftest import ROOT

ASSETS = ROOT / "assets" / "images"
MANIFEST = json.loads((ASSETS / "LOCAL_EDITS.json").read_text(encoding="utf-8"))


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def test_local_edits_are_intact():
    changed = []
    for e in MANIFEST["edits"]:
        png = ASSETS / e["path"]
        if not png.is_file():
            changed.append(f"{e['path']}: missing")
        elif _git_blob(png.read_bytes()) != e["blob"]:
            changed.append(f"{e['path']}: overwritten (ours from {e['commit']})")
    assert changed == []


def test_local_edits_have_reasons():
    paths = [e["path"] for e in MANIFEST["edits"]]
    assert len(paths) == len(set(paths))
    for e in MANIFEST["edits"]:
        assert ".check/" in e["path"]
        assert e["reason"].strip()
        assert e["commit"].strip()


def test_known_regressions_stay_fixed():
    """The three files d201351 overwrote are listed."""
    paths = {e["path"] for e in MANIFEST["edits"]}
    assert {
        "Common02Icon.check/timg/C_Com_icon_Setting.png",
        "Common02Icon.check/timg/C_Com_icon_SettingON.png",
        "CameraSetting.check/timg/CamSet_Alert01.png",
        "NCommon.check/timg/Com_MultiWin_W01_Text02_01_04.png",
    } <= paths
