# Release infra (gold publish)

You change assets/code in **this** EngPatcher repo. Gold binaries are built and
uploaded by **nlpp-gold-maker** (Ubuntu self-hosted → GitHub Releases; EngPatcher
workflow nickname: nlpp-gold).

## Publish a bake

Push or merge to **`main`** only (other branches do not trigger):

```bash
git push origin main
```

Workflow **Request gold Release** pings **nlpp-gold-maker**. If Release tag **`gold`**
already has `bake_img.bin`, the runner downloads it and refreshes TRB, chrome, and
name-input on that file instead of a full PNG pack. If `github.com:443` is unreachable,
it bakes offline from the vanilla files on the runner and does not upload a Release.
A run that will publish a new bake deletes Release tag **`gold`** first, so Drop
packs locally until the new bake is uploaded.
A full pack still runs when the Release is missing, PNG-pack inputs changed since the
published EngPatcher commit, or you dispatch with **force_pack**. The rolling Release tag stays **`gold`**:

- `bake_img.bin`
- `name_input_code.bin`
- `romfs_overlay.zip`

## Consume a bake

```bash
python tools/fetch_release_bake.py --repo OWNER/nlpp-gold-maker --tag gold
# or: set NLPP_GITHUB_REPO=OWNER/nlpp-gold-maker
```

## Setup secret (once)

EngPatcher → Settings → Secrets → `NLPP_GOLD_DISPATCH_TOKEN`  
= PAT that can dispatch workflows on **nlpp-gold-maker**.

Optional variable: `NLPP_GOLD_REPO=OWNER/nlpp-gold-maker` (workflow already
defaults to `<owner>/nlpp-gold-maker`).

Docs / runner: local `Documents/nlpp-gold` or the GitHub **nlpp-gold-maker** repo.

## Companion site progress bar (script text)

After each gold bake, nlpp-gold-maker runs `engpatcher/src/report_progress.py` and
POSTs `scriptTranslated` / `scriptTotal` / `scriptPercent` to the companion
site Worker (`POST /api/admin/progress`). The site bar reads `GET /api/progress`
live (~30 s edge cache) — no site rebuild.

On **nlpp-gold-maker** (Actions secrets, not the public EngPatcher repo):

| Secret | Value |
|--------|--------|
| `NLPP_PROGRESS_ENDPOINT` | `https://newloveplus.loc.moe/api/admin/progress` |
| `NLPP_PROGRESS_TOKEN` | Prefer Worker `PROGRESS_API_TOKEN` (progress-only). `ADMIN_API_TOKEN` works but also gates `/api/admin/devlog`. |

Local / Drop CIA auto-report uses EngPatcher `.env` (`NLPP_PROGRESS_*`).  
Disable anywhere with `NLPP_PROGRESS_SKIP=1`. Manual: `.\ab_test\make.ps1 progress`.
