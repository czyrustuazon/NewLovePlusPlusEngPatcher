# Contributing

Thanks for wanting to help translate New Love Plus+. This is a small fan project, not a
company — see the [companion site](https://github.com/czyrustuazon/NLPP-EngPatcher-Site)
for the public devlog and progress tracker, but this repo — the patcher, finished scripts,
and toolchain — is where the actual work happens and where volunteer tasks are tracked.

## Finding something to work on

Browse [open Issues](https://github.com/czyrustuazon/NewLovePlusPlusEngPatcher/issues),
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
is licensed under the terms in [`LICENSE`](./LICENSE) (MIT for this project's own code and
assets — see that file for what it does and doesn't cover, including third-party components
and game content).

## Code of conduct

Be decent. See [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).
