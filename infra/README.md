# Release infra (gold publish)

You change assets/code in **this** EngPatcher repo. Gold binaries are built and
uploaded by **nlpp-gold** (Ubuntu self-hosted → GitHub Releases).

## Publish a bake

Push or merge to **`main`** only (other branches do not trigger):

```bash
git push origin main
```

Workflow **Request gold Release** pings nlpp-gold, which rebuilds from that
commit and updates the rolling Release tag **`gold`**:

- `bake_img.bin`
- `romfs_overlay.zip`

## Consume a bake

```bash
python tools/fetch_release_bake.py --repo OWNER/nlpp-gold --tag gold
# or: set NLPP_GITHUB_REPO=OWNER/nlpp-gold
```

## Setup secret (once)

EngPatcher → Settings → Secrets → `NLPP_GOLD_DISPATCH_TOKEN`  
= PAT that can dispatch workflows on nlpp-gold.

Docs / runner: local `Documents/nlpp-gold` or the GitHub nlpp-gold repo (`infra/`).

## Companion site progress bar (script text)

After each gold bake, nlpp-gold runs `engpatcher/src/report_progress.py` and
POSTs `scriptTranslated` / `scriptTotal` / `scriptPercent` to the companion
site Worker (`POST /api/admin/progress`). The site bar reads `GET /api/progress`
live (~30 s edge cache) — no site rebuild.

On **nlpp-gold** (Actions secrets, not the public EngPatcher repo):

| Secret | Value |
|--------|--------|
| `NLPP_PROGRESS_ENDPOINT` | `https://newloveplus.loc.moe/api/admin/progress` |
| `NLPP_PROGRESS_TOKEN` | Prefer Worker `PROGRESS_API_TOKEN` (progress-only). `ADMIN_API_TOKEN` works but also gates `/api/admin/devlog`. |

Local / Drop CIA auto-report uses EngPatcher `.env` (`NLPP_PROGRESS_*`).  
Disable anywhere with `NLPP_PROGRESS_SKIP=1`. Manual: `.\make.ps1 progress`.
