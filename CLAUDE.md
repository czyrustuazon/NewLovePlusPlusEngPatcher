# Agent rules for NewLovePlusPlusEngPatcher

Project rules also live in `.cursor/rules/*.mdc`; the `alwaysApply` ones apply
to every agent, not only Cursor. Short cross-tool notes: `AGENTS.md`
(commit message style + deploy-a → launch-a).

## HARD REQUIREMENT: after deploy-a, launch Azahar A

Do not stop at LayeredFS copy. After `.\ab_test\make.ps1 deploy-a` (or any
instance-A refresh), run `.\ab_test\make.ps1 launch-a` and confirm
`ab_test\azahar_instances\a\azahar.exe` is running. Same for B → `launch-b`.
Details: `AGENTS.md`, `.cursor/rules/deploy-a-launch.mdc`.

## HARD REQUIREMENT: workbench English fits 30 columns (choices 28)

The game cuts talk text at 30 columns and choice buttons at 28, mid-word
(`FUN_005bf750`, see `src/dialog_wrap.py`). Count columns the game's way:
ASCII = 1, anything else = 2 (`？`, `…`, `！`), name markers at their
`dialog_wrap.MARKER_COLUMNS` budget (`▲高嶺＊＊▲` = 8).

- The Scripts kit (`../nlpp-localization-workbench/kit/NLPP_Translate.html`)
  warns on every over-width line and blocks Save on any edited line that
  does not fit. Do not remove or loosen that gate, or change its widths
  without changing `dialog_wrap.py` to match.
- `tools/sync_workbench.py` must keep writing `choices` per script, or
  choice buttons fall back to the 30-column talk limit.
- English you write for a script line (agent edits included) breaks with
  `\n` so each line fits 30 (28 on a choice button).
- Audit as a stem enters the patcher, not before. When a pack is ingested
  (`tools/ingest_pack.py` warns on each too-wide changed line), a review
  lands in `assets/script_contrib`, or a stem joins
  `assets/gemini_heroines/proofread.json`, run
  `python tools/audit_dialog_width.py <stem>` and re-break or shorten every
  line it lists before committing. Keep the contributor's wording; move the
  break, or trim only as much as fitting needs. Already-shipped lines in
  stems nobody is adding stay as they are (the patcher re-wraps them at
  spaces on inject); the kit only warns on those.

## HARD REQUIREMENT: hardware-accurate Azahar goes in azahar-3ds-accurate

Any change that makes Azahar behave more like real 3DS hardware belongs in the
fork **azahar-3ds-accurate**, not only in this repo:

- local checkout: `../azahar-3ds-accurate` (override with `NLPP_AZAHAR_FORK`)
- branch `main` = NLPP changes; branch `upstream` = pristine upstream Azahar
- remote `origin` = `git@github.com:czyrustuazon/azahar-3ds-accurate.git`

That covers:

- new or changed `NLPP_EMU_*` crash replays (one per Luma3DS dump worth guarding),
- exception reporting, MMU / data-abort / prefetch-abort behavior,
- FS / service behavior that differs from hardware (e.g. `OpenLinkFile`),
- anything that changes `ab_test/patches/azahar-*.patch`.

Every such change is unfinished until all of these are done, in order:

1. **Commit** it on `main` in `../azahar-3ds-accurate`. Describe the hardware
   behavior and the Luma dump it matches in the message.
2. **Do not push.** Never run `git push` in the fork. The owner pushes. End
   your report with the exact command for them:
   `git -C "../azahar-3ds-accurate" push -u origin main upstream`
3. Regenerate the exports here: `python tools/export_azahar_patches.py`, and
   commit the changed `ab_test/patches/*.patch` with the EngPatcher change.
4. Update the fork's `NLPP.md` table when a replay or behavior is added.
5. Tell the owner that, after their push, the gold runner needs
   `sudo bash scripts/setup-smoke-runner.sh` (nlpp-gold-maker) to rebuild its
   Azahar, and local A/B needs `.\ab_test\make.ps1 build-azahar`.

Also:

- Never commit to the fork's `upstream` branch except a pristine upstream
  import (procedure in the fork's `NLPP.md`).
- Never open pull requests or issues on azahar-emu/azahar. Azahar's
  `AI-POLICY.md` bans AI-written contributions; fork code is not upstreamable.
- Never edit `ab_test/patches/azahar-*.patch` by hand.
  `tests/test_export_azahar_patches.py` fails when they differ from the fork.
- `../azahar` (remote `nlpp`) is the old local build checkout, superseded by
  `../azahar-3ds-accurate`. Do not commit NLPP changes there.
