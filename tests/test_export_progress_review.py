"""Gemini machine-pass stems show as unreviewed in fansite progress JSON."""

from __future__ import annotations

from conftest import TOOLS, load_module

metrics = load_module("export_progress_metrics", TOOLS / "export_progress_metrics.py")


def test_gemini_nene_stems_are_machine_unreviewed():
    unrev = metrics.gemini_unreviewed_stems()
    assert "a141" in unrev
    assert "t000" not in unrev
    assert "k000" not in unrev


def test_proofread_json_removes_stem_from_unreviewed(tmp_path, monkeypatch):
    proof = tmp_path / "proofread.json"
    proof.write_text('{"stems": ["a141"]}\n', encoding="utf-8")
    monkeypatch.setattr(metrics, "GEMINI_PROOFREAD", proof)
    assert "a141" not in metrics.gemini_unreviewed_stems()
    assert "a000" in metrics.gemini_unreviewed_stems()


def test_script_metrics_nene_bar_is_teal_unreviewed():
    scripts = metrics.script_metrics(metrics.DEFAULT_ENG_DBIN)
    nene = scripts["by_route"]["nene"]
    assert nene["english_unreviewed"] > 0
    assert nene["caveat"] == metrics.CAVEAT_MACHINE
    assert nene["bar"] == metrics.BAR_UNREVIEWED
    assert any(f["bar"] == metrics.BAR_UNREVIEWED for f in nene["fills"])
    manaka = scripts["by_route"]["manaka"]
    assert manaka["english_unreviewed"] == 0
    assert manaka["bar"] == metrics.BAR_REVIEWED
    a141 = next(r for r in scripts["files"]["english"] if r["stem"] == "a141")
    assert a141["review"] == metrics.REVIEW_MACHINE
    t000 = next(r for r in scripts["files"]["english"] if r["stem"] == "t000")
    assert t000["review"] == metrics.REVIEW_REVIEWED
    assert scripts["english_unreviewed"] == nene["english_unreviewed"]
