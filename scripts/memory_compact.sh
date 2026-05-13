#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
compact_dir="$root/memory/compact/$(date -u +%Y)/$(date -u +%m)"
mkdir -p "$compact_dir"
out="$compact_dir/$(date -u +%Y%m%d-%H%M%S).md"
{
  echo "# Muno memory compaction $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  find "$root/memory/inbox" -type f -name '*.md' | sort | while read -r file; do
    rel="${file#$root/}"
    title="$(sed -n 's/^# //p' "$file" | head -1)"
    echo "## ${title:-$(basename "$file")}"; echo; echo "- Source: \`$rel\`"; sed '1{/^# /d;}' "$file" | head -20; echo
  done
} > "$out"
echo "$out"
