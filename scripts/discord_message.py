#!/usr/bin/env python3
"""Writes the Discord webhook messages for one update: the pull request's title and link, the build and
hotfix lines, and one line per spell and item change, each linked to Wowhead and naming what changed,
read from the update folder's CHANGES.md, spells.diff and items-changed.diff.

    discord_message.py <update folder> <title> <pull request url> <CHANGES.md url> <out dir>

writes <out dir>/1.json, 2.json, ... to post in order. A spell's ranks collapse into one line
("~ Revenge ×6", linked to the highest rank). A changed card names its changed fields, with the old and
new value when a field moved by one or two values ("effect 3: 10%→30%"). Discord caps an embed's
description at 4096 characters and a message at 6000, so the lines run over up to MESSAGES messages
and the rest is counted under a link to CHANGES.md. Mentions are turned off, so a spell or item name
can never ping anyone.
"""
import collections
import json
import os
import re
import sys

folder, title, pr_url, changes_url, out_dir = sys.argv[1:6]
text = open(os.path.join(folder, "CHANGES.md")).read()

MESSAGES = 3
EMBED_LIMIT = 3900
MESSAGE_LIMIT = 5600
COLORS = {"Patch": 0xE67E22, "Hotfix": 0x3498DB}
ENTRY = re.compile(r"^- (added|removed|changed) (\d+) (.+?)(?: \(Rank \d+\))?(?: · .+)?$")
MARKS = {"added": "+", "removed": "−", "changed": "~"}
TEXT_FIELDS = {"tooltip", "aura", "vars", "text"}


def section(name):
    m = re.search(rf"^## {name}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def header(prefix):
    m = re.search(rf"^- {prefix}: (.+)$", text, re.M)
    return m.group(1) if m else "?"


def changed_fields(path):
    """Each card's changed fields from a diff of cards: {id: {field: (old lines, new lines)}}."""
    fields = collections.defaultdict(lambda: collections.defaultdict(lambda: ([], [])))
    if not os.path.exists(path):
        return fields
    card, field = None, None
    for line in open(path):
        line = line.rstrip("\n")
        if line.startswith("+++ ") or line.startswith("@@") or line.startswith("# "):
            continue
        if line.startswith("--- "):
            card, field = line.split()[1], None
            continue
        sign, body = line[:1], line[1:]
        if not body.strip() or body.startswith("https://"):
            continue
        if not body.startswith(" "):
            # A card's first line is its id and name; every other unindented line opens a field.
            field = "name" if body.split()[0] == card else re.split(r"\s{2,}", body, maxsplit=1)[0]
            value = re.split(r"\s{2,}", body, maxsplit=1)[1] if field != "name" and re.search(r"\s{2,}", body) else body
        else:
            value = body.strip()
        if sign in "-+" and card and field:
            fields[card][field][0 if sign == "-" else 1].append(value)
    return fields


def describe(field, old, new):
    """The field's name, with its old and new value when one or two of its values moved. An effect's
    first line says it in words and the next repeats it as the row's values, so the first line that
    moved is the one shown."""
    if field == "name":
        ranks = [re.search(r"\(Rank (\d+)\)$", line[-1]) for line in (old, new) if line]
        if len(ranks) == 2 and all(ranks):
            return f"rank {ranks[0].group(1)}→{ranks[1].group(1)}"
        return "renamed"
    if field in TEXT_FIELDS or len(old) != len(new) or not old:
        return field
    for a, b in zip(old, new):
        ta, tb = a.split(), b.split()
        if len(ta) != len(tb):
            return field
        moved = []
        for x, y in zip(ta, tb):
            x, y = x.strip("(),;"), y.strip("(),;")
            if x != y:
                key = x.split("=")[0] if "=" in x and x.split("=")[0] == y.split("=")[0] else ""
                moved.append(f"{key} {x[len(key) + 1:]}→{y[len(key) + 1:]}" if key else f"{x}→{y}")
        if moved:
            # Class masks and flags read as hex, which says nothing in a chat line.
            if len(moved) <= 2 and sum(len(m) for m in moved) <= 50 and "0x" not in "".join(moved):
                return f"{field}: " + ", ".join(moved)
            return field
    return field


def lines_for(body, kind_url, diff):
    """One line per spell or item, its ranks collapsed, in the order CHANGES.md lists them."""
    seen = collections.OrderedDict()
    for line in body.splitlines():
        m = ENTRY.match(line)
        if m:
            seen.setdefault((m.group(1), m.group(3)), []).append(m.group(2))
    out = []
    for (kind, name), ids in seen.items():
        link = f"[{name}](https://www.wowhead.com/forever/{kind_url}={ids[-1]})"
        line = f"{MARKS[kind]} {link}" + (f" ×{len(ids)}" if len(ids) > 1 else "")
        if kind == "changed":
            merged = collections.OrderedDict()
            for i in ids:
                for field, (old, new) in diff.get(i, {}).items():
                    merged.setdefault(field, describe(field, old, new))
            if merged:
                line += " · " + ", ".join(list(merged.values())[:4]) + (" …" if len(merged) > 4 else "")
        out.append(line)
    return out


spell_diff = changed_fields(os.path.join(folder, "spells.diff"))
item_diff = changed_fields(os.path.join(folder, "items-changed.diff"))

lines = []
for m in re.finditer(r"^### (.+?): (\d+) added, (\d+) removed, (\d+) changed\n(.*?)(?=^### |\Z)", section("Spells"), re.S | re.M):
    cls, added, removed, changed, body = m.groups()
    counts = ", ".join(f"{n} {word}" for n, word in ((added, "added"), (removed, "removed"), (changed, "changed")) if n != "0")
    lines.append(f"**{cls}** ({counts})")
    lines += lines_for(body, "spell", spell_diff)
items = section("Items")
item_lines = lines_for(items, "item", item_diff)
if item_lines:
    lines.append(f"**Items** ({items.strip().splitlines()[0].rstrip('.')})")
    lines += item_lines
if not lines:
    lines.append("No class spell or item changed.")

# Pack the lines into embeds and the embeds into messages, then count what did not fit.
messages, embed, size, total = [[]], [], 0, 0
for i, line in enumerate(lines):
    if size + len(line) + 1 > EMBED_LIMIT or total + len(line) + 1 > MESSAGE_LIMIT:
        messages[-1].append(embed)
        embed, size = [], 0
        if total + len(line) + 1 > MESSAGE_LIMIT or len(messages[-1]) == 10:
            if len(messages) == MESSAGES:
                break
            messages.append([])
            total = 0
    embed.append(line)
    size += len(line) + 1
    total += len(line) + 1
else:
    i = len(lines)
if embed:
    messages[-1].append(embed)
left = sum(1 for line in lines[i:] if not line.startswith("**"))
messages[-1][-1].append(f"\n[CHANGES.md]({changes_url})" + (f": {left} more not listed here" if left else ""))

kind = title.split(":", 1)[0]
color = COLORS.get(kind, 0x95A5A6)
os.makedirs(out_dir, exist_ok=True)
for n, embeds in enumerate(messages, 1):
    out = []
    for e, body in enumerate(embeds):
        embed = {"color": color, "description": "\n".join(body)}
        if n == 1 and e == 0:
            embed.update({"title": title[:256], "url": pr_url})
        if n == len(messages) and e == len(embeds) - 1:
            embed["fields"] = [
                {"name": "Build", "value": header("Build")[:1024], "inline": True},
                {"name": "Hotfixes", "value": header("Hotfixes")[:1024], "inline": True},
            ]
            embed["footer"] = {"text": "+ added   − removed   ~ changed   ×N ranks"}
        out.append(embed)
    message = {"username": "WoWSims Game Data", "allowed_mentions": {"parse": []}, "embeds": out}
    with open(os.path.join(out_dir, f"{n}.json"), "w") as f:
        json.dump(message, f, ensure_ascii=False)
