"""Mail home button list includes Zhoumaru Play (再生)."""

from __future__ import annotations

import struct

import pytest

from conftest import TOOLS, load_module

deploy = load_module("deploy_mail_home_en", TOOLS / "deploy_mail_home_en.py")


def _pane(name: bytes, width: float, x: float) -> bytes:
    sec = bytearray(80)
    sec[0:4] = b"pan1"
    struct.pack_into("<I", sec, 4, len(sec))
    sec[12 : 12 + len(name)] = name
    struct.pack_into("<f", sec, 0x24, x)
    struct.pack_into("<f", sec, 68, width)
    return bytes(sec)


def _clyt(*sections: bytes) -> bytes:
    header_size = 0x14
    total = header_size + sum(len(sec) for sec in sections)
    head = bytearray(header_size)
    struct.pack_into("<4sHHIII", head, 0, b"CLYT", 0xFEFF, header_size, 0, total, len(sections))
    return bytes(head) + b"".join(sections)


def _reply_layout(width: float, x: float) -> bytes:
    return _clyt(_pane(b"Tex_Reply_Text", width, x))


def test_reply_text_pane_uses_the_rest_of_the_pill():
    widened = deploy.widen_reply_text(_reply_layout(146.0, -16.0))
    x, w = struct.unpack_from("<ff", widened, 0x14 + 0x24)[0], struct.unpack_from(
        "<f", widened, 0x14 + 68
    )[0]
    assert w == deploy.REPLY_W
    assert x == deploy.REPLY_X
    # left edge stays put, right edge stays inside the 200 px pill
    assert abs((x - w / 2) - (-89.0)) < 0.01
    assert (x + w / 2) < 100
    again = deploy.widen_reply_text(widened)
    assert again == widened


def test_mail_home_play_buttons():
    assert deploy.BUTTON_PKG == 5207
    paths = [p for p, _en in deploy.BUTTON_LABELS]
    assert "timg/C_Btn_Play_Off.bclim" in paths
    assert "timg/C_Btn_Play_On.bclim" in paths
    assert dict(deploy.BUTTON_LABELS)["timg/C_Btn_Play_Off.bclim"] == "Play"
    assert "C_Btn_Play_Off" in deploy.ZHOUMARU_BUTTONS
    assert "C_Btn_Play_On" in deploy.ZHOUMARU_BUTTONS
    assert "mail_tex_chak_RGBA4" in deploy.ZHOUMARU_BUTTONS
    assert "mail_tex_jyusin_RGBA4" in deploy.ZHOUMARU_BUTTONS
    assert "mail_tex_shinki_RGBA4" in deploy.ZHOUMARU_BUTTONS


def test_mail_arc_lists_good_zhoumaru_masters():
    """Mail.arc rebuilds from vanilla; unlisted masters (compose tabs) ship JP."""
    from conftest import ROOT

    stems = {p.rsplit("/", 1)[-1].removesuffix(".bclim") for p, _en in deploy.ZHOUMARU_ONLY}
    assert {f"Mail_SendType_T0{i}" for i in range(1, 5)} <= stems
    assert "C_Com_icon_Repry2" not in stems  # 送信, mislabeled "Reply"
    for stem in stems:
        assert (ROOT / "assets" / "images" / "Mail.check" / "timg" / f"{stem}.png").is_file()
    assert stems <= deploy.ZHOUMARU_BUTTONS


def test_category_rows_render_menu_row_style():
    """Inbox rows use the Zhoumaru menu-row lettering (Arimo, gray 47)."""
    assert deploy.MENU_FONT.is_file()
    for _path, en in deploy.CATEGORY_LABELS:
        im = deploy.render_menu_label(142, 18, en)
        assert im.size == (142, 18)
        assert im.split()[3].getbbox() is not None



def test_render_label_faces_and_overflow():
    import pytest

    for face in (deploy.FONT, deploy.HEISEI_W5):
        if not face.is_file():
            continue
        im = deploy.render_label(64, 16, "Mail", face=face)
        assert im.size == (64, 16) and im.getchannel("A").getbbox() is not None
    with pytest.raises(RuntimeError, match="cannot fit"):
        deploy.render_label(8, 8, "Far too long")


def test_gap_pad_and_exact_empty_blocks():
    import zlib

    import fake_img as fi

    data = fi.darc({"a.bin": b"a" * 5, "b.bin": b"b" * 5}) + bytes(8)
    gaps = deploy.interfile_zero_gaps(data)
    assert len(gaps) == 2 and gaps == sorted(gaps, reverse=True)
    assert deploy.interfile_zero_gaps(data, min_len=10_000) == []
    rng = bytes(range(1, 256))
    size, off = gaps[0]
    padded = deploy.apply_gap_pad(data, 2, rng)
    assert padded[off : off + 2] == rng[:2] and padded[off + 2 :] == data[off + 2 :]
    assert deploy.interfile_zero_gaps(deploy.apply_gap_pad(data, size + 1, rng)) == []

    blob = b"mail" * 60
    base = len(zlib.compress(blob, 9)) + 20
    hit = next(n for n in range(base, base + 10) if deploy.compress_exact_empty_blocks(blob, n))
    assert zlib.decompress(deploy.compress_exact_empty_blocks(blob, hit)) == blob
    assert deploy.compress_exact_empty_blocks(blob, 4) is None


def test_only_the_reply_pane_moves():
    other_tag = b"txl1" + struct.pack("<I", 8)
    other_pane = _pane(b"Tex_Other", 146.0, -16.0)
    reply = _pane(b"Tex_Reply_Text", 146.0, -16.0)
    original = _clyt(other_tag, other_pane, reply)
    widened = deploy.widen_reply_text(original)
    start = 0x14 + len(other_tag) + len(other_pane)
    assert widened[:start] == original[:start]
    assert struct.unpack_from("<f", widened, start + 68)[0] == deploy.REPLY_W


@pytest.mark.parametrize(
    ("layout", "message"),
    [
        (b"FLYT" + bytes(0x20), "not CLYT"),
        (_reply_layout(100.0, -16.0), "geometry"),
        (_clyt(_pane(b"Tex_Other", 146.0, -16.0)), "found 0 times"),
        (
            _clyt(_pane(b"Tex_Reply_Text", 146.0, -16.0), _pane(b"Tex_Reply_Text", 146.0, -16.0)),
            "found 2 times",
        ),
    ],
)
def test_an_unexpected_layout_stops_the_deploy(layout, message):
    with pytest.raises(SystemExit, match=message):
        deploy.widen_reply_text(layout)
