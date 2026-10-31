#!/usr/bin/env python3
"""Writes the Discord webhook message for one update: the pull request's title and link, the build and
hotfix lines, each class's spell changes and the item changes, read from the update's CHANGES.md.

    discord_message.py <CHANGES.md> <title> <pull request url> <CHANGES.md url> > message.json

A spell's ranks collapse into one name ("~Revenge ×6": six ranks changed). Discord caps an embed's description at
4096 characters, so the class lists stop short of that and the rest is counted under a link to
CHANGES.md. Mentions are turned off, so a spell or item name can never ping anyone.
"""
import collections
import json
import re
import sys

changes_path, title, pr_url, changes_url = sys.argv[1:5]
text = open(changes_path).read()

LIMIT = 3800
COLORS = {"Patch": 0xE67E22, "Hotfix": 0x3498DB}
ENTRY = re.compile(r"^- (added|removed|changed) \d+ (.+?)(?: \(Rank \d+\))?(?: · .+)?$")
MARKS = {"added": "+", "removed": "−", "changed": "~"}


def section(name):
    m = re.search(rf"^## {name}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def header(prefix):
    m = re.search(rf"^- {prefix}: (.+)$", text, re.M)
    return m.group(1) if m else "?"


def names(lines):
    """Each spell or item once, in order, with its rank count when it has more than one."""
    seen = collections.OrderedDict()
    for line in lines:
        m = ENTRY.match(line)
        if m:
            key = (m.group(1), m.group(2))
            seen[key] = seen.get(key, 0) + 1
    return [f"{MARKS[kind]}{name}" + (f" ×{n}" if n > 1 else "") for (kind, name), n in seen.items()]


blocks = []
for m in re.finditer(r"^### (.+?): (\d+) added, (\d+) removed, (\d+) changed\n(.*?)(?=^### |\Z)", section("Spells"), re.S | re.M):
    cls, added, removed, changed, body = m.groups()
    counts = ", ".join(f"{n} {word}" for n, word in ((added, "added"), (removed, "removed"), (changed, "changed")) if n != "0")
    blocks.append((f"**{cls}** ({counts})", names(body.splitlines())))

items = section("Items")
item_counts = (items.strip().splitlines() or ["0 added, 0 removed, 0 changed."])[0].rstrip(".")
blocks.append((f"**Items** ({item_counts})", names(items.splitlines())))

blocks = [b for b in blocks if b[1] or not b[0].startswith("**Items**")]
description, left = [], 0
for i, (head, entries) in enumerate(blocks):
    # Every later block keeps room for its count line; this block's names fill what is left.
    budget = LIMIT - sum(len(d) + 1 for d in description) - sum(len(h) + 12 for h, _ in blocks[i + 1:]) - len(head)
    shown = []
    for entry in entries:
        if len(", ".join(shown + [entry])) + 12 > budget:
            break
        shown.append(entry)
    rest = len(entries) - len(shown)
    left += rest
    description.append(head + (": " + ", ".join(shown) if shown else "") + (f" … +{rest}" if rest else ""))
if not description:
    description.append("No class spell or item changed.")
description.append(f"\n[CHANGES.md]({changes_url})" + (f": {left} more not listed here" if left else ""))

kind = title.split(":", 1)[0]
message = {
    "username": "WoWSims Game Data",
    "allowed_mentions": {"parse": []},
    "embeds": [{
        "title": title[:256],
        "url": pr_url,
        "color": COLORS.get(kind, 0x95A5A6),
        "description": "\n".join(description),
        "fields": [
            {"name": "Build", "value": header("Build")[:1024], "inline": True},
            {"name": "Hotfixes", "value": header("Hotfixes")[:1024], "inline": True},
        ],
        "footer": {"text": "+ added   − removed   ~ changed"},
    }],
}
json.dump(message, sys.stdout, ensure_ascii=False)
