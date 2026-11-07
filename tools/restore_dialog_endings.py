#!/usr/bin/env python3
"""Put back sentence endings English dropped from the Japanese script.

A line changes only when the Japanese dialog at that index ends a sentence
and the English talk line has no ending of its own. Tag questions that
English already closes with a period stay put. Sound effects, a drawn-out
``～``, a cut-off ``--``, and a ``▼`` continue mark stay put.

Dry-run is the default.

  python tools/restore_dialog_endings.py
  python tools/restore_dialog_endings.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from patch_names import SDL2Data, build_dbin2, parse_dbin2  # noqa: E402

VANILLA = ROOT / "cache" / "vanilla_from_rom" / "romfs" / "script" / "bin" / "script"
DIALOG_RE = re.compile(r"<Dialog>(.*?)</Dialog>", re.DOTALL)
JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
SFX_RE = re.compile(r"\*[^*]+\*\s*$")
CLOSERS = set("\"'”’」』）)]〕")
JP_END = set("。！？…")
# A mark already in the English line. A comma is a pause, not an ending.
HAS_ENDING_RE = re.compile(r"[.!?！？。…]")


def _strip_marks(text: str) -> str:
    text = re.sub(r"▲[^▲\n]*▲", "", text)
    return text.replace("●", "").replace("\n", " ").strip()


def _jp_end(text: str) -> str:
    body = _strip_marks(text).rstrip()
    index = len(body) - 1
    while index >= 0 and body[index] in "」』）)】〕":
        index -= 1
    if index < 0:
        return ""
    return body[index]


def _tail(text: str) -> str:
    body = _strip_marks(text).rstrip()
    while body and body[-1] in "▼▲※":
        body = body[:-1].rstrip()
    return body


def _last_content(text: str) -> str:
    """Last glyph that is not a closer, a space, or the continue mark."""
    body = _tail(text)
    index = len(body) - 1
    while index >= 0 and (body[index] in CLOSERS or body[index].isspace()):
        index -= 1
    return body[index] if index >= 0 else ""


def _already_ended(text: str) -> bool:
    body = _tail(text)
    if not body or body.endswith(("...", "..", "--", "-", "_", "\\n")):
        return True
    if SFX_RE.search(body) or body[-1] in "～〜":
        return True
    if HAS_ENDING_RE.search(body):
        return True
    return _last_content(text) in set(".!?…~～！？。｡♪―—")


def restored_ending(jp: str, en: str) -> str | None:
    """English with the Japanese ending restored, or None when the line is fine."""
    if "▼" in en or "※" in en:
        return None
    end = _jp_end(jp)
    if end not in JP_END or _already_ended(en):
        return None
    body = _strip_marks(en)
    if JP_RE.search(body) or " " not in body:
        return None
    if len(re.findall(r"[A-Za-z]", body)) < 2:
        return None
    if SFX_RE.search(body) or body.endswith(("～", "〜", "--", "-", "_", "\\n")):
        return None
    # A comma inside quotes is part of the quote. Only a final comma can
    # become the Japanese full stop.
    stripped = en.rstrip()
    if _last_content(en) == "," and not stripped.endswith(","):
        return None
    has_ellipsis = "…" in jp
    if end == "…" or (has_ellipsis and end == "。"):
        mark = "..."
    elif end == "？" and has_ellipsis:
        mark = "...？"
    elif end == "？":
        mark = "？"
    elif end == "！":
        mark = "！"
    else:
        mark = "."
    stripped = en.rstrip()
    if stripped.endswith(","):
        if mark == ".":
            return stripped[:-1] + "."
        return None
    return stripped + mark


def _dialogs_of(path: Path) -> list[str]:
    _key, _unknown, entries = parse_dbin2(path.read_bytes())
    out: list[str] = []
    for entry in entries:
        out.extend(entry.sdl2.dialogs)
    return out


def _xml_dialogs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [_norm(hit) for hit in DIALOG_RE.findall(text)]


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_dbin(path: Path, dialogs: list[str]) -> None:
    key, unknown, entries = parse_dbin2(path.read_bytes())
    if build_dbin2(key, unknown, entries) != path.read_bytes():
        raise RuntimeError(f"{path} does not round-trip; left unchanged")
    index = 0
    rewritten = []
    for entry in entries:
        count = len(entry.sdl2.dialogs)
        rewritten.append(
            type(entry)(
                entry.unknown0,
                entry.unknown1,
                SDL2Data(entry.sdl2.key, entry.sdl2.unknown, dialogs[index : index + count]),
            )
        )
        index += count
    path.write_bytes(build_dbin2(key, unknown, rewritten))


def _write_xml(path: Path, dialogs: list[str]) -> None:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    matches = list(DIALOG_RE.finditer(text))
    if len(matches) != len(dialogs):
        raise RuntimeError(f"{path.name}: dialog count does not match")
    pieces: list[str] = []
    cursor = 0
    for match, new in zip(matches, dialogs):
        pieces.append(text[cursor : match.start(1)])
        old = _norm(match.group(1))
        if old == new:
            pieces.append(match.group(1))
        else:
            pieces.append(new.replace("\n", newline))
        cursor = match.end(1)
    pieces.append(text[cursor:])
    path.write_bytes("".join(pieces).encode("utf-8"))


def _english_files() -> list[Path]:
    roots = (
        ROOT / "rebuild_dbin2",
        ROOT / "assets" / "gemini_heroines",
        ROOT / "assets" / "scripts",
    )
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(root.rglob("*.dbin2"))
        found.extend(root.rglob("*.xml"))
    return sorted(found)


def plan_file(path: Path, vanilla: list[str]) -> list[tuple[int, str, str]]:
    current = _xml_dialogs(path) if path.suffix == ".xml" else _dialogs_of(path)
    if len(current) != len(vanilla):
        return []
    changes: list[tuple[int, str, str]] = []
    for index, (jp, en) in enumerate(zip(vanilla, current)):
        new = restored_ending(jp, en)
        if new is not None and new != en:
            changes.append((index, en, new))
    return changes


def apply_file(path: Path, vanilla: list[str]) -> list[tuple[int, str, str]]:
    changes = plan_file(path, vanilla)
    if not changes:
        return []
    current = _xml_dialogs(path) if path.suffix == ".xml" else _dialogs_of(path)
    for index, _old, new in changes:
        current[index] = new
    if path.suffix == ".xml":
        _write_xml(path, current)
    else:
        _write_dbin(path, current)
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the restored endings")
    parser.add_argument("--vanilla", type=Path, default=VANILLA)
    args = parser.parse_args(argv)
    vanilla_dir = args.vanilla
    if not vanilla_dir.is_dir():
        print(f"vanilla scripts missing: {vanilla_dir}", file=sys.stderr)
        return 1
    total = 0
    files = 0
    cache: dict[str, list[str] | None] = {}
    for path in _english_files():
        stem = path.stem
        if stem not in cache:
            vpath = vanilla_dir / f"{stem}.dbin2"
            cache[stem] = _dialogs_of(vpath) if vpath.is_file() else None
        vanilla = cache[stem]
        if vanilla is None:
            continue
        changes = apply_file(path, vanilla) if args.apply else plan_file(path, vanilla)
        if not changes:
            continue
        files += 1
        total += len(changes)
        print(f"{path.relative_to(ROOT)} ({len(changes)})")
        for index, old, new in changes[:8]:
            print(f"  #{index} {old!r} -> {new!r}")
        if len(changes) > 8:
            print(f"  … {len(changes) - 8} more")
    mode = "wrote" if args.apply else "would change"
    print(f"[endings] {mode} {total} line(s) in {files} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
