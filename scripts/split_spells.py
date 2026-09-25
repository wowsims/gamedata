#!/usr/bin/env python3
"""Splits tools/spelldata -dump's <class>.txt files into one file per spec:

    <out>/<class>/<spec>.txt   the tree's talents and the spells of its skill line
    <out>/<class>/pets.txt     hunter and warlock pet abilities
    <out>/<class>/other.txt    everything else: set bonuses, triggered spells, racials, ...

A spell goes to the first of:
  1. the talent tab forever's generated trees (ui/sim/talents/trees/<class>.json) put it in;
  2. the spec skill line SkillLineAbility teaches it through;
  3. the file of a spell of the same class and name that 1 or 2 placed (a talent's other ranks, the
     spells an ability triggers under its own name);
  4. the file of a placed spell that triggers it, followed as far as the triggers go;
and to other.txt when none of them places it.

    split_spells.py <forever checkout> <wowsims.db> <dump dir> <out dir>
"""
import json
import os
import sqlite3
import sys

SEPARATOR = "=======\n"
SPEC_SKILL_CATEGORY = 7
# Skill lines named differently from the talent tab they are.
SKILL_ALIASES = {"Shadow Magic": "Shadow", "Elemental Combat": "Elemental"}


def slug(name):
    return name.lower().replace(" ", "-")


def main(forever, db_path, dump_dir, out_dir):
    db = sqlite3.connect(db_path)
    names = dict(db.execute("SELECT ID, Name_lang FROM SpellName"))
    triggers = {}
    for spell, triggered in db.execute("SELECT SpellID, EffectTriggerSpell FROM SpellEffect WHERE EffectTriggerSpell > 0 ORDER BY ID"):
        triggers.setdefault(spell, []).append(triggered)
    skills = {}
    for spell, name, category in db.execute("""SELECT sla.Spell, sl.DisplayName_lang, sl.CategoryID
                                               FROM SkillLineAbility sla JOIN SkillLine sl ON sl.ID = sla.SkillLine
                                               ORDER BY sla.ID"""):
        skills.setdefault(spell, []).append((name, category))

    for file in sorted(os.listdir(dump_dir)):
        if not file.endswith(".txt"):
            continue
        cls = file[:-4]
        with open(os.path.join(dump_dir, file), encoding="utf-8") as f:
            cards = [c for c in f.read().split(SEPARATOR) if c.strip()]
        ids = [int(c.split(" ", 1)[0]) for c in cards]

        tabs = []
        talent_tab = {}
        trees = os.path.join(forever, "ui", "sim", "talents", "trees", f"{cls}.json")
        if os.path.exists(trees):
            for tab in json.load(open(trees)):
                tabs.append(tab["name"])
                for talent in tab["talents"]:
                    talent_tab[talent["spellId"]] = tab["name"]

        placed = {}
        for id in ids:
            if id in talent_tab:
                placed[id] = talent_tab[id]
                continue
            for name, category in skills.get(id, []):
                name = SKILL_ALIASES.get(name, name)
                if name.startswith("Pet - "):
                    placed[id] = "Pets"
                    break
                if category == SPEC_SKILL_CATEGORY and name in tabs:
                    placed[id] = name
                    break

        by_name = {}
        for id in ids:
            if id in placed:
                by_name.setdefault(names.get(id), placed[id])
        for id in ids:
            if id not in placed and names.get(id) in by_name:
                placed[id] = by_name[names.get(id)]
        in_class = set(ids)
        queue = [id for id in ids if id in placed]
        while queue:
            id = queue.pop()
            for triggered in triggers.get(id, []):
                if triggered in in_class and triggered not in placed:
                    placed[triggered] = placed[id]
                    queue.append(triggered)

        files = {}
        for id, card in zip(ids, cards):
            spec = placed.get(id, "Other")
            files.setdefault(slug(spec), []).append(card)

        os.makedirs(os.path.join(out_dir, cls), exist_ok=True)
        for spec, spec_cards in sorted(files.items()):
            with open(os.path.join(out_dir, cls, f"{spec}.txt"), "w", encoding="utf-8") as f:
                f.write(SEPARATOR.join(spec_cards))
        print(f"{cls}: " + ", ".join(f"{spec} {len(c)}" for spec, c in sorted(files.items())), file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:])
