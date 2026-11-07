"""Mail home button list includes Zhoumaru Play (再生)."""

from __future__ import annotations

from conftest import TOOLS, load_module

deploy = load_module("deploy_mail_home_en", TOOLS / "deploy_mail_home_en.py")


def _reply_layout(width: float, x: float) -> bytes:
    import struct

    header_size = 0x14
    sec = bytearray(80)
    sec[0:4] = b"pan1"
    struct.pack_into("<I", sec, 4, len(sec))
    sec[12:27] = b"Tex_Reply_Text"
    struct.pack_into("<f", sec, 0x24, x)
    struct.pack_into("<f", sec, 68, width)
    total = header_size + len(sec)
    head = bytearray(header_size)
    struct.pack_into("<4sHHIII", head, 0, b"CLYT", 0xFEFF, header_size, 0, total, 1)
    return bytes(head) + bytes(sec)


def test_reply_text_pane_uses_the_rest_of_the_pill():
    import struct

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
