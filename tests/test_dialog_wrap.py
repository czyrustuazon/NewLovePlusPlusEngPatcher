"""English script lines are broken at spaces before the game cuts a word."""

from __future__ import annotations

import dialog_wrap as dw
import patch_names as names


def _script(dialogs: list[str]) -> bytes:
    sdl2 = names.SDL2Data(key=2, unknown=[], dialogs=dialogs)
    return names.build_dbin2(1, 0, [names.DbinEntry(0, 0, sdl2)])


def _choice_script(dialogs: list[str], choices: list[int]) -> bytes:
    """Talk dialog 1 (index << 16), then choice buttons (0x0001NNNN)."""
    cmds = [names.UnknownEntry([], 0x24002, 1 << 16)]
    cmds += [names.UnknownEntry([], 0x10000 | i, 0x24002) for i in choices]
    sdl2 = names.SDL2Data(key=2, unknown=cmds, dialogs=dialogs)
    return names.build_dbin2(1, 0, [names.DbinEntry(0, 0, sdl2)])


def _game_wrap(text: str, width: int) -> str:
    """FUN_005bf750 without kinsoku: break in front of the char that crosses."""
    out = []
    col = 0
    for c in text:
        if c == "\n":
            col = 0
        else:
            col += 1 if ord(c) < 0x80 else 2
            if col > width:
                out.append("\n")
                col = 1 if ord(c) < 0x80 else 2
        out.append(c)
    return "".join(out)


def test_columns_count_wide_glyphs_and_marker_budgets():
    assert dw.columns("abc") == 3
    assert dw.columns("Eh？") == 4
    assert dw.columns("Hi ▲Takane＊＊▲.") == 3 + dw.NAME_COLUMNS + 1
    assert dw.columns("▲小早川＊▲") == dw.NAME_COLUMNS
    assert dw.columns("● ▲月▲") == dw.NAME_COLUMNS + 1 + 9
    assert dw.columns("▲デート場所▲") == dw.OTHER_MARKER_COLUMNS


def test_overlong_line_is_reflowed_where_the_game_would_cut_a_word():
    text = "Okay then, let's hear you talk about how much you love me right now."
    assert "\n" in _game_wrap(text, dw.TALK_COLUMNS)  # vanilla: mid-word cut
    talk = dw.wrap_dialog(text)
    assert talk == "Okay then, let's hear you talk\nabout how much you love me\nright now."
    assert _game_wrap(talk, dw.TALK_COLUMNS) == talk
    button = dw.wrap_dialog(text, dw.CHOICE_COLUMNS)
    assert button == "Okay then, let's hear you\ntalk about how much you love\nme right now."
    assert _game_wrap(button, dw.CHOICE_COLUMNS) == button


def test_lines_that_already_fit_are_left_alone():
    hand = "So this is Towano City, \nhuh..."
    assert dw.wrap_dialog(hand) == hand
    talk = "Is that so...？ Then rabbits \nit is！"  # 29 columns, two lines
    assert dw.wrap_dialog(talk) == talk
    assert dw.wrap_dialog("Let's go.") == "Let's go."


def test_29_columns_fits_talk_but_not_a_choice_button():
    text = "All right, let's get started!"
    assert dw.wrap_dialog(text) == text
    assert dw.wrap_dialog(text, dw.CHOICE_COLUMNS) == "All right, let's get\nstarted!"
    # The photographed k142 choice: the game showed "...no choi / ce.".
    photo = "Got it. Guess I have no choice."
    assert "choi\nce" in _game_wrap(photo, dw.CHOICE_COLUMNS)
    assert dw.wrap_dialog(photo, dw.CHOICE_COLUMNS) == "Got it. Guess I have no\nchoice."


def test_overlong_line_in_a_broken_dialog_reflows_the_whole_dialog():
    text = "Sounds good to me！\nIt's kind of cute.\nI've gotten fond of it already."
    assert dw.wrap_dialog(text) == (
        "Sounds good to me！ It's kind\nof cute. I've gotten fond of\nit already."
    )
    blank = " " * 31
    assert dw.wrap_dialog(blank) == blank


def test_reflow_keeps_hand_hyphens_and_markers_whole():
    text = "Walking down these spring- \ntime streets with ▲Takane＊＊▲ is definitely the feeling."
    wrapped = dw.wrap_dialog(text)
    assert "spring-time" in wrapped
    assert "▲Takane＊＊▲" in wrapped
    assert all(dw.columns(line) <= dw.TALK_COLUMNS for line in wrapped.split("\n"))


def test_japanese_and_unbreakable_words_are_left_to_the_game():
    jp = "大丈夫だと思うけど、これからも▲Kobayaka＊▲ に寂しい思いはさせないようにしよう。"
    assert dw.wrap_dialog(jp) == jp
    assert dw.wrap_dialog("SKINSHIP_RET_CHANGE_SITUATION") == "SKINSHIP_RET_CHANGE_SITUATION"
    long_word = "Honorificabilitudinitatibus... ok"
    assert dw.wrap_dialog(long_word) == "Honorificabilitudinitatibus...\nok"


def test_fit_font_swaps_glyphs_the_dialog_font_lacks():
    assert dw.fit_font("giving presents—just to see") == "giving presents―just to see"
    assert dw.fit_font("pages 1–2, right now〜") == "pages 1-2, right now～"
    assert dw.fit_font("cliché, señor, Gyōja, Família") == "cliche, senor, Gyoja, Familia"
    assert dw.fit_font("3 × 4 ÷ 2") == "3 × 4 ÷ 2"
    assert dw.fit_font("Hi？ ▲Takane＊＊▲ ―") == "Hi？ ▲Takane＊＊▲ ―"


def test_fit_font_turns_a_typed_out_break_into_a_real_one():
    typed = "(What kind of storefront says all that？)" + "\\" + "n"
    assert dw.fit_font(typed) == "(What kind of storefront says all that？)"
    assert dw.fit_font("Wait." + "\\" + "nOkay.") == "Wait.\nOkay."
    assert dw.fit_font("Line one\nline two\n") == "Line one\nline two\n"


def test_wrap_dbin2_fits_the_font_before_wrapping():
    raw = _script(["Maybe that's the whole point—just to see that look."])
    _, _, entries = names.parse_dbin2(dw.wrap_dbin2(raw))
    # ― is two columns: "point―just to see that look." is 30.
    assert entries[0].sdl2.dialogs == ["Maybe that's the whole\npoint―just to see that look."]


def test_wrap_dbin2_rewrites_only_scripts_that_change():
    fits = _script(["Hello.", "See you."])
    assert dw.wrap_dbin2(fits) is fits
    assert dw.wrap_dbin2(b"not a script") == b"not a script"

    raw = _script(["Hello.", "You forgot my birthday, didn't you？ Sigh..."])
    _, _, entries = names.parse_dbin2(dw.wrap_dbin2(raw))
    assert entries[0].sdl2.dialogs == [
        "Hello.",
        "You forgot my birthday, didn't\nyou？ Sigh...",
    ]


def test_choice_buttons_are_found_from_their_commands():
    raw = _choice_script(["Rinko", "Will you?", "Yes", "No"], [2, 3])
    sdl2 = names.parse_dbin2(raw)[2][0].sdl2
    assert dw.choice_dialogs(sdl2) == {2, 3}
    # A 0x0001NNNN word with a value list, or index 0, is not a button.
    sdl2.unknown.append(names.UnknownEntry([names.SectionAEntry(5, 0)], 0x10001, 0))
    sdl2.unknown.append(names.UnknownEntry([], 0x10000, 0))
    assert dw.choice_dialogs(sdl2) == {2, 3}


def test_choice_buttons_wrap_at_28_and_talk_at_30():
    photo = "Got it. Guess I have no choice."  # 31: past both widths
    fits_talk = "I think that's a good idea, ok"  # 30
    raw = _choice_script(["Rinko", photo, photo, fits_talk, fits_talk], [2, 3])
    _, _, entries = names.parse_dbin2(dw.wrap_dbin2(raw))
    assert entries[0].sdl2.dialogs == [
        "Rinko",
        "Got it. Guess I have no\nchoice.",
        "Got it. Guess I have no\nchoice.",
        "I think that's a good idea,\nok",  # button: 30 > 28
        fits_talk,  # talk: 30 fits
    ]
