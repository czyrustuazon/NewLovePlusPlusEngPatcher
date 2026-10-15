"""Gemini Japanese→English helpers for NLPP heroine dialogue / SMS.

Preserves game control tokens by swapping them for ASCII sentinels before the
API call and restoring + validating them afterwards. A dropped ``▲…▲``,
``※``, ``▼``, or ``●`` is treated as a failed translation.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Latest Gemini Pro (2026-09). gemini-3-pro-preview shut down 2026-03-09.
DEFAULT_GEMINI_MODEL = "gemini-3.1-pro-preview"
# JP-TL-Bench slightly favored Flash for raw JP→EN; Pro is the quality default.
ALT_FLASH_MODEL = "gemini-3-flash-preview"

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# Placeholder-only / punct-only lines are left alone (volunteer workbench rule).
SKIP_LINE_RE = re.compile(
    r"^(?:[○●…\s]|[？?！!。．.、，,―—\-~～…♪★☆♡♥※▼])+$"
)

# Complete ▲…▲ tokens, then control glyphs, then printf / {n} placeholders.
MARKER_RE = re.compile(
    r"▲[^▲]+▲"
    r"|[※▼●]"
    r"|%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?[sdifuxXcs]"
    r"|\{[^{}]+\}"
)
SENTINEL_RE = re.compile(r"@@M(\d+)@@")

HEROINE_VOICES = {
    "nene": (
        "Anegasaki Nene — warm, teasing 'older girlfriend' energy; casual, "
        "affectionate, a little playful. Sound like a real person talking, "
        "not a subtitle dump."
    ),
    "rinko": (
        "Kobayakawa Rinko — reserved bookworm; polite, dry, sometimes blunt. "
        "Keep her composed; do not make her bubbly or slangy unless the JP is."
    ),
    "manaka": (
        "Takane Manaka — bright, earnest, athletic club-captain energy; "
        "friendly and a bit straightforward."
    ),
    "common": "Shared / system scenes. Match the speaker implied by the Japanese.",
}


SYSTEM_PROMPT = """You translate Japanese Nintendo 3DS dating-sim dialogue from NEW Love Plus+ into natural spoken English.

Output rules:
- Return ONLY JSON: {"items":[{"i": <int>, "t": "<english>"}]}
- Translate only objects whose "need" is true. Keep the same "i" values.
- Sound like the character speaking, not like a dictionary. Contractions are fine.
- Preserve every @@Mn@@ sentinel EXACTLY, in the same order. These stand in for game markers (names, wait codes). Never drop, translate, reorder, or spell them out.
- Input may use ◙ for a line break. Put ◙ in the English at natural wrap points (3DS bubble is narrow, ~22–28 Latin letters).
- Prefer fullwidth ？ for questions (matches existing EN scripts). Prefer ASCII letters.
- Game names: 高嶺/愛花=Takane/Manaka, 小早川/凛子=Kobayakawa/Rinko, 姉ヶ崎/寧々=Anegasaki/Nene, とわの/トワノ=Towano.
- Do NOT replace name/player tokens with English names — sentinels already cover ▲主人公＊▲ / ▲高嶺＊＊▲ / ▲小早川＊▲ / ▲姉ヶ崎＊▲.
- Never leave Japanese kana/kanji unless a proper noun has no English form.
- Do not wrap the whole string in extra quotes.
- Leave placeholder-only lines (○○○) untranslated if they slip through — copy the source.
"""


def dotenv_paths() -> list[Path]:
    return [
        ROOT / ".env",
        ROOT.parent / "NewLovePlusPlusLocalizationProject" / ".env",
        ROOT.parent / ".env",
    ]


def load_dotenv_map(paths: list[Path] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in paths or dotenv_paths():
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in out and value:
                out[key] = value
    return out


def load_env_value(*names: str, explicit: str | None = None) -> str | None:
    if explicit is not None:
        text = explicit.strip()
        return text or None
    for name in names:
        env = os.environ.get(name, "").strip()
        if env:
            return env
    dotenv = load_dotenv_map()
    for name in names:
        val = dotenv.get(name, "").strip()
        if val:
            return val
    return None


def load_gemini_api_key(explicit: str | None = None) -> str:
    key = load_env_value("GEMINI_API_KEY", "GOOGLE_API_KEY", explicit=explicit)
    if key:
        return key
    raise SystemExit(
        "GEMINI_API_KEY is not set. Copy .env.example to .env and paste a "
        "Google AI Studio key, or pass --api-key."
    )


def load_gemini_model(explicit: str | None = None) -> str:
    return (
        load_env_value("GEMINI_MODEL", explicit=explicit) or DEFAULT_GEMINI_MODEL
    )


def strip_markers(text: str) -> str:
    return MARKER_RE.sub("", text or "")


def has_japanese(text: str) -> bool:
    return bool(JP_RE.search(strip_markers(text)))


def should_skip_line(text: str) -> bool:
    """True for empty, punct-only, or circle-placeholder lines."""
    if not text or not text.strip():
        return True
    stripped = text.strip()
    if SKIP_LINE_RE.match(stripped) and not has_japanese(stripped):
        return True
    return False


def needs_translation(text: str) -> bool:
    if should_skip_line(text):
        return False
    return has_japanese(text)


def extract_markers(text: str) -> list[str]:
    return MARKER_RE.findall(text)


def protect_markers(text: str) -> tuple[str, list[str]]:
    markers = extract_markers(text)
    if not markers:
        return text, []
    out = []
    last = 0
    for i, match in enumerate(MARKER_RE.finditer(text)):
        out.append(text[last : match.start()])
        out.append(f"@@M{i}@@")
        last = match.end()
    out.append(text[last:])
    return "".join(out), markers


def restore_markers(text: str, markers: list[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if 0 <= idx < len(markers):
            return markers[idx]
        return match.group(0)

    return SENTINEL_RE.sub(repl, text)


def leftover_sentinels(text: str) -> list[str]:
    return SENTINEL_RE.findall(text)


def marker_multiset(text: str) -> list[str]:
    return extract_markers(text)


def markers_preserved(source: str, translated: str) -> tuple[bool, list[str]]:
    """Return (ok, missing_from_translation). Order-insensitive counts."""
    src = extract_markers(source)
    dst = extract_markers(translated)
    missing: list[str] = []
    remaining = list(dst)
    for token in src:
        if token in remaining:
            remaining.remove(token)
        else:
            missing.append(token)
    return (not missing, missing)


def to_api_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "◙")


def from_api_newlines(text: str) -> str:
    return text.replace("◙", "\n").replace("\r\n", "\n").replace("\r", "\n")


RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "t": {"type": "string"},
                },
                "required": ["i", "t"],
            },
        }
    },
    "required": ["items"],
}


def parse_items_json(raw: str) -> dict[int, str]:
    data = json.loads(raw or "{}")
    items = data.get("items", data if isinstance(data, list) else [])
    by_i: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict) or "i" not in item or "t" not in item:
            continue
        by_i[int(item["i"])] = str(item["t"])
    return by_i


@dataclass
class TranslateItem:
    index: int
    source: str
    need: bool
    protected: str = ""
    markers: list[str] = field(default_factory=list)


@dataclass
class TranslateResult:
    index: int
    source: str
    english: str | None
    error: str = ""
    missing_markers: list[str] = field(default_factory=list)


def prepare_items(sources: list[str], need: list[bool] | None = None) -> list[TranslateItem]:
    items: list[TranslateItem] = []
    for i, src in enumerate(sources):
        flag = need[i] if need is not None else needs_translation(src)
        protected, markers = protect_markers(src) if flag else (src, extract_markers(src))
        items.append(
            TranslateItem(
                index=i,
                source=src,
                need=flag,
                protected=to_api_newlines(protected),
                markers=markers,
            )
        )
    return items


def build_user_prompt(
    items: list[TranslateItem],
    *,
    heroine: str,
    context: str = "",
) -> str:
    voice = HEROINE_VOICES.get(heroine, HEROINE_VOICES["common"])
    payload = [
        {
            "i": it.index,
            "need": it.need,
            "s": it.protected if it.need else to_api_newlines(it.source),
        }
        for it in items
    ]
    header = [
        f"Heroine/route: {heroine}. Voice: {voice}",
        "Translate each object with need=true into natural English.",
        "Copy every @@Mn@@ sentinel into the English unchanged.",
    ]
    if context:
        header.append(context)
    header.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(header)


def finalize_item(item: TranslateItem, raw_en: str | None) -> TranslateResult:
    if not item.need:
        return TranslateResult(item.index, item.source, item.source)
    if raw_en is None:
        return TranslateResult(item.index, item.source, None, error="missing")
    en = from_api_newlines(restore_markers(raw_en, item.markers))
    leftover = leftover_sentinels(en)
    if leftover:
        return TranslateResult(
            item.index,
            item.source,
            None,
            error="leftover_sentinel",
            missing_markers=[f"@@M{n}@@" for n in leftover],
        )
    ok, missing = markers_preserved(item.source, en)
    if not ok:
        return TranslateResult(
            item.index,
            item.source,
            None,
            error="dropped_marker",
            missing_markers=missing,
        )
    jp_left = len(JP_RE.findall(strip_markers(en)))
    if jp_left > max(2, len(en) // 4):
        return TranslateResult(item.index, item.source, None, error="still_japanese")
    return TranslateResult(item.index, item.source, en)


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text)
    # google-genai sometimes nests candidates → content → parts
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            continue
        chunks = [getattr(p, "text", "") or "" for p in parts]
        joined = "".join(chunks).strip()
        if joined:
            return joined
    return ""


def make_gemini_client(api_key: str):
    try:
        from google import genai
    except ImportError as exc:
        raise SystemExit(
            "google-genai is not installed. Run: pip install google-genai"
        ) from exc
    return genai.Client(api_key=api_key)


def _thinking_config(types_mod, thinking_level: str):
    level = (thinking_level or "HIGH").upper()
    if level == "OFF":
        return None
    try:
        return types_mod.ThinkingConfig(thinking_level=level)
    except (TypeError, ValueError):
        enum = getattr(types_mod, "ThinkingLevel", None)
        value = getattr(enum, level, None) if enum is not None else None
        if value is not None:
            try:
                return types_mod.ThinkingConfig(thinking_level=value)
            except (TypeError, ValueError):
                pass
    return None


def _retry_delay_seconds(exc: BaseException, attempt: int) -> float:
    text = str(exc)
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", text, re.I)
    if match:
        return min(float(match.group(1)) + 2.0, 900.0)
    match = re.search(r"'retryDelay': '(\d+)s'", text)
    if match:
        return min(float(match.group(1)) + 2.0, 900.0)
    return min(30.0 * (2 ** attempt), 300.0)


def _is_retryable_api_error(exc: BaseException) -> bool:
    text = str(exc)
    return any(
        token in text
        for token in (
            "429",
            "RESOURCE_EXHAUSTED",
            "UNAVAILABLE",
            "500",
            "502",
            "503",
            "504",
        )
    )


def gemini_generate_json(
    client,
    model: str,
    user: str,
    *,
    temperature: float = 0.4,
    thinking_level: str = "HIGH",
) -> str:
    from google.genai import types

    config_kwargs: dict[str, Any] = {
        "system_instruction": SYSTEM_PROMPT,
        "temperature": temperature,
        "response_mime_type": "application/json",
    }
    think = _thinking_config(types, thinking_level)
    if think is not None:
        config_kwargs["thinking_config"] = think

    config = None
    for schema_key in ("response_json_schema", "response_schema"):
        try:
            config = types.GenerateContentConfig(
                **config_kwargs, **{schema_key: RESPONSE_JSON_SCHEMA}
            )
            break
        except (TypeError, ValueError):
            continue
    if config is None:
        config = types.GenerateContentConfig(**config_kwargs)

    last_exc: BaseException | None = None
    for attempt in range(8):
        try:
            response = client.models.generate_content(
                model=model,
                contents=user,
                config=config,
            )
            return _extract_response_text(response)
        except Exception as exc:  # noqa: BLE001 — retry Gemini quota / transport
            last_exc = exc
            if not _is_retryable_api_error(exc) or attempt == 7:
                raise
            if "PerDay" in str(exc) or "per_day" in str(exc):
                raise
            delay = _retry_delay_seconds(exc, attempt)
            print(
                f"[gemini] retry {attempt + 1}/8 in {delay:.0f}s ({type(exc).__name__})",
                flush=True,
            )
            time.sleep(delay)
    raise last_exc or RuntimeError("gemini_generate_json failed")


def _context_window(
    items: list[TranslateItem],
    chunk: list[TranslateItem],
    *,
    pad: int = 16,
) -> list[TranslateItem]:
    """Prompt slice: lines to translate plus nearby scene context."""
    if not chunk:
        return []
    want = {it.index for it in chunk}
    lo = min(want) - pad
    hi = max(want) + pad
    out: list[TranslateItem] = []
    for it in items:
        if it.index in want or lo <= it.index <= hi:
            out.append(
                TranslateItem(
                    index=it.index,
                    source=it.source,
                    need=it.index in want,
                    protected=it.protected,
                    markers=it.markers,
                )
            )
    return out


def _translate_prepared_once(
    client,
    model: str,
    prompt_items: list[TranslateItem],
    targets: list[TranslateItem],
    *,
    heroine: str,
    context: str = "",
    temperature: float = 0.4,
    thinking_level: str = "HIGH",
    repair: bool = True,
) -> dict[int, TranslateResult]:
    results: dict[int, TranslateResult] = {}
    if not targets:
        return results
    user = build_user_prompt(prompt_items, heroine=heroine, context=context)
    raw = gemini_generate_json(
        client,
        model,
        user,
        temperature=temperature,
        thinking_level=thinking_level,
    )
    by_i = parse_items_json(raw)
    failed: list[TranslateItem] = []
    for it in targets:
        res = finalize_item(it, by_i.get(it.index))
        if res.english is None:
            failed.append(it)
        results[it.index] = res

    if repair and failed:
        time.sleep(0.4)
        repair_payload = [
            {
                "i": it.index,
                "s": it.protected,
                "missing": results[it.index].missing_markers,
                "bad": results[it.index].error,
            }
            for it in failed
        ]
        repair_user = (
            f"Heroine/route: {heroine}. The previous English dropped game markers.\n"
            "Re-translate. Copy every @@Mn@@ sentinel into t. Return JSON items.\n"
            + json.dumps(repair_payload, ensure_ascii=False)
        )
        raw2 = gemini_generate_json(
            client,
            model,
            repair_user,
            temperature=min(temperature, 0.2),
            thinking_level=thinking_level,
        )
        by_i2 = parse_items_json(raw2)
        for it in failed:
            results[it.index] = finalize_item(it, by_i2.get(it.index))
    return results


def translate_prepared(
    client,
    model: str,
    items: list[TranslateItem],
    *,
    heroine: str,
    context: str = "",
    temperature: float = 0.4,
    thinking_level: str = "HIGH",
    repair: bool = True,
    chunk_size: int = 40,
    context_pad: int = 16,
) -> list[TranslateResult]:
    needed = [it for it in items if it.need]
    results: dict[int, TranslateResult] = {}
    for it in items:
        if not it.need:
            results[it.index] = TranslateResult(it.index, it.source, it.source)

    if not needed:
        return [results[i] for i in range(len(items))]

    size = chunk_size if chunk_size and chunk_size > 0 else len(needed)
    for start in range(0, len(needed), size):
        chunk = needed[start : start + size]
        prompt_items = _context_window(items, chunk, pad=context_pad)
        part = _translate_prepared_once(
            client,
            model,
            prompt_items,
            chunk,
            heroine=heroine,
            context=context,
            temperature=temperature,
            thinking_level=thinking_level,
            repair=repair,
        )
        results.update(part)

    return [results[i] for i in range(len(items))]


def translate_texts(
    client,
    model: str,
    texts: list[str],
    *,
    heroine: str,
    context: str = "",
    **kwargs: Any,
) -> list[TranslateResult]:
    items = prepare_items(texts)
    return translate_prepared(
        client, model, items, heroine=heroine, context=context, **kwargs
    )
