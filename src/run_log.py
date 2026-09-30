"""One patch log at ``out/log.txt``.

Gold rebuild writes the image-pack report and rebuild summary. The CIA patch
appends the PATCH SUMMARY. No ``out/logs/`` folder and no timestamped copies.
"""

from __future__ import annotations

from pathlib import Path

import nlpp_paths as paths


def default_log_path() -> Path:
    return paths.OUT_LOG


def write_log(text: str, *, dest: Path | None = None, append: bool = False) -> Path | None:
    """Write ``text`` to the run log. Never raises."""
    path = dest if dest is not None else default_log_path()
    body = text if text.endswith("\n") else text + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.is_file() and path.stat().st_size > 0:
            existing = path.read_text(encoding="utf-8", errors="replace")
            if not existing.endswith("\n"):
                existing += "\n"
            path.write_text(existing + "\n" + body, encoding="utf-8")
        else:
            path.write_text(body, encoding="utf-8")
        return path
    except OSError as exc:
        print(f"[log] warning: could not write {path}: {exc}", flush=True)
        return None
