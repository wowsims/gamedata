#!/usr/bin/env python3
"""Writes the Discord webhook messages for one update: the pull request's title and link, the build and
hotfix lines, and each spell and item change linked to Wowhead with what changed below it, read from the
update folder's CHANGES.md, spells.diff and items-changed.diff.

    discord_message.py <update folder> <title> <pull request url> <CHANGES.md url> <out dir>

writes <out dir>/1.json, 2.json, ... to post in order, in Discord's markdown. Each class opens with a
heading and its counts. A spell's ranks collapse into one line ("~ Revenge ×6", linked to the highest
rank, marked 🟢 added, 🔴 removed or 🟠 changed), and each changed field sits below it, indented as a
tree, with its values: the one value that moved ("effect 3: `10 → 30`"), the
whole old and new value of a short field ("sells: `7 silver` → `9 silver`"), or the value of a new or
removed field ("+ binds: `binds when equipped`"); text fields share one line. A new spell or item shows
its key values the same way (effects, cost and cooldown; item type, level, stats and effects). Discord caps an embed's
description at 4096 characters and a message at 6000, so the detail scales with the update: the most
detailed level whose every entry fits in MESSAGES messages is used (each field on a line, then all of
an entry's fields on one line, then names alone, then names in a paragraph per class, then the same
without the Wowhead links, then counts alone), and past that the rest is counted under a link to CHANGES.md. Mentions are turned off, so a
spell or item name can never ping anyone.
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
FIELDS_SHOWN = 6
# The longest old and new value, together, a detail line shows whole.
WHOLE_LIMIT = 80
# What a new spell or item shows below it, in this order.
ADDED_FIELDS = {
    "spell": ["effect 1", "effect 2", "effect 3", "cost", "cooldown", "cast", "duration", "range"],
    "item": ["item", "level", "stats", "weapon", "effect", "binds"],
}
COLORS = {"Patch": 0xE67E22, "Hotfix": 0x3498DB}
ENTRY = re.compile(r"^- (added|removed|changed) (\d+) (.+?)(?: \(Rank \d+\))?(?: · .+)?$")
# Discord colors no text in an embed outside code blocks, where links stop working, so the kind of
# change is a colored marker.
MARKS = {"added": "🟢", "removed": "🔴", "changed": "🟠"}
TEXT_FIELDS = {"tooltip", "aura", "vars", "text"}
# Fields a reader learns nothing from: the spells a card names, its label ids, its Wowhead link.
SKIPPED_FIELDS = {"refs", "labels", "https"}
TWO_WORD_FIELDS = {("stance", "exclude"), ("caster", "aura")}
# A detail line sits under its spell or item, drawn as a tree: every line but the last branches off,
# the last closes it. Discord trims leading spaces in an embed, so the indent is an em space.
BRANCH, LAST = "\u2003├ ", "\u2003└ "


def section(name):
    m = re.search(rf"^## {name}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def header(prefix):
    m = re.search(rf"^- {prefix}: (.+)$", text, re.M)
    return m.group(1) if m else "?"


def split_field(body):
    """A card line's field name and value: one word, or "effect N", "stance exclude", "caster aura"."""
    words = body.split()
    n = 2 if len(words) > 1 and (words[0] == "effect" and words[1].isdigit() or tuple(words[:2]) in TWO_WORD_FIELDS) else 1
    return " ".join(words[:n]), " ".join(words[n:])


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
        if not body.strip():
            continue
        if not body.startswith(" "):
            # A card's first line is its id and name; every other unindented line opens a field.
            if body.split()[0] == card:
                field, value = "name", body
            else:
                field, value = split_field(body)
        else:
            value = body.strip()
        if sign in "-+" and card and field and field not in SKIPPED_FIELDS:
            fields[card][field][0 if sign == "-" else 1].append(value)
    return fields


def card_fields(path):
    """Each card's fields from a file of whole cards split by =======: {id: {field: lines}}."""
    cards = collections.defaultdict(lambda: collections.defaultdict(list))
    if not os.path.exists(path):
        return cards
    card, field = None, None
    for line in open(path):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("======="):
            card = None if line.startswith("=======") else card
            continue
        if card is None:
            card = line.split()[0]
            continue
        if not line.startswith(" "):
            field, value = split_field(line)
        else:
            value = line.strip()
        if field not in SKIPPED_FIELDS:
            cards[card][field].append(value)
    return cards


def summary(card, keys):
    """A new spell's or item's key values, one line each, the ones too long or unreadable left out."""
    out = []
    for key in keys:
        lines = card.get(key)
        if key == "effect" and lines:
            # A recipe's "use: 402265 Learning" line is the same on every recipe; what it teaches is the news.
            lines = [re.sub(r"\b\d{4,} ", "", line) for line in lines if "402265 Learning" not in line]
        if key == "range" and lines and lines[0].startswith("50000"):
            lines = None
        if lines:
            value = " · ".join(lines[:2]) if key == "effect" else lines[0]
            value = re.sub(r" \(at level \d+\)", "", value)
            if len(value) <= WHOLE_LIMIT and not unreadable(value):
                out.append(f"{key}: `{value}`")
    return out


def single_move(a, b):
    """The one value that moved between two versions of a card line, as "old → new", or None."""
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return None
    moved = [(x.strip("(),;"), y.strip("(),;")) for x, y in zip(ta, tb) if x.strip("(),;") != y.strip("(),;")]
    if len(moved) != 1:
        return None
    x, y = moved[0]
    if "=" in x and x.split("=")[0] == y.split("=")[0]:
        key = x.split("=")[0]
        return f"{key} {x[len(key) + 1:]} → {y[len(key) + 1:]}"
    return f"{x} → {y}"


def unreadable(value):
    # Class masks, flags, the row's enum names and the card's "unrecognised shape" say nothing in a chat line.
    return "0x" in value or "unrecognised shape" in value or bool(re.search(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", value))


def describe(field, old, new):
    """How one changed field reads below its spell or item, or None for a text field, which only the
    field's name stands for. A field one value of which moved shows that value; a new or removed field,
    or a short one that moved in several places, shows its whole value. An effect's first line says it
    in words and the next repeats it as the row's values, so the words are what is read, unless only
    the values moved."""
    if field == "name":
        ranks = [re.search(r"\(Rank (\d+)\)$", lines[-1]) for lines in (old, new) if lines]
        if len(ranks) == 2 and all(ranks):
            return f"`rank {ranks[0].group(1)} → {ranks[1].group(1)}`"
        names = [lines[-1].split(" ", 1)[-1] for lines in (old, new) if lines]
        return f"renamed: `{names[0]} → {names[1]}`" if len(names) == 2 else "renamed"
    if field in TEXT_FIELDS:
        return None
    if not old or not new:
        sign, value = ("+", new[0]) if new else ("−", old[0])
        return f"{sign} {field}: `{value}`" if len(value) <= WHOLE_LIMIT and not unreadable(value) else f"{sign} {field}"
    a, b = (re.sub(r" \(at level \d+\)", "", v) for v in (old[0], new[0]))
    if a == b and len(old) > 1 and len(new) > 1:
        a, b = old[1], new[1]
    move = single_move(a, b)
    if move and not unreadable(move):
        return f"{field}: `{move}`"
    if len(a) + len(b) <= WHOLE_LIMIT and not unreadable(a + b):
        return f"{field}: `{a}` → `{b}`"
    return field


def block_for(body, kind_url, diff, added_cards):
    """Each spell or item once, its ranks collapsed, in the order CHANGES.md lists them: its linked
    line and, for a changed one, its changed fields."""
    seen = collections.OrderedDict()
    for line in body.splitlines():
        m = ENTRY.match(line)
        if m:
            seen.setdefault((m.group(1), m.group(3)), []).append(m.group(2))
    entries = []
    for (kind, name), ids in seen.items():
        line = f"{MARKS[kind]} [{name}](https://www.wowhead.com/forever/{kind_url}={ids[-1]})" + (f" ×{len(ids)}" if len(ids) > 1 else "")
        subs = []
        if kind == "added":
            card = added_cards.get(ids[-1]) or {field: new for field, (_, new) in diff.get(ids[-1], {}).items()}
            subs = summary(card, ADDED_FIELDS[kind_url])
        if kind == "changed":
            fields = collections.OrderedDict()
            for i in ids:
                for field, (old, new) in diff.get(i, {}).items():
                    fields.setdefault(field, describe(field, old, new))
            subs = [shown for shown in fields.values() if shown]
            texts = [field for field, shown in fields.items() if not shown]
            if texts:
                subs.append(", ".join(texts))
        plain = f"{MARKS[kind]} {name}" + (f" ×{len(ids)}" if len(ids) > 1 else "")
        entries.append((line, subs, plain))
    return entries


def render(blocks, level):
    """The message's pieces at one level of detail: 0 puts each changed field on its own line, 1 puts
    an entry's fields on one line, 2 lists the entries alone, 3 packs a class's entries into one
    paragraph, 4 does the same without the links, 5 keeps only each class's counts. A class opens with
    a heading and its counts as subtext, or at level 5 with one bold line."""
    pieces = []
    for name, counts, entries in blocks:
        head = f"### {name}"
        if level == 5:
            pieces.append(("head", f"**{name}** · {counts}", head))
            continue
        pieces.append(("head", f"{head}\n-# {counts}", head))
        if level in (3, 4):
            paragraph = ""
            for line, _, plain in entries:
                line = line if level == 3 else plain
                if paragraph and len(paragraph) + len(line) > 1000:
                    pieces.append(("entry", paragraph, head))
                    paragraph = ""
                paragraph += (" · " if paragraph else "") + line
            if paragraph:
                pieces.append(("entry", paragraph, head))
            continue
        for line, subs, _ in entries:
            if level == 0:
                shown = subs[:FIELDS_SHOWN] + ([f"{len(subs) - FIELDS_SHOWN} more"] if len(subs) > FIELDS_SHOWN else [])
                line += "".join(f"\n{LAST if n == len(shown) - 1 else BRANCH}{sub}" for n, sub in enumerate(shown))
            elif level == 1 and subs:
                line += f"\n{LAST}" + " · ".join(subs)
            pieces.append(("entry", line, head))
    return pieces


def pack(pieces):
    """The pieces packed into embeds and the embeds into messages, and the number of entries that did
    not fit. A class that runs on into a new embed repeats its header there."""
    messages, embed, size, total = [[]], [], 0, 0
    for i, (kind, piece, head) in enumerate(pieces):
        cost = len(piece) + 1
        if size + cost > EMBED_LIMIT or total + cost > MESSAGE_LIMIT:
            messages[-1].append(embed)
            embed, size = [], 0
            if total + cost > MESSAGE_LIMIT or len(messages[-1]) == 10:
                if len(messages) == MESSAGES:
                    return messages, sum(1 for k, _, _ in pieces[i:] if k == "entry")
                messages.append([])
                total = 0
            if kind == "entry":
                embed.append(f"{head} (cont.)")
                size += len(head) + 9
                total += len(head) + 9
        embed.append(piece)
        size += cost
        total += cost
    if embed:
        messages[-1].append(embed)
    return messages, 0


spell_diff = changed_fields(os.path.join(folder, "spells.diff"))
item_diff = changed_fields(os.path.join(folder, "items-changed.diff"))

blocks = []
for m in re.finditer(r"^### (.+?): (\d+) added, (\d+) removed, (\d+) changed\n(.*?)(?=^### |\Z)", section("Spells"), re.S | re.M):
    cls, added, removed, changed, body = m.groups()
    counts = ", ".join(f"{n} {word}" for n, word in ((added, "added"), (removed, "removed"), (changed, "changed")) if n != "0")
    blocks.append((cls, counts, block_for(body, "spell", spell_diff, {})))
items = section("Items")
item_entries = block_for(items, "item", item_diff, card_fields(os.path.join(folder, "items.txt")))
if item_entries:
    m = re.match(r"(\d+) added, (\d+) removed, (\d+) changed", items.strip())
    counts = ", ".join(f"{n} {word}" for n, word in zip(m.groups(), ("added", "removed", "changed")) if n != "0") if m else ""
    blocks.append(("Items", counts, item_entries))

# The most detailed level whose every entry fits; past the most compact one the rest is counted.
if blocks:
    for level in range(6):
        messages, left = pack(render(blocks, level))
        if not left:
            break
    if left:
        level = 4
        messages, left = pack(render(blocks, level))
    print(f"detail level {level}, {len(messages)} message(s), {left} entries not listed", file=sys.stderr)
else:
    messages, left = pack([("head", "No class spell or item changed.", "")])
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
            embed["footer"] = {"text": "🟢 added   🔴 removed   🟠 changed   ×N ranks"}
        out.append(embed)
    message = {"username": "WoWSims Game Data", "allowed_mentions": {"parse": []}, "embeds": out}
    with open(os.path.join(out_dir, f"{n}.json"), "w") as f:
        json.dump(message, f, ensure_ascii=False)
