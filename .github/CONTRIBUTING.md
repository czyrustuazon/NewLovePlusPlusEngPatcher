# Contributing

Thanks for wanting to help translate New Love Plus+. This is a small fan project, not a
company — see the [companion site](https://newloveplus.loc.moe) ([source](https://github.com/czyrustuazon/NLPP-EngPatcher-Site))
for the public devlog and progress tracker, but this repo — the patcher, finished scripts,
and toolchain — is where the actual work happens and where volunteer tasks are tracked.

## Finding something to work on

Most leftover **dialogue / SMS / TRB / UI PNG** help is through the browser
[localization workbench](https://github.com/czyrustuazon/nlpp-localization-workbench)
(no Python). See root `README.md` → **Volunteer localization workbench**.

For patcher / RE / QA tasks, browse
[open Issues](https://github.com/czyrustuazon/NewLovePlusPlusEngPatcher/issues),
filtered by label:

| Label | What it means |
|---|---|
| `translation` | Translating script text |
| `editing` | Reviewing/polishing existing translations |
| `reverse-engineering` | Understanding game data formats, containers, code |
| `graphics` | Redrawing/inserting translated textures and UI |
| `qa-testing` | Playing through and reporting what's broken |
| `tooling` | Improvements to the patcher itself |
| `good-first-issue` | No prior context needed |

**To claim a task:** comment "I'll take this" on the Issue before starting. Standard
open-source etiquette, but worth stating plainly for anyone who hasn't contributed to a repo
before.

**Found a bug instead of picking up a task?** (patcher crashed, a translation is bugged
in-game) — that's a different door: open a
[Bug Report](https://github.com/czyrustuazon/NewLovePlusPlusEngPatcher/issues/new/choose)
issue, or mention it in the project Discord, rather than the task list.

## Getting started with Git & GitHub

If you've never used git before, here's what to install:

- [Git](https://git-scm.com/) itself
- A free GitHub account
- Any code editor — VS Code is a fine free default
- Optional: [GitHub Desktop](https://desktop.github.com/) if the command line feels
  intimidating at first

Then the workflow: **fork** this repo to your account → **clone** it locally → create a
**branch** → make your edit → **commit** and **push** → open a **pull request**. GitHub's
own [beginner docs](https://docs.github.com/en/get-started) cover the mechanics of each
step better than anything worth rewriting here.

## Before you open a pull request (patcher code)

```
pip install -r dev/requirements-dev.txt
python dev/install_hooks.py      # one time: runs the checks below on every push
python -m coverage run -m pytest tests/ -m "not local_data"
python dev/check_coverage.py     # coverage ratchet (CI runs it too)
```

- **Fixing a bug? Add a test that fails without your fix.** Put the specific cause in it
  (the address, byte pattern, or call order). A comment explains a crash; a test stops it
  coming back.
- **New `src/patch_*.py` or `tools/deploy_*.py`?** It needs a test that names it.
  `tests/test_every_module_tested.py` fails otherwise.
- **Coverage only goes up (goal: 100%).** `dev/check_coverage.py` fails if a file drops
  below its floor in `tests/snapshots/coverage_floor.json`, or if a new file is under
  100%. After adding tests, run `python dev/check_coverage.py --update` and commit the
  raised floors. See what is missing with `python -m coverage report -m --include=<file>`
  (or `python -m coverage html`, then open `htmlcov/index.html`).
- **Tests that need vanilla dumps, fonts or the Azahar fork** get
  `@pytest.mark.local_data`. They still run locally, but coverage leaves them out,
  since CI cannot run them. Code they cover still needs a test that runs without that data.
- **Changed what a patch writes?** The snapshot tests will fail on purpose. If the change
  is intended, refresh and commit the snapshots with your change, so reviewers see
  which caves and addresses moved:
  `NLPP_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_patch_blob_snapshots.py tests/test_code_patch_map.py`
- `tests/test_code_patch_map.py` needs a vanilla `code.bin`
  (`cache/vanilla_from_rom/exefs/code.bin` or `NLPP_VANILLA_CODE`). CI has none and
  skips it, so run it locally before pushing code.bin changes.

## Recommended tools — optional, not required

**[Ghidra](https://ghidra-sre.org/)** — free, open-source, the standard tool for digging
into the 3DS binary: disassembly, tracing how the game references its text and graphics
containers, understanding the `.trb` format from the inside.

**[Cursor](https://cursor.com/)** — worth mentioning mainly as a research accelerator, not
a coding assistant first: pointed at an unfamiliar binary-parsing function or this repo's
Python codebase, it's genuinely faster at "what does this do and why" than reading cold,
and useful for one-off extraction/insertion scripts. It's a paid tool (Cursor Pro, ~$20/month)
and entirely optional — contributors are just as welcome using VS Code, plain command-line
tools, or their own established RE workflow. This is "what's working for us," not a bar to
entry.

## License

By submitting a pull request, you agree your contribution to the EngPatcher original work
is licensed under the terms in [`LICENSE`](../LICENSE) (MIT for this project's own code and
assets — see that file for what it does and doesn't cover, including third-party components
and game content).

## Code of conduct

Be decent. See [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).
