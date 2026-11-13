---
name: script-review
description: >-
  Keeps Gemini machine lines in the volunteer review queue. Use when editing
  Nene or Rinko dialogue, ingesting a contributor pack, or syncing the
  workbench after an agent changes a machine-translated line.
---

You keep machine-translated dialogue in the review queue until a person signs it.

A line is machine text when it comes from `assets/gemini_heroines/` and no human changed it. Rewriting that line yourself does not review it. The workbench must still show it as needing work.

## Do

- Leave a contributor line a person wrote as the shipped text.
- When you change a machine line, add its dialog index to `assets/script_contrib/unreviewed.json` under the stem, then run `python tools/sync_workbench.py`.
- A line that still equals the Gemini pass also stays in the queue. `tools/sync_workbench.py` does that for a contributor stem that is not in `assets/gemini_heroines/proofread.json`.
- A stem in `proofread.json` is signed off. Do not put it back in the queue.

## Don't

- Do not add the stem to `REVIEWED_BY` in the workbench, or to `proofread.json`, for an edit you made.
- Do not treat a contributor file as proof that every line in it was reviewed. Lines the pack left equal to Gemini, and lines you rewrote, still need a person.
---
