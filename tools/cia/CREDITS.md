# Vendored CIA toolchain (Windows x64)

Pinned binaries used by `src/patch_cia.py`. Prefer these on-disk copies;
`src/setup_tools.py` only downloads if a file is missing (optional refresh).

| File | Upstream | Pinned |
|------|----------|--------|
| `3dstool/3dstool.exe` | [dnasdw/3dstool](https://github.com/dnasdw/3dstool) | v1.2.6 |
| `ctrtool.exe` | [3DSGuy/Project_CTR](https://github.com/3DSGuy/Project_CTR) | ctrtool v1.2.1 (win_x64) |
| `makerom.exe` | [3DSGuy/Project_CTR](https://github.com/3DSGuy/Project_CTR) | makerom v0.19.0 (win_x86_64) |
| `seeddb.bin` | [ihaveamac/3DS-rom-tools](https://github.com/ihaveamac/3DS-rom-tools) | snapshot at vendor time |
| `decrypt.exe` | Not stored here — copied from `../Batch-CIA-3DS-Decryptor-Redux/` by `setup_tools.py` | see that folder’s `CREDITS.md` |

Release URLs (fallback fetch only):

- https://github.com/dnasdw/3dstool/releases/download/v1.2.6/3dstool.zip
- https://github.com/3DSGuy/Project_CTR/releases/download/ctrtool-v1.2.1/ctrtool-v1.2.1-win_x64.zip
- https://github.com/3DSGuy/Project_CTR/releases/download/makerom-v0.19.0/makerom-v0.19.0-win_x86_64.zip
- https://raw.githubusercontent.com/ihaveamac/3DS-rom-tools/master/seeddb/seeddb.bin
