#!/usr/bin/env python3
"""Reads a DBCache.bin: prints the build it is for as shell assignments, and writes every hotfix push
it holds to <pushes file>, one `<push id> <entries>` line per push, sorted by push id.

    dbcache_info.py DBCache.bin pushes.txt
    build=70009
    pushes=4343
    entries=36624

Push ids are not in time order: a push made today can carry a lower id than one from last week, so
it is the set of pushes that says whether the hotfixes moved, never the highest id. Entries under a
push id of 0 or below are left out: they are records the client cached while looking items up, not
hotfixes, and their count grows whenever it browses (raidbots leaves them out of its count too).

The layout is XFTH v9, the one tools/db2tool/wdc/hotfix.go reads: a 44-byte header (magic, version,
build, a 32-byte hash), then entries of magic, region, push id, unique id, table hash, record id,
data size, status and padding (32 bytes), followed by the data.
"""
import collections
import struct
import sys

path, pushes_path = sys.argv[1:3]
buf = open(path, "rb").read()
if buf[:4] != b"XFTH":
    sys.exit(f"{path}: not a DBCache file")
version, build = struct.unpack_from("<II", buf, 4)
if version != 9:
    sys.exit(f"{path}: DBCache version {version}, only 9 is read")

pos, pushes = 44, collections.Counter()
while pos + 32 <= len(buf):
    if buf[pos:pos + 4] != b"XFTH":
        sys.exit(f"{path}: bad entry magic at offset {pos}")
    _, push_id, _, _, _, size = struct.unpack_from("<iiiIii", buf, pos + 4)
    if push_id > 0:
        pushes[push_id] += 1
    pos += 32 + size

with open(pushes_path, "w") as f:
    f.writelines(f"{push} {count}\n" for push, count in sorted(pushes.items()))

print(f"build={build}")
print(f"pushes={len(pushes)}")
print(f"entries={sum(pushes.values())}")
