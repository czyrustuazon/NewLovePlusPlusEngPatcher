"""Tiny synthetic img.bin / PACK / DARC / BCLIM builders for deploy_* tests.

CI has no game data. These build the same container layout the game uses
(parsed by tools/nlpp-tools/img), so deploy scripts run their real main()
on a few KB instead of the 680MB img.bin.

    arc = darc({"timg/A.bclim": bclim(8, 8, 8)})
    pkg = package([("Foo.arc", arc)])
    img_path.write_bytes(img({5259: pkg}))

Package elements are zlib level 1, so exact-slot recompression (zopfli or
gap-tune) always has room to hit the original slot size.

use_paths() points a deploy module's path constants at tmp_path. Use it in
every test that runs main(): the real defaults write into release/, out/ and
the Azahar LayeredFS img.bin.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

NLPP_TOOLS = Path(__file__).resolve().parents[1] / "tools" / "nlpp-tools"
if str(NLPP_TOOLS) not in sys.path:
    sys.path.insert(0, str(NLPP_TOOLS))

IMG_BLOCK = 0x800
PKG_ENTRY = 0x20


def _align(x: int, a: int) -> int:
    return (x + a - 1) // a * a


def bclim(width: int, height: int, fmt: int = 8, pixels: bytes | None = None) -> bytes:
    """BCLIM: tiled pixels + CLIM header + imag block. Default fmt 8 (RGBA4444).

    Default pixels are zero, padded to the power-of-two canvas like the game's.
    """
    from bclimutil import rectangular_pot

    if pixels is None:
        pot_w, pot_h = rectangular_pot(width, height)
        if fmt == 0xB:  # ETC1A4: 16 bytes per 4x4 block
            pixels = bytes(pot_w * pot_h)
        else:
            bpp = {0: 1, 1: 1, 2: 1, 3: 2, 5: 2, 6: 3, 8: 2, 9: 4}[fmt]
            pixels = bytes(pot_w * pot_h * bpp)
    imag = struct.pack("<4sIHHII", b"imag", 0x14, width, height, fmt, len(pixels))
    size = len(pixels) + 0x14 + len(imag)
    clim = struct.pack("<4sHHIIHH", b"CLIM", 0xFEFF, 0x14, 0x02020000, size, 1, 0)
    return pixels + clim + imag


def darc(files: dict[str, bytes], align: int = 0x80) -> bytes:
    """DARC with a root, '.', and one level of subdirectories."""
    groups: dict[str, list[tuple[str, bytes]]] = {}
    for rel, data in files.items():
        d, _, name = rel.rpartition("/")
        groups.setdefault(d, []).append((name, data))
    # (name, is_dir, parent_or_None, payload)
    rows: list[tuple[str, bool, bytes | None]] = [("", True, None), (".", True, None)]
    dir_rows: list[int] = []
    for d in sorted(groups):
        if d:
            dir_rows.append(len(rows))
            rows.append((d, True, None))
        rows.extend((n, False, data) for n, data in groups[d])
    count = len(rows)

    names = bytearray()
    name_offs = []
    for name, _, _ in rows:
        name_offs.append(len(names))
        names += name.encode("utf-16le") + b"\0\0"
    table_off = 0x1C
    table_size = count * 12 + len(names)
    data_start = _align(table_off + table_size, align)

    blob = bytearray()
    entries = []
    dir_end = {}
    for i, idx in enumerate(dir_rows):
        dir_end[idx] = dir_rows[i + 1] if i + 1 < len(dir_rows) else count
    for i, (name, is_dir, data) in enumerate(rows):
        if is_dir:
            parent, end = (0, count) if i < 2 else (1, dir_end[i])
            entries.append(struct.pack("<III", name_offs[i] | 0x01000000, parent, end))
            continue
        blob += bytes(_align(len(blob), align) - len(blob))
        entries.append(struct.pack("<III", name_offs[i], data_start + len(blob), len(data)))
        blob += data

    out = bytearray(b"darc" + b"\xff\xfe" + struct.pack("<H", 0x1C))
    out += struct.pack("<IIIII", 0x01000000, 0, table_off, table_size, data_start)
    out += b"".join(entries) + names
    out += bytes(data_start - len(out))
    out += blob
    struct.pack_into("<I", out, 0x0C, len(out))
    return bytes(out)


def package(elements: list[tuple], *, typ0: bool = True) -> bytes:
    """PACK blob. Each element is (name, data) or (name, data, type, compressed).

    Default type is b"ARC " and compressed (zlib level 1).
    """
    norm = [e if len(e) == 4 else (*e, b"ARC ", True) for e in elements]
    cnt = len(norm)
    str_off = (cnt + 1) * PKG_ENTRY
    strs = bytearray()
    slots = []
    for name, *_ in norm:
        slots.append(len(strs))
        strs += name.encode("utf-8") + b"\0"
    ptr_off = str_off + len(strs)
    cur = _align(ptr_off + 4 * cnt, 0x10)

    body = bytearray()
    table = []
    dec_off = 0
    for name, data, typ, cmp in norm:
        stored = zlib.compress(data, 1) if cmp else data
        off = cur + len(body)
        if cmp:
            table.append(struct.pack("<4s4x6I", typ, len(data), dec_off, 0, 1, len(stored), off))
        else:
            table.append(struct.pack("<4s4x6I", typ, len(data), off, 0, 0, 0, 0))
        dec_off = _align(dec_off + len(data), 0x80)
        body += stored
        body += bytes(_align(len(body), 0x10) - len(body))
    total = cur + len(body)
    head = struct.pack(
        "<6sH6I", b"PACK\n0" if typ0 else b"PACK\n ", cnt, ptr_off, str_off, cur, dec_off, total, 0
    )
    out = bytearray(head + b"".join(table) + strs + struct.pack(f"<{cnt}I", *slots))
    out += bytes(cur - len(out))
    out += body
    return bytes(out)


def img(packages: dict[int, bytes], count: int | None = None, raw: dict[int, bytes] | None = None) -> bytes:
    """img.bin with PAK entries at the given indices (others empty).

    raw: non-package resources {index: bytes} (type b"RAW ").
    """
    raw = raw or {}
    used = {**{i: (b"PAK ", p) for i, p in packages.items()}, **{i: (b"RAW ", r) for i, r in raw.items()}}
    count = count if count is not None else max(used) + 1
    idx = bytearray()
    for i in range(count):
        typ, data = used.get(i, (b"\0\0\0\0", b""))
        idx += struct.pack("<4s4x2I2xBB", typ, len(data), 0, 0, 0x30 if typ == b"PAK " else 0x8)
    off_table = len(idx)
    offs = bytearray(struct.pack("<4x2I", len(used), 0x1C4B4))
    blobs = bytearray()
    first = _align(IMG_BLOCK + off_table + len(offs) + 8 * len(used), IMG_BLOCK)
    for i in sorted(used):
        addr = first + len(blobs)
        offs += struct.pack("<2I", i, (addr >> 11) - 1)
        data = used[i][1]
        blobs += data + bytes(_align(len(data), IMG_BLOCK) - len(data))
    head = struct.pack("<10I", 0xA, (first >> 11) - 1, 1, 0, count, off_table, 1, 0, 0, 0x276F4)
    out = bytearray(head) + bytes(IMG_BLOCK - len(head)) + idx + offs
    out += bytes(first - len(out))
    out += blobs
    return bytes(out)


def read_package(img_path: Path, index: int) -> bytes:
    """Package bytes at ``index`` (as ie unpack would write them)."""
    from img import Image  # nlpp-tools, on sys.path via conftest

    image = Image(str(img_path))
    try:
        image.parse(False)
        return image.entries[index].fw.read()
    finally:
        image.fh.close()


def read_element(pkg: bytes, name: str, tmp: Path) -> bytes:
    """Decompressed element ``name`` from a PACK blob."""
    from img import FileWindow, Package

    path = tmp / f"_pkg_{name}"
    path.write_bytes(pkg)
    p = Package(FileWindow(str(path)), 0)
    p.parse(False)
    for e in p.entries:
        if e.fn == name:
            return e.read()
    raise KeyError(name)


def use_paths(monkeypatch, tmp_path: Path, *modules, **extra: Path) -> dict[str, Path]:
    """Point path constants of deploy modules (and deploy_common) at tmp_path.

    Patches every module passed plus the globals of their deploy_common
    functions, since scripts copy names with ``from deploy_common import``.
    Returns the paths used.
    """
    paths = {
        "BAKE_IMG": tmp_path / "release" / "bake_img.bin",
        "AZAHAR_MOD_IMG": tmp_path / "azahar" / "img.bin",
        "AZAHAR_INSTANCES": tmp_path / "azahar_instances",
        "AZAHAR_MOD_TRB_DIR": tmp_path / "azahar" / "trb",
        "TEXTRESOURCE": tmp_path / "release" / "textresource",
        "OVERLAY_TRB_DIR": tmp_path / "overlay" / "trb",
        "ROMFS_OVERLAY": tmp_path / "overlay",
        "RELEASE": tmp_path / "release",
        "OUT": tmp_path / "out",
        **extra,
    }
    monkeypatch.setenv("NLPP_ALSO_AZAHAR", "0")
    monkeypatch.setenv("NLPP_NO_IMG_BACKUP", "1")
    namespaces = []
    for mod in modules:
        namespaces.append(vars(mod))
        for fn_name in ("iter_deploy_targets", "resolve_resident_trb", "maybe_backup_img", "resolve_img_paths"):
            fn = getattr(mod, fn_name, None)
            if fn is not None and fn.__globals__ is not vars(mod):
                namespaces.append(fn.__globals__)
    for ns in namespaces:
        for key, value in paths.items():
            if key in ns:
                monkeypatch.setitem(ns, key, value)
    return paths
