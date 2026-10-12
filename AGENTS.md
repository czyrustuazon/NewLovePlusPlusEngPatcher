# Agent notes (NewLovePlusPlusEngPatcher)

Project rules also live in `CLAUDE.md` and `.cursor/rules/*.mdc` (`alwaysApply`
ones apply every session).

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
