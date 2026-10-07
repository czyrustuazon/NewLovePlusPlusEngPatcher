"""Write a Luma code.ips that turns vanilla code.bin into a patched one.

  python tools/make_code_ips.py cache/vanilla_from_rom/exefs/code.bin release/name_input_code.bin out/code.ips

Luma applies luma/titles/<id>/code.ips to the decompressed .code in memory, as
an alternative to replacing code.bin. Offsets are into the decompressed code.
Untested on hardware (see docs/layeredfs-investigation.md).
"""
import sys


def main() -> None:
    van, new, out = sys.argv[1:4]
    v = open(van, 'rb').read(); o = open(new, 'rb').read()
    assert len(v) == len(o)
    GAP = 8
    recs = []; i = 0; n = len(v)
    while i < n:
        if v[i] != o[i]:
            s = i; last = i
            while i < n and (i - last) <= GAP:
                if v[i] != o[i]: last = i
                i += 1
            recs.append([s, last + 1])
        else:
            i += 1
    buf = bytearray(b'PATCH')
    for s, e in recs:
        if s == 0x454F46:  # offset bytes would spell EOF
            s -= 1
        while e - s > 0xFFFF:  # split oversized
            buf += s.to_bytes(3, 'big') + (0xFFFF).to_bytes(2, 'big') + o[s:s + 0xFFFF]
            s += 0xFFFF
        buf += s.to_bytes(3, 'big') + (e - s).to_bytes(2, 'big') + o[s:e]
    buf += b'EOF'
    open(out, 'wb').write(buf)
    # verify by applying
    t = bytearray(v); p = 5
    while buf[p:p + 3] != b'EOF':
        off = int.from_bytes(buf[p:p + 3], 'big'); sz = int.from_bytes(buf[p + 3:p + 5], 'big'); p += 5
        t[off:off + sz] = buf[p:p + sz]; p += sz
    print('records', len(recs), 'ips bytes', len(buf), 'roundtrip', bytes(t) == o)


if __name__ == "__main__":
    main()
