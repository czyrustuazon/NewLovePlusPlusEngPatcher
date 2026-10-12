"""Mail sort popup labels rendered by deploy_mail_sort_en."""

from __future__ import annotations

import zlib

import numpy as np
from PIL import Image

from conftest import TOOLS, load_module

deploy = load_module("deploy_mail_sort_en", TOOLS / "deploy_mail_sort_en.py")


def test_mail_sort_constants():
    assert deploy.PKG == 5207
    assert deploy.ETC1_LABELS[0][0].endswith("Mail_PopTxt04.bclim")
    assert deploy.ETC1_LABELS[1][0].endswith("Mail_PopTxt05.bclim")
    assert [t for t, _a, _b in deploy.POP05_LINES] == [
        "Timestamp",
        "Sender",
        "Lock",
    ]
    assert "Cancel" in deploy.CANCEL_PATHS[0]
    assert "timg/C_Btn_Play_Off.bclim" in deploy.PRESERVE_HOME_PATHS
    assert "timg/mail_tex_jyusin_RGBA4.bclim" in deploy.PRESERVE_HOME_PATHS


def test_assert_home_preserved_detects_wipe(monkeypatch):
    before = {"timg/C_Btn_Play_Off.bclim": "a" * 40}
    monkeypatch.setattr(deploy, "_home_shas", lambda _arc: {"timg/C_Btn_Play_Off.bclim": "b" * 40})
    try:
        deploy._assert_home_preserved(before, b"unused")
    except SystemExit as exc:
        assert "wiped home chrome" in str(exc)
    else:
        raise AssertionError("expected SystemExit on wipe")


def test_render_sort_method_fits_canvas():
    im = deploy.render_gray_label(88, 20, "Sort Method")
    assert im.size == (88, 20)
    assert im.mode == "RGBA"
    a = np.array(im)[:, :, 3]
    assert int((a > 20).sum()) > 50


def test_render_pop05_three_bands():
    im = deploy.render_pop05(104, 96)
    assert im.size == (104, 96)
    a = np.array(im)[:, :, 3]
    for _text, y0, y1 in deploy.POP05_LINES:
        band = a[y0 : y1 + 1]
        assert int((band > 20).sum()) > 20


def test_reletter_cancel_keeps_face_alpha():
    # Translucent face + white JP fill + dark outline (vanilla キャンセル shape).
    chrome = Image.new("RGBA", (98, 42), (250, 250, 250, 170))
    for x in range(22, 76):
        for y in range(15, 27):
            chrome.putpixel((x, y), (254, 254, 254, 255))  # white glyph body
    for x in range(20, 78):
        chrome.putpixel((x, 14), (51, 51, 51, 255))
        chrome.putpixel((x, 27), (51, 51, 51, 255))

    def _fake_decode(_raw: bytes):
        return chrome.copy()

    orig = deploy.decode_bclim_to_image
    deploy.decode_bclim_to_image = _fake_decode  # type: ignore[assignment]
    try:
        out = deploy.reletter_cancel(b"unused", "Cancel")
    finally:
        deploy.decode_bclim_to_image = orig  # type: ignore[assignment]
    arr = np.array(out)
    center = arr[14:28, 30:68]
    center_a = center[:, :, 3]
    center_lum = center[:, :, :3].mean(axis=2)
    assert (center_lum < 140).any()  # EN ink
    face_gaps = center_a[center_lum > 200]
    assert face_gaps.size and float(face_gaps.mean()) < 200
    # No leftover opaque white JP body in the face.
    white_left = ((center_lum > 230) & (center_a > 230)).sum()
    assert int(white_left) < 30


def test_compress_exact_empty_blocks_roundtrip():
    data = b"PACK" + bytes(range(256)) * 8
    # Pick a slot that empty-block can hit.
    body_len = None
    for level in range(10):
        co = zlib.compressobj(level, wbits=-15)
        body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
        # hdr(2) + body + final(5) + adler(4); pad remain % 5 == 0
        base = 2 + len(body) + 5 + 4
        # bump to next congruent length with at least one empty block
        for extra in range(5, 50, 5):
            slot_len = base + extra
            got = deploy.compress_exact_empty_blocks(data, slot_len)
            if got is not None:
                body_len = slot_len
                break
        if body_len is not None:
            break
    assert body_len is not None
    stream = deploy.compress_exact_empty_blocks(data, body_len)
    assert stream is not None and len(stream) == body_len
    d = zlib.decompressobj()
    assert d.decompress(stream) == data
    assert not d.unused_data and d.eof
