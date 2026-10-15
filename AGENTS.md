# Agent notes (NewLovePlusPlusEngPatcher)

Project rules also live in `CLAUDE.md` and `.cursor/rules/*.mdc` (`alwaysApply`
ones apply every session).

## Commit messages (established style)

Match recent `git log` on the branch. Only commit when the user asks (or asks
to preserve WIP instead of stash — see `.cursor/rules/no-git-stash.mdc`).

- **Subject:** imperative, sentence case, ends with a period. One line that
  states the outcome for the game/patcher (not a file list).
  Example: `Restore Select Data NO DATA and post-game Title sheets in the bake.`
- **Body:** 1–3 short sentences on *why* / what was wrong. Concrete UI or
  package names are fine (`Vis_Dsel_Data`, pkg **5152**, HOME lock).
- **Not:** Conventional-Commit prefixes (`fix:`, `feat:`), issue-number-only
  subjects, or “WIP update” without substance (WIP is OK when parking work).
- Prefer PowerShell-safe commit text (here-string or `-m` twice); bash heredoc
  is not available in this shell.

## Deploy A → launch A (required)

When you **deploy / seed / combine into Azahar instance A** (`deploy-a`, or any
LayeredFS refresh that targets A):

1. Run the deploy (`.\ab_test\make.ps1 deploy-a`, etc.).
2. **Immediately launch** Azahar A: `.\ab_test\make.ps1 launch-a`.
3. Confirm `ab_test\azahar_instances\a\azahar.exe` is running.

Do **not** stop after copying files and tell the user to open Azahar. Same for
“run it” / “open it” after a deploy — launch the emulator.

If `img.bin` / `code.bin` just changed, prefer quitting any existing Azahar A
process first so LayeredFS reloads, then `launch-a`.

`deploy-b` → `launch-b` the same way when they ask for B.

Cursor rule: `.cursor/rules/deploy-a-launch.mdc`.
