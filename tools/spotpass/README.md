# SpotPass (`いつの間に通信`) inject for New Love Plus+

Title ID `00040000000F4E00`, BOSS extdata ID **`0x321`**, NsDataId **`1`**, payload file **`info.dat`**.

**Dump credit: Cetaceaqua** — thank you for providing the SpotPass archive (「とわのウォッチャー」第28号).

Long-form RE + Azahar HLE notes: EngPatcher root [`technical.md` §16](../../technical.md). User-facing summary: root [`README.md`](../../README.md#spotpass-とわのウォッチャー--boot-check).

## Bundled files (committed with the repo)

| File | Role |
|------|------|
| `info.dat` | Cleartext NsData payload (2324 bytes / `0x914`) |
| `info.dat.boss` | Encrypted CDN BOSS container (archive) |
| `info.dat.boss.decrypted` | Same container decrypted (payload header fields) |

A GitHub clone that includes this folder can rebuild injects with no extra downloads.

## How the inject is made

We do **not** edit the payload. We prepend a **0x34-byte Boss header** → **2376** bytes (`--real3ds`, default). For stock Azahar, optionally zero-pad to `0x7D004` (`--azahar`). See README / technical §16 for the shareable write-up and emulator NewFlag notes.

## Build

From EngPatcher root:

```bash
python tools/build_spotpass_inject.py              # default = real3ds
python tools/build_spotpass_inject.py --real3ds
python tools/build_spotpass_inject.py --azahar
python tools/build_spotpass_inject.py --azahar-exact
```

Also runs automatically at the end of `patch_cia` / the drop bat (default `real3ds`).

## Real 3DS (short)

1. Run NLPP once; enable SpotPass in network settings if available.
2. Build → put `out/spotpass_real3ds/info.dat` **only** under `…/00000321/boss/` (create `boss` on PC/GodMode9 if FBI has no SpotPass path).
3. Do **not** paste into Extra Data `user/`. Cold-boot.

StreetPass **Communication** (Girlfriend Comm / Business Card / Wireless Battle) is unrelated.
