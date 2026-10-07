## What and why

<!-- What changed, and what in-game behavior it fixes or adds. Link the Issue. -->

## Checklist

- [ ] Bug fix: added a test that fails without this fix
- [ ] New `patch_*` / `deploy_*` module: has a test that names it
- [ ] Snapshot files changed only because I meant to change patch output
- [ ] code.bin change: ran `tests/test_code_patch_map.py` locally with a vanilla code.bin (CI skips it)
- [ ] Tested in-game (Azahar or hardware) if this changes game behavior
