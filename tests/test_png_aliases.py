from pathlib import Path

from pack_images import png_to_bclim_candidates


def test_new_prefix_aliases_album_stems():
    cands = png_to_bclim_candidates(Path("new_Btn_Search_Off.png"))
    joined = " ".join(cands).lower()
    assert "timg/c_btn_search_off.bclim" in joined
    assert "timg/alb_btn_search_off.bclim" in joined


def test_upper_suffix_strips():
    cands = png_to_bclim_candidates(Path("Btn_kamae_a_upper.png"))
    joined = " ".join(cands).lower()
    assert "timg/btn_kamae_a.bclim" in joined


def test_dunder_prefix_strips():
    cands = png_to_bclim_candidates(Path("__Que_Txt02b.png"))
    joined = " ".join(cands).lower()
    assert "timg/que_txt02b.bclim" in joined
