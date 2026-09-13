"""HOME-menu SMDH + NCCH product-code metadata for patched CIAs.

Vanilla NLPP is a JP title (SMDH ニューラブプラス＋ / CTR-P-BLPJ). FBI and the
3DS HOME menu read the ExeFS ``icon`` SMDH, not TRB strings. We rewrite every
language slot to English, set a valid 3DS region lock, and retarget the NCCH
product code (J→E for USA). Title ID ``00040000000F4E00`` is unchanged so
saves / LayeredFS / SpotPass keep working.
"""

from __future__ import annotations

from pathlib import Path

SMDH_MAGIC = b"SMDH"
SMDH_SIZE = 0x36C0
N_LANGUAGES = 16
TITLE_SLOT = 0x200
SHORT_LEN = 0x80
LONG_LEN = 0x100
PUBLISHER_LEN = 0x80
TITLES_OFF = 0x08
REGION_LOCK_OFF = 0x2018

SHORT_TITLE = "New Love Plus+"
LONG_TITLE = "New Love Plus+"
PUBLISHER = "KONAMI"

# SMDH region lock-out bitmask (3dbrew). Bit set = that region may launch.
REGION_JAPAN = 0x01
REGION_USA = 0x02
REGION_EUROPE = 0x04
REGION_AUSTRALIA = 0x08
REGION_CHINA = 0x10
REGION_KOREA = 0x20
REGION_TAIWAN = 0x40
REGION_FREE = 0x7F

# CLI name → (lock mask, NCCH product code, summary label)
REGION_PRESETS: dict[str, tuple[int, str, str]] = {
    "usa": (REGION_USA, "CTR-P-BLPE", "USA (North America)"),
    "japan": (REGION_JAPAN, "CTR-P-BLPJ", "Japan"),
    "europe": (REGION_EUROPE, "CTR-P-BLPP", "Europe"),
    "free": (REGION_FREE, "CTR-P-BLPE", "Region Free"),
}

PRODUCT_CODE_LEN = 16
ICON_NAMES = ("icon.bin", "icon", ".icon")


def utf16_field(text: str, nbytes: int) -> bytes:
    """UTF-16LE, NUL-padded, always even, leaving room for a terminator."""
    raw = text.encode("utf-16le")
    limit = nbytes - 2 if nbytes >= 2 else 0
    if len(raw) > limit:
        raw = raw[:limit]
        if len(raw) % 2:
            raw = raw[:-1]
    return raw + b"\x00" * (nbytes - len(raw))


def title_slot(
    short: str = SHORT_TITLE,
    long: str = LONG_TITLE,
    publisher: str = PUBLISHER,
) -> bytes:
    blob = (
        utf16_field(short, SHORT_LEN)
        + utf16_field(long, LONG_LEN)
        + utf16_field(publisher, PUBLISHER_LEN)
    )
    if len(blob) != TITLE_SLOT:
        raise ValueError(f"title slot {len(blob):#x} != {TITLE_SLOT:#x}")
    return blob


def patch_smdh(
    data: bytes,
    *,
    short: str = SHORT_TITLE,
    long: str = LONG_TITLE,
    publisher: str = PUBLISHER,
    region_lock: int = REGION_USA,
) -> bytes:
    """Rewrite all 16 language slots + region lock. Icons / ratings stay."""
    if len(data) < SMDH_SIZE:
        raise ValueError(f"SMDH too small ({len(data)} < {SMDH_SIZE})")
    if data[:4] != SMDH_MAGIC:
        raise ValueError(f"not SMDH (magic={data[:4]!r})")
    buf = bytearray(data)
    slot = title_slot(short, long, publisher)
    for i in range(N_LANGUAGES):
        off = TITLES_OFF + i * TITLE_SLOT
        buf[off : off + TITLE_SLOT] = slot
    buf[REGION_LOCK_OFF : REGION_LOCK_OFF + 4] = int(region_lock).to_bytes(
        4, "little"
    )
    return bytes(buf)


def smdh_short_title(data: bytes, lang: int = 1) -> str:
    """Read a language slot's short title (0=JP, 1=EN)."""
    off = TITLES_OFF + lang * TITLE_SLOT
    raw = data[off : off + SHORT_LEN]
    return raw.decode("utf-16le", errors="replace").split("\x00", 1)[0]


def smdh_region_lock(data: bytes) -> int:
    return int.from_bytes(data[REGION_LOCK_OFF : REGION_LOCK_OFF + 4], "little")


def find_exefs_icon(exefs_dir: Path) -> Path:
    for name in ICON_NAMES:
        path = exefs_dir / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"no SMDH icon in {exefs_dir}")


def patch_icon_file(path: Path, *, region_lock: int = REGION_USA) -> None:
    raw = path.read_bytes()
    path.write_bytes(patch_smdh(raw, region_lock=region_lock))


def _ncch_product_off(header: bytes) -> int:
    if len(header) >= 0x160 and header[0x100:0x104] == b"NCCH":
        return 0x150
    if len(header) >= 0x60 and header[:4] == b"NCCH":
        return 0x50
    raise ValueError("not an NCCH header")


def read_ncch_product_code(header: bytes) -> str:
    off = _ncch_product_off(header)
    return header[off : off + PRODUCT_CODE_LEN].split(b"\x00", 1)[0].decode(
        "ascii", errors="replace"
    )


def patch_ncch_product_code(header: bytes, product_code: str) -> bytes:
    off = _ncch_product_off(header)
    buf = bytearray(header)
    blob = product_code.encode("ascii")[:PRODUCT_CODE_LEN]
    buf[off : off + PRODUCT_CODE_LEN] = blob.ljust(PRODUCT_CODE_LEN, b"\x00")
    return bytes(buf)


def resolve_region(name: str) -> tuple[int, str, str]:
    key = name.lower().strip()
    if key in ("na", "us", "north-america", "north_america"):
        key = "usa"
    if key not in REGION_PRESETS:
        raise ValueError(
            f"unknown CIA region {name!r} (use usa, japan, europe, or free)"
        )
    return REGION_PRESETS[key]
