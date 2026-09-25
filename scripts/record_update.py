#!/usr/bin/env python3
"""Records one Forever update in the repository: diffs a fresh export against the files committed
now, writes what changed to its own folder under patches/<version>/, then replaces spells/ and
items/ with the export and moves state.json on.

    record_update.py --repo . --export <dir> --version 1.60.1.70009 --build 70009 \
        --pushes pushes.txt --hotfixes applied --forever <sha> [--body <file>]

pushes.txt is dbcache_info.py's list of the hotfix pushes the export applied (empty when it applied
none); it replaces hotfix-pushes.txt, and the pushes it adds are the update's hotfixes.

<dir> holds spells/<class>/<spec>.txt (split_spells.py) and items/items.txt (export_items.py).

The folder is patches/<version>/patch for the first update seen on a version, hotfix-<push> for a
later one with new hotfix pushes (hotfix-<lowest new push>+<n> when there are n more), and resync-<date> for a run forced without either moving (a change in
the export tools rather than in the game). It holds CHANGES.md, which is also the pull request's
body, items.txt with the cards of the items added, and a diff or card file for each other kind of
change there was.
"""
import argparse
import datetime
import difflib
import json
import os
import shutil
import sys

SEPARATOR = "=======\n"
# GitHub refuses a pull request body over 65536 characters.
BODY_LIMIT = 60000


def read_cards(path):
    """The cards of a dump by id, in file order."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    cards = {}
    for card in text.split(SEPARATOR):
        if card.strip():
            cards[card.split(" ", 1)[0]] = card
    return cards


def read_class(path):
    """The cards of every spec file of a class by id, and the spec file each one is in."""
    cards, specs = {}, {}
    if os.path.isdir(path):
        for file in sorted(os.listdir(path)):
            if file.endswith(".txt"):
                for id, card in read_cards(os.path.join(path, file)).items():
                    cards[id], specs[id] = card, file[:-4]
    return cards, specs


def read_pushes(path):
    """dbcache_info.py's push list: entries by push id."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {int(push): int(count) for push, count in (line.split() for line in f if line.strip())}


def heading(card):
    return card.split("\n", 1)[0]


def compare(old, new):
    added = [new[k] for k in new if k not in old]
    removed = [old[k] for k in old if k not in new]
    changed = [(old[k], new[k]) for k in new if k in old and old[k] != new[k]]
    return added, removed, changed


def card_diff(before, after):
    name = heading(after or before)
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), name, name, n=20))


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--export", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--build", required=True)
    p.add_argument("--pushes", required=True, help="dbcache_info.py's push list for the export")
    p.add_argument("--hotfixes", required=True, help="how the hotfixes went in, for CHANGES.md")
    p.add_argument("--forever", required=True, help="the forever commit the export ran from")
    p.add_argument("--body", help="where to also write the pull request body")
    args = p.parse_args()

    state_path = os.path.join(args.repo, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    old_pushes = read_pushes(os.path.join(args.repo, "hotfix-pushes.txt"))
    pushes = read_pushes(args.pushes)
    # A push whose entry count moved is new too: the push was extended.
    new_pushes = sorted(p for p in pushes if old_pushes.get(p) != pushes[p])

    if state.get("version") != args.version:
        label, kind = "patch", "Patch"
    elif new_pushes:
        label, kind = f"hotfix-{new_pushes[0]}" + (f"+{len(new_pushes) - 1}" if len(new_pushes) > 1 else ""), "Hotfix"
    else:
        label, kind = f"resync-{today}", "Resync"
    folder = os.path.join(args.repo, "patches", args.version, label)
    if os.path.exists(folder):
        label += f"-{datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S')}"
        folder = os.path.join(args.repo, "patches", args.version, label)
    first = not state

    named = ", ".join(map(str, new_pushes[:5])) + (f" and {len(new_pushes) - 5} more" if len(new_pushes) > 5 else "")
    lines = [f"# {kind}: {args.version}" + (f", hotfix push{'es' if len(new_pushes) > 1 else ''} {named}" if kind == "Hotfix" else ""), ""]
    lines.append(f"- Build: {args.version} (`wow_classic_beta` on Blizzard's CDN)")
    lines.append(f"- Hotfixes: {args.hotfixes}")
    if state:
        lines.append(f"- Previous: {state['version']} with {len(old_pushes)} hotfix pushes ({state.get('date', '?')})")
    lines.append(f"- Exported by wowsims/forever@{args.forever[:12]} on {today}")
    if kind == "Resync":
        lines.append("")
        lines.append("Neither the build nor the hotfixes moved: whatever changed here comes from the export tools, not the game.")
    if first:
        lines.append("")
        lines.append("First export: this is the baseline every later update diffs against, so there is nothing to compare yet.")
    lines.append("")

    if new_pushes and not first:
        lines.append("## Hotfix pushes")
        lines.append("")
        lines += [f"- {p}: {pushes[p]} entries" + (f" (was {old_pushes[p]})" if p in old_pushes else "") for p in new_pushes]
        lines.append("")

    # Spells, class by class.
    spell_diffs, summary = [], []
    old_dir = os.path.join(args.repo, "spells")
    new_dir = os.path.join(args.export, "spells")
    classes = sorted({c for d in (old_dir, new_dir) if os.path.isdir(d) for c in os.listdir(d)
                      if os.path.isdir(os.path.join(d, c))})
    for cls in classes:
        old, old_specs = read_class(os.path.join(old_dir, cls))
        new, new_specs = read_class(os.path.join(new_dir, cls))
        added, removed, changed = compare(old, new)
        if first or not (added or removed or changed):
            continue

        def line(verb, card, specs):
            return f"- {verb} {heading(card)} · {specs[card.split(' ', 1)[0]]}"

        summary.append(f"### {cls.capitalize()}: {len(added)} added, {len(removed)} removed, {len(changed)} changed")
        summary += [line("added", c, new_specs) for c in added]
        summary += [line("removed", c, old_specs) for c in removed]
        summary += [line("changed", a, new_specs) for _, a in changed]
        summary.append("")
        spell_diffs += [f"# {cls}\n"]
        spell_diffs += [card_diff("", c) for c in added]
        spell_diffs += [card_diff(c, "") for c in removed]
        spell_diffs += [card_diff(b, a) for b, a in changed]

    # Items.
    items_added, items_removed, items_changed = compare(read_cards(os.path.join(args.repo, "items", "items.txt")),
                                                        read_cards(os.path.join(args.export, "items", "items.txt")))
    if first:
        items_added = items_removed = items_changed = []

    lines.append("## Spells")
    lines.append("")
    lines += summary or ["No class spell changed.", ""]
    lines.append("## Items")
    lines.append("")
    if items_added or items_removed or items_changed:
        lines.append(f"{len(items_added)} added, {len(items_removed)} removed, {len(items_changed)} changed.")
        lines.append("")
        lines += [f"- added {heading(c)}" for c in items_added]
        lines += [f"- removed {heading(c)}" for c in items_removed]
        lines += [f"- changed {heading(a)}" for _, a in items_changed]
    else:
        lines.append("No item changed.")
    lines.append("")

    files = {}
    if spell_diffs:
        files["spells.diff"] = "".join(spell_diffs)
    if items_added:
        files["items.txt"] = SEPARATOR.join(items_added)
    if items_removed:
        files["items-removed.txt"] = SEPARATOR.join(items_removed)
    if items_changed:
        files["items-changed.diff"] = "".join(card_diff(b, a) for b, a in items_changed)
    if files:
        lines.append("## Files")
        lines.append("")
        lines += [f"- [`{name}`]({name})" for name in sorted(files)]
        lines.append("")

    changes = "\n".join(lines)
    files["CHANGES.md"] = changes
    for name, text in files.items():
        write(os.path.join(folder, name), text)

    # The export becomes the committed state.
    shutil.rmtree(old_dir, ignore_errors=True)
    shutil.copytree(new_dir, old_dir)
    os.makedirs(os.path.join(args.repo, "items"), exist_ok=True)
    shutil.copy(os.path.join(args.export, "items", "items.txt"), os.path.join(args.repo, "items", "items.txt"))
    shutil.copy(args.pushes, os.path.join(args.repo, "hotfix-pushes.txt"))
    with open(state_path, "w") as f:
        json.dump({"version": args.version, "build": int(args.build), "pushes": len(pushes), "date": today,
                   "forever": args.forever, "folder": os.path.relpath(folder, args.repo)}, f, indent=2)
        f.write("\n")

    if args.body:
        link = os.path.relpath(folder, args.repo)
        body = changes if len(changes) <= BODY_LIMIT else (
            changes[:BODY_LIMIT].rsplit("\n", 1)[0] + f"\n\n… cut short, the full list is in `{link}/CHANGES.md`.\n")
        write(args.body, body)

    print(f"folder={os.path.relpath(folder, args.repo)}")
    print(f"title={kind}: {args.version}" + (f" hotfix {named}" if kind == "Hotfix" else "") + f" ({today})")


if __name__ == "__main__":
    main()
