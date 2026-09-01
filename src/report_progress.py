#!/usr/bin/env python3
"""Report script-text translation progress to the companion site.

Diffs the rebuilt English ``textresource_jpn.trb`` against the pristine JP
baseline, counts the entries whose text changed, and POSTs the numbers to the
site Worker's ``/api/admin/progress`` route (Workers KV). The site's progress
bar reads that KV value live -- no site rebuild, same one-shot-write model as
the ``/devlog`` Discord command.

Typical use, after a translation batch::

    py src/patch_textresource.py rebuild      # regenerates release/textresource/*.trb
                                              # and auto-POSTs when .env is set
    py src/report_progress.py                 # manual / CI / Drop CIA.bat

Or via the make shim: ``.\\make.ps1 progress``.

Config lives outside the repo (this is a public repo -- the site's admin surface
should not be discoverable from it). Copy ``.env.example`` to ``.env`` and set:

* ``NLPP_PROGRESS_ENDPOINT`` -- the Worker's admin progress URL
* ``NLPP_PROGRESS_TOKEN``    -- bearer token (prefer site ``PROGRESS_API_TOKEN``;
  ``ADMIN_API_TOKEN`` still accepted as a fallback)

Both may instead be passed as env vars or ``--endpoint`` / ``--token``. Without
them the script still runs ``--dry-run`` style math but refuses to POST (unless
``--best-effort``, which soft-skips the POST).

Auto triggers (all soft-fail — never break a rebuild/patch):

* end of ``patch_textresource.py rebuild`` (when endpoint+token resolve)
* end of successful ``Drop CIA or 3DS Here to Patch.bat``
* nlpp-gold CI after a gold bake (GitHub secrets)

Disable with ``NLPP_PROGRESS_SKIP=1``.

The graphics/menu track is maintained by hand in the admin panel and is not
touched here -- a partial POST only updates the fields it sends.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # local `import` of siblings

import nlpp_paths as paths  # noqa: E402
import patch_textresource as tr  # noqa: E402

# Durable rebuilt EN TRB (default --out of `patch_textresource.py rebuild`).
DEFAULT_EN_TRB = paths.TEXTRESOURCE / "textresource_jpn.trb"

# Preferred first; ADMIN_API_TOKEN kept as local/dev fallback until the site
# Worker accepts a progress-only PROGRESS_API_TOKEN.
_TOKEN_ENV_NAMES = (
    "NLPP_PROGRESS_TOKEN",
    "PROGRESS_API_TOKEN",
    "ADMIN_API_TOKEN",
)


def _progress_skipped() -> bool:
    return os.environ.get("NLPP_PROGRESS_SKIP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _from_env_or_dotenv(*names: str) -> str | None:
    """First non-empty value for any of `names`, from the environment then .env."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    for path in (paths.ROOT / ".env", paths.ROOT.parent / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in names:
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
    return None


def load_token(explicit: str | None = None, *, required: bool = True) -> str | None:
    # explicit="" means force-unset (do not fall through to .env).
    if explicit is not None:
        token = explicit.strip() or None
    else:
        token = _from_env_or_dotenv(*_TOKEN_ENV_NAMES)
    if token:
        return token
    if required:
        raise SystemExit(
            "No progress token. Set NLPP_PROGRESS_TOKEN in "
            "NewLovePlusPlusEngPatcher/.env (copy .env.example), export it, or pass "
            "--token. Prefer the site Worker's PROGRESS_API_TOKEN (progress-only); "
            "ADMIN_API_TOKEN still works as a fallback."
        )
    return None


def load_endpoint(explicit: str | None = None, *, required: bool = True) -> str | None:
    if explicit is not None:
        endpoint = explicit.strip() or None
    else:
        endpoint = _from_env_or_dotenv("NLPP_PROGRESS_ENDPOINT")
    if endpoint:
        return endpoint
    if required:
        raise SystemExit(
            "No progress endpoint. Set NLPP_PROGRESS_ENDPOINT in "
            "NewLovePlusPlusEngPatcher/.env (copy .env.example), export it, or pass "
            "--endpoint. Or use --dry-run / --best-effort to skip posting."
        )
    return None


def script_progress(vanilla_trb: Path, en_trb: Path) -> dict[str, int]:
    """Count JP entries whose text differs between the vanilla and English TRB."""
    lookup = tr.load_lookup(tr.LOOKUP_PATH)
    vanilla = tr.dump_entries(vanilla_trb.read_bytes(), lookup)
    english = tr.dump_entries(en_trb.read_bytes(), lookup)
    if len(vanilla) != len(english):
        raise SystemExit(
            f"entry count mismatch: vanilla {len(vanilla)} vs English {len(english)}. "
            "Rebuild the English TRB from the current baseline first."
        )

    total = translated = 0
    for van, eng in zip(vanilla, english):
        src = tr.normalize_newlines(van["text"])
        if not src or not tr.JP_RE.search(src):
            continue  # only entries that actually had Japanese to translate
        total += 1
        if src != tr.normalize_newlines(eng["text"]):
            translated += 1

    percent = round(translated / total * 100) if total else 0
    return {
        "scriptTranslated": translated,
        "scriptTotal": total,
        "scriptPercent": percent,
    }


def post_progress(endpoint: str, token: str, payload: dict[str, int]) -> None:
    # Cloudflare WAF (error 1010) rejects the default Python-urllib UA.
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "NLPP-EngPatcher-progress/1.0 (+https://github.com/czyrustuazon/NewLovePlusPlusEngPatcher)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", "replace")
            print(f"[progress] {response.status} {body}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"[progress] POST failed: HTTP {exc.code} {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"[progress] POST failed: {exc.reason}")


def try_report_progress(
    *,
    en_trb: Path | None = None,
    vanilla_trb: Path | None = None,
    endpoint: str | None = None,
    token: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Compute + optionally POST. Never raises — returns True if POST succeeded.

    Used by ``patch_textresource rebuild``, Drop CIA.bat, and nlpp-gold CI so a
    missing .env or a network blip never fails the primary job.

    When endpoint/token are unset (and not ``dry_run``), returns immediately
    without touching TRB files — patching still works on a clean clone.
    """
    if _progress_skipped():
        print("[progress] skipped (NLPP_PROGRESS_SKIP)")
        return False

    try:
        # Credentials first (unless dry-run): no .env → no TRB work, no failure.
        resolved_endpoint = load_endpoint(endpoint, required=False)
        resolved_token = load_token(token, required=False)
        if not dry_run and (not resolved_endpoint or not resolved_token):
            print(
                "[progress] skipped (optional): NLPP_PROGRESS_ENDPOINT / "
                "NLPP_PROGRESS_TOKEN not set"
            )
            return False

        en = Path(en_trb) if en_trb else DEFAULT_EN_TRB
        vanilla = Path(vanilla_trb) if vanilla_trb else paths.find_vanilla_main_trb()
        if not vanilla or not Path(vanilla).is_file():
            print("[progress] skipped: vanilla textresource_jpn.trb not found")
            return False
        if not en.is_file():
            print(f"[progress] skipped: English TRB not found ({en})")
            return False

        payload = script_progress(Path(vanilla), en)
        print(
            f"[progress] script text: {payload['scriptTranslated']}/{payload['scriptTotal']} "
            f"= {payload['scriptPercent']}%"
        )
        if dry_run:
            print(json.dumps(payload, indent=2))
            return False

        # resolved_* checked above; assert for type checkers.
        assert resolved_endpoint and resolved_token
        post_progress(resolved_endpoint, resolved_token, payload)
        return True
    except SystemExit as exc:
        # script_progress / post_progress use SystemExit for hard errors.
        msg = exc.code if isinstance(exc.code, str) else (exc.args[0] if exc.args else exc)
        print(f"[progress] soft-fail: {msg}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001 — never break callers
        print(f"[progress] soft-fail: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--vanilla-trb", type=Path, default=None,
        help="pristine JP textresource_jpn.trb (default: auto-detect)",
    )
    parser.add_argument(
        "--en-trb", type=Path, default=DEFAULT_EN_TRB,
        help=f"rebuilt English TRB (default: {DEFAULT_EN_TRB})",
    )
    parser.add_argument("--endpoint", default=None, help="admin progress URL (default: env / .env)")
    parser.add_argument("--token", default=None, help="admin bearer token (default: env / .env)")
    parser.add_argument("--dry-run", action="store_true", help="print the numbers, don't POST")
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help="never exit non-zero (skip POST if unset; soft-fail on network errors)",
    )
    args = parser.parse_args()

    if args.best_effort or args.dry_run:
        ok = try_report_progress(
            en_trb=args.en_trb,
            vanilla_trb=args.vanilla_trb,
            endpoint=args.endpoint,
            token=args.token,
            dry_run=args.dry_run,
        )
        return 0 if args.best_effort or args.dry_run or ok else 1

    # Strict CLI: missing paths / config / POST errors are fatal.
    if _progress_skipped():
        print("[progress] skipped (NLPP_PROGRESS_SKIP)")
        return 0

    vanilla = args.vanilla_trb or paths.find_vanilla_main_trb()
    if not vanilla or not Path(vanilla).is_file():
        raise SystemExit(
            "vanilla textresource_jpn.trb not found. Set NLPP_VANILLA_TRB or pass --vanilla-trb."
        )
    if not args.en_trb.is_file():
        raise SystemExit(
            f"English TRB not found: {args.en_trb}\n"
            "Run `py src/patch_textresource.py rebuild` first."
        )

    payload = script_progress(Path(vanilla), args.en_trb)
    print(
        f"[progress] script text: {payload['scriptTranslated']}/{payload['scriptTotal']} "
        f"= {payload['scriptPercent']}%"
    )
    post_progress(load_endpoint(args.endpoint), load_token(args.token), payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
