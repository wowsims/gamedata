# gamedata

What changes in each WoW Classic Forever build and hotfix, read straight from the client data.

A scheduled workflow checks Blizzard's CDN and the latest hotfix cache every three hours. When either
one moves, it exports every class spell and every item, diffs them against the last export, and opens
and merges a pull request. **Each merged pull request is one update**, and its description lists what
changed.

## Layout

```
spells/<class>/
    <spec>.txt            the spec's talents and the spells of its skill line, one card per spell,
                          split by =======
    pets.txt              pet abilities (hunter, warlock)
    other.txt             the rest: set bonuses, item procs, NPC and leftover spells
items/items.txt           every item in the client, one card per item (collapsed in pull requests)
patches/<version>/
    patch/                the first export on this build
    hotfix-<push>/        a later export with newer hotfixes (<push> is the newest hotfix push id)
    resync-<date>/        a forced re-export with no game change (the export tools changed)
        CHANGES.md        what was added, removed or changed, and from which build and hotfixes
        spells.diff       each changed spell as a diff of its card
        items.txt         the cards of the items this update added
        items-removed.txt the removed items' cards
        items-changed.diff each changed item as a diff of its card
state.json                the build and hotfix push of the last export
```

Git history on `spells/` shows the same changes over time, e.g. `git log -p -- spells/hunter/`.

A spell's file comes from forever's generated talent trees first, then the spec skill line that
teaches it, then a same-named spell of the class that is already placed (other ranks), then the
placed spell that triggers it. Anything none of those places is in `other.txt`.

## Where the data comes from

- **Build:** `wow_classic_beta` as `us.version.battle.net` serves it, read off the CDN by
  [wowsims/forever](https://github.com/wowsims/forever)'s `tools/db2tool`.
- **Hotfixes:** raidbots' mirror of the client's `DBCache.bin`. It lags a build push, so a new build
  is recorded first without hotfixes (`patch/`), and the hotfixes follow as `hotfix-<push>/`.
- **Spells:** `tools/spelldata -dump` from forever, after `gen_spelldata -everyClassSpell` has built the
  spell store from every spell whose class family is a player class. Each card shows the row's columns
  in words and as the client's own values.
- **Items:** `scripts/export_items.py` over the same database. Stats come from the item's stat
  allocation and the `RandPropPoints` budget for its item level, quality and slot, and weapon damage
  comes from the `ItemDamage*` tables, as the client computes them. Base armor is not computed.

## Running it

The workflow runs on a schedule. To run it by hand, use **Actions → Update game data → Run workflow**.
`forever_ref` picks the forever commit to export with, and `force` records an export even when neither
the build nor the hotfixes moved.

To run it locally, with a forever checkout next to this one and its `tools/database/wowsims.db` built:

```sh
cd ../forever
go run ./tools/database/gen_spelldata -everyClassSpell -unchecked   # rewrites the store; git checkout it after
go run ./tools/spelldata -dump /tmp/dump
python3 ../gamedata/scripts/split_spells.py . tools/database/wowsims.db /tmp/dump /tmp/export/spells
python3 ../gamedata/scripts/export_items.py tools/database/wowsims.db /tmp/export/items/items.txt
cd ../gamedata
python3 scripts/record_update.py --repo . --export /tmp/export --version <version> --build <build> \
    --push <push> --hotfixes "<how>" --forever <sha>
```
