"""Dropped Japanese endings come back. Lines that already end stay put."""

from __future__ import annotations

from conftest import TOOLS, load_module

endings = load_module("restore_dialog_endings", TOOLS / "restore_dialog_endings.py")


def test_ellipsis_question_and_bang_follow_the_japanese():
    assert endings.restored_ending("前のほうが好きかな……", "The last style was better") == (
        "The last style was better..."
    )
    assert endings.restored_ending("好き、かな？", "I like it, I guess") == "I like it, I guess？"
    assert endings.restored_ending("ちょっと派手……かな？", "This is too gaudy") == (
        "This is too gaudy...？"
    )
    assert endings.restored_ending("中華料理が好きだ！", "Chinese food") == "Chinese food！"


def test_a_trailing_comma_becomes_a_period_when_japanese_ends_the_sentence():
    jp = "こんなに一緒にいたの、はじめてだけど。"
    en = "This is the first time we've\n\nbeen together this long,"
    assert endings.restored_ending(jp, en) == (
        "This is the first time we've\n\nbeen together this long."
    )


def test_finished_lines_sound_effects_and_continue_marks_stay():
    assert endings.restored_ending("よろしくね？", "Pleased to meet you.") is None
    assert endings.restored_ending("はあ。", "Tell me about it... *sigh*") is None
    assert endings.restored_ending("だ。", "*Sniff, sniff*") is None
    assert endings.restored_ending("ダーメ。", "No way, not right now〜") is None
    assert endings.restored_ending("な。", "It makes me want to say, 'I'm home, ▼'") is None
    assert endings.restored_ending("かな……", "The last style was better...") is None
    assert endings.restored_ending("だ！", "Nice！ I love it") is None
    assert endings.restored_ending("か？", "(A book I'd laugh at...？ )") is None
    assert endings.restored_ending("。", '"To expand our knowledge,"') is None
    assert endings.restored_ending("姉ヶ崎", "Anegasaki") is None
