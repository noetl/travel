#!/usr/bin/env bash
set -euo pipefail
kind="claude"
if [[ "${1:-}" == --kind=* ]]; then kind="${1#--kind=}"; shift; fi
if [[ "$kind" != "claude" && "$kind" != "codex" ]]; then echo "--kind must be claude or codex" >&2; exit 2; fi
if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then echo "Usage: $0 [--kind=claude|codex] <title> <summary> [tags] [author]" >&2; exit 1; fi
title="$1"; summary="$2"; tags="${3:-none}"; author="${4:-$(git config user.name 2>/dev/null || echo unknown)}"
root="$(git rev-parse --show-toplevel)"
ts_iso="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"; year="$(date -u +"%Y")"; month="$(date -u +"%m")"; stamp="$(date -u +"%Y%m%d-%H%M%S")"
slug="$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-60)"; [[ -z "$slug" ]] && slug=entry
dir="$root/memory/inbox/$kind/$year/$month"; mkdir -p "$dir"; file="$dir/${stamp}-${slug}.md"
cat > "$file" <<EOF
# $title
- Timestamp: $ts_iso
- Author: $author
- Tags: $tags
- Kind: $kind

## Summary
$summary

## Actions
-

## Related
-
EOF
echo "$file"
