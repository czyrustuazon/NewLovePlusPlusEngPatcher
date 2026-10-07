# Agent rules for NewLovePlusPlusEngPatcher

Project rules also live in `.cursor/rules/*.mdc`; the `alwaysApply` ones apply
to every agent, not only Cursor.

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
