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
