#!/usr/bin/env python3
"""Prints the build a DBCache.bin is for and the newest hotfix push it holds, as shell assignments:

    build=70009
    push=123456
    entries=812

The layout is XFTH v9, the one tools/db2tool/wdc/hotfix.go reads: a 44-byte header (magic, version,
build, a 32-byte hash), then entries of magic, region, push id, unique id, table hash, record id,
data size, status and padding (32 bytes), followed by the data.
"""
import struct
import sys

buf = open(sys.argv[1], "rb").read()
if buf[:4] != b"XFTH":
    sys.exit(f"{sys.argv[1]}: not a DBCache file")
version, build = struct.unpack_from("<II", buf, 4)
if version != 9:
    sys.exit(f"{sys.argv[1]}: DBCache version {version}, only 9 is read")

pos, push, entries = 44, 0, 0
while pos + 32 <= len(buf):
    if buf[pos:pos + 4] != b"XFTH":
        sys.exit(f"{sys.argv[1]}: bad entry magic at offset {pos}")
    _, push_id, _, _, _, size = struct.unpack_from("<iiiIii", buf, pos + 4)
    push = max(push, push_id)
    entries += 1
    pos += 32 + size

print(f"build={build}")
print(f"push={push}")
print(f"entries={entries}")
