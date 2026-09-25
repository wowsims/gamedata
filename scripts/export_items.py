#!/usr/bin/env python3
"""Writes every item in forever's client database (tools/database/wowsims.db) to one text file,
one card per item sorted by id, split by a line of =======.

Stats and weapon damage are worked out the way the client does, from the tables the database
carries (RandPropPoints, ItemDamage*), so a hotfix to a budget or a damage table shows on every
item it moves.

    export_items.py <wowsims.db> <out.txt>
"""
import math
import os
import sqlite3
import sys

QUALITY = ["poor", "common", "uncommon", "rare", "epic", "legendary", "artifact", "heirloom"]

INVTYPE = {
    1: "head", 2: "neck", 3: "shoulders", 4: "shirt", 5: "chest", 6: "waist", 7: "legs", 8: "feet",
    9: "wrists", 10: "hands", 11: "finger", 12: "trinket", 13: "one-hand", 14: "shield", 15: "ranged",
    16: "back", 17: "two-hand", 18: "bag", 19: "tabard", 20: "chest", 21: "main hand", 22: "off hand",
    23: "held in off hand", 24: "ammo", 25: "thrown", 26: "ranged", 27: "quiver", 28: "relic",
}

STAT = {
    0: "mana", 1: "health", 3: "agility", 4: "strength", 5: "intellect", 6: "spirit", 7: "stamina",
    12: "defense rating", 13: "dodge rating", 14: "parry rating", 15: "block rating",
    16: "melee hit rating", 17: "ranged hit rating", 18: "spell hit rating",
    19: "melee crit rating", 20: "ranged crit rating", 21: "spell crit rating",
    28: "melee haste rating", 29: "ranged haste rating", 30: "spell haste rating",
    31: "hit rating", 32: "crit rating", 35: "resilience rating", 36: "haste rating",
    37: "expertise rating", 38: "attack power", 39: "ranged attack power", 40: "feral attack power",
    41: "healing", 42: "spell damage", 43: "mana per 5 sec", 44: "armor penetration rating",
    45: "spell power", 46: "health per 5 sec", 47: "spell penetration", 48: "block value",
    50: "armor", 51: "fire resistance", 52: "frost resistance", 53: "holy resistance",
    54: "shadow resistance", 55: "nature resistance", 56: "arcane resistance",
    83: "weapon damage", 84: "holy damage", 85: "fire damage", 86: "nature damage",
    87: "frost damage", 88: "shadow damage", 89: "arcane damage", 124: "all resistances",
}

TRIGGER = {0: "use", 1: "equip", 2: "chance on hit", 4: "soulstone", 5: "use (no delay)", 6: "learn"}

BONDING = {1: "binds when picked up", 2: "binds when equipped", 3: "binds when used", 4: "quest item"}

CLASSES = ["warrior", "paladin", "hunter", "rogue", "priest", "death knight", "shaman", "mage",
           "warlock", "monk", "druid"]

WEAPON, ARMOR = 2, 4
CASTER_WEAPON = 0x200


def arr(text):
    return [float(v) for v in text.strip("[]").split(",")] if text else []


# The column of RandPropPoints an item's stats are budgeted from, as dbc.Item.GetRandomSuffixType.
def budget_slot(cls, sub, inv):
    if cls == WEAPON:
        if sub in (1, 5, 6, 8, 10):
            return 0
        if sub in (2, 3, 16, 18, 19):
            return 4
        return 3
    if cls == ARMOR:
        if inv in (1, 5, 7, 20):
            return 0
        if inv in (3, 6, 8, 10, 12):
            return 1
        if inv in (2, 9, 11, 14, 16, 22, 23, 28):
            return 2
    return -1


def damage_table(inv, sub, flags1):
    caster = flags1 & CASTER_WEAPON
    if inv in (13, 21, 22):
        return "ItemDamageOneHandCaster" if caster else "ItemDamageOneHand"
    if inv == 17:
        return "ItemDamageTwoHandCaster" if caster else "ItemDamageTwoHand"
    if inv in (15, 25, 26):
        return {2: "ItemDamageRanged", 3: "ItemDamageRanged", 18: "ItemDamageRanged",
                16: "ItemDamageThrown", 19: "ItemDamageWand"}.get(sub)
    return None


def num(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def main(db_path, out_path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    budgets = {}
    for r in db.execute("SELECT ID, Good, Superior, Epic FROM RandPropPoints"):
        budgets[r["ID"]] = {2: arr(r["Good"]), 3: arr(r["Superior"]), 4: arr(r["Epic"])}

    damage = {}
    for table in ("ItemDamageOneHand", "ItemDamageOneHandCaster", "ItemDamageTwoHand",
                  "ItemDamageTwoHandCaster", "ItemDamageRanged", "ItemDamageThrown", "ItemDamageWand"):
        damage[table] = {r["ItemLevel"]: arr(r["Quality"]) for r in db.execute(f"SELECT ItemLevel, Quality FROM {table}")}

    classes = {r["ClassID"]: r["ClassName_lang"] for r in db.execute("SELECT ClassID, ClassName_lang FROM ItemClass")}
    subclasses = {(r["ClassID"], r["SubClassID"]): r["DisplayName_lang"] or r["VerboseName_lang"]
                  for r in db.execute("SELECT ClassID, SubClassID, DisplayName_lang, VerboseName_lang FROM ItemSubClass")}
    sets = {r["ID"]: r["Name_lang"] for r in db.execute("SELECT ID, Name_lang FROM ItemSet")}
    spell_names = {r["ID"]: r["Name_lang"] for r in db.execute("SELECT ID, Name_lang FROM SpellName")}
    name_descs = {r["ID"]: r["Description_lang"] for r in db.execute("SELECT ID, Description_lang FROM ItemNameDescription")}

    effects = {}
    for r in db.execute("""SELECT x.ItemID, e.TriggerType, e.SpellID, e.Charges, e.CoolDownMSec, e.CategoryCoolDownMSec
                           FROM ItemXItemEffect x JOIN ItemEffect e ON e.ID = x.ItemEffectID
                           ORDER BY x.ItemID, e.LegacySlotIndex, e.ID"""):
        effects.setdefault(r["ItemID"], []).append(r)

    rows = db.execute("""SELECT s.*, i.ClassID, i.SubclassID FROM ItemSparse s
                         LEFT JOIN Item i ON i.ID = s.ID ORDER BY s.ID""").fetchall()

    cards = []
    for r in rows:
        cls, sub, inv = r["ClassID"], r["SubclassID"], r["InventoryType"]
        quality = r["OverallQualityID"]
        flags1 = int(arr(r["Flags"])[1]) if r["Flags"] else 0
        lines = [f"{r['ID']} {r['Display_lang']}"]

        kind = [QUALITY[quality] if 0 <= quality < len(QUALITY) else f"quality {quality}"]
        if cls is not None:
            kind.append(subclasses.get((cls, sub)) or classes.get(cls, f"class {cls}"))
        if inv in INVTYPE:
            kind.append(INVTYPE[inv])
        lines.append(f"{'item':<9} {', '.join(kind)}")

        level = f"ilvl {r['ItemLevel']}"
        if r["RequiredLevel"]:
            level += f", requires level {r['RequiredLevel']}"
        lines.append(f"{'level':<9} {level}")
        if r["ItemNameDescriptionID"] in name_descs:
            lines.append(f"{'tag':<9} {name_descs[r['ItemNameDescriptionID']]}")
        if r["Bonding"] in BONDING:
            lines.append(f"{'binds':<9} {BONDING[r['Bonding']]}")
        if r["MaxCount"] == 1:
            lines.append(f"{'unique':<9} yes")
        if r["AllowableClass"] not in (-1, 0):
            lines.append(f"{'classes':<9} " + ", ".join(c for i, c in enumerate(CLASSES) if r["AllowableClass"] & (1 << i)))

        # Legendaries and above are budgeted as epics, which is what the client does.
        slot = budget_slot(cls, sub, inv)
        budget = 0
        if slot >= 0 and r["ItemLevel"] in budgets and quality >= 2:
            budget = budgets[r["ItemLevel"]][min(quality, 4)][slot]
        stat_ids = [int(v) for v in arr(r["StatModifier_bonusStat"])]
        allocs = arr(r["StatPercentEditor"])
        stats = []
        for sid, alloc in zip(stat_ids, allocs):
            if sid < 0 or alloc == 0:
                continue
            value = round(alloc * budget * 0.0001) if budget else None
            stats.append(f"+{value} {STAT.get(sid, f'stat {sid}')}" if value is not None
                         else f"{STAT.get(sid, f'stat {sid}')} (allocation {num(alloc)}, no budget)")
        if stats:
            lines.append(f"{'stats':<9} " + ", ".join(stats))

        if cls == WEAPON and r["ItemDelay"]:
            speed = r["ItemDelay"] / 1000
            weapon = f"speed {speed:.2f}"
            table = damage_table(inv, sub, flags1)
            dps_row = damage.get(table, {}).get(r["ItemLevel"]) if table else None
            if dps_row:
                dps = dps_row[min(quality, 4) if quality > 6 else quality]
                bonus = r["QualityModifier"] * speed
                low = max(math.floor(dps * speed * (1 - r["DmgVariance"] / 2) + bonus), 1)
                high = max(math.floor(dps * speed * (1 + r["DmgVariance"] / 2) + bonus + 0.5), 1)
                weapon = f"{low} - {high} damage, {weapon}, {num(round((low + high) / 2 / speed, 1))} dps"
            lines.append(f"{'weapon':<9} {weapon}")

        for e in effects.get(r["ID"], []):
            text = f"{TRIGGER.get(e['TriggerType'], 'trigger ' + str(e['TriggerType']))}: {e['SpellID']} {spell_names.get(e['SpellID'], '?')}"
            extra = []
            # A negative count is the client's "destroyed when the charges run out".
            if e["Charges"]:
                count = abs(e["Charges"])
                extra.append(f"{count} charge{'s' if count > 1 else ''}" + (", consumed" if e["Charges"] < 0 else ""))
            if e["CoolDownMSec"] > 0:
                extra.append(f"{num(e['CoolDownMSec'] / 1000)} s cooldown")
            if e["CategoryCoolDownMSec"] > 0:
                extra.append(f"{num(e['CategoryCoolDownMSec'] / 1000)} s shared cooldown")
            if extra:
                text += f" ({', '.join(extra)})"
            lines.append(f"{'effect':<9} {text}")

        if r["ItemSet"] in sets:
            lines.append(f"{'set':<9} {sets[r['ItemSet']]}")
        if r["Description_lang"]:
            lines.append(f"{'text':<9} \"{r['Description_lang']}\"")
        if r["SellPrice"]:
            lines.append(f"{'sells':<9} {r['SellPrice']} copper")

        cards.append("\n".join(lines) + "\n")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("=======\n".join(cards))
    print(f"items: {len(cards)} items", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:])
