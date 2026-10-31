#!/usr/bin/env bash
# Renders one recorded update with scripts/discord_message.py and posts it to a Discord webhook, as the
# workflow's "Post to Discord" step does, so a change to the message can be seen before it merges.
#
#   scripts/discord_test.sh [update folder]      default: the update the last recorded commit added
#   scripts/discord_test.sh --dry-run [folder]   print the messages, post nothing
#
# The webhook URL comes from $DISCORD_WEBHOOK_URL, else ~/.wowsims-discord-webhook (one line), and the
# emoji markers from $DISCORD_MARKS, else ~/.wowsims-discord-marks, as the DISCORD_MARKS variable holds.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
dry=false
if [ "${1:-}" = "--dry-run" ]; then
    dry=true
    shift
fi
# The update the last recorded commit added.
folder=${1:-$(dirname "$(git -C "$repo" log -1 --name-only --format= -- 'patches/*/*/CHANGES.md' | head -1)")}
folder=${folder%/}
test -f "$repo/$folder/CHANGES.md" || { echo "no CHANGES.md in $repo/$folder" >&2; exit 1; }

if [ -z "${DISCORD_MARKS:-}" ] && [ -f ~/.wowsims-discord-marks ]; then
    export DISCORD_MARKS=$(head -1 ~/.wowsims-discord-marks)
fi
title=$(head -1 "$repo/$folder/CHANGES.md" | sed 's/^# //')
out=$(mktemp -d)
python3 -I "$repo/scripts/discord_message.py" "$repo/$folder" "$title (test)" \
    "https://github.com/wowsims/gamedata/pulls" \
    "https://github.com/wowsims/gamedata/blob/main/$folder/CHANGES.md" "$out"

if $dry; then
    for message in $(ls "$out" | sort -n); do
        echo "=== message $message"
        python3 -I -c 'import json, sys; [print(e["description"], "\n---") for e in json.load(open(sys.argv[1]))["embeds"]]' "$out/$message"
    done
    exit 0
fi

url=${DISCORD_WEBHOOK_URL:-}
if [ -z "$url" ] && [ -f ~/.wowsims-discord-webhook ]; then
    url=$(head -1 ~/.wowsims-discord-webhook)
fi
test -n "$url" || { echo "set DISCORD_WEBHOOK_URL or write the URL to ~/.wowsims-discord-webhook" >&2; exit 1; }

for message in $(ls "$out" | sort -n); do
    curl -fsS -H 'Content-Type: application/json' --data-binary @"$out/$message" "$url"
    echo "posted message $message"
    sleep 1
done
