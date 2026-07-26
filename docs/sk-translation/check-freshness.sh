#!/usr/bin/env bash
# Report which Slovak translations have fallen behind their English originals.
#
# Translations rot silently: the English doc gets a new finding, the translation
# keeps claiming the old one, and nothing complains. Each translation records the
# commit it was made from in its header, so that drift is checkable rather than
# invisible.
#
# Usage: docs/sk-translation/check-freshness.sh [-v]
#          -v  also print the diff of what changed in the original
set -uo pipefail
cd "$(dirname "$0")/../.."

VERBOSE=0
[ "${1:-}" = "-v" ] && VERBOSE=1

stale=0 ok=0 missing=0

for tr in docs/sk-translation/*.md; do
    base=$(basename "$tr")
    [ "$base" = "INDEX.md" ] && continue
    orig="$base"
    if [ ! -f "$orig" ]; then
        echo "?  $base — no English original at ./$orig"
        continue
    fi

    # Each translation carries a machine-readable marker on its first line:
    #   <!-- translated-from: <sha> -->
    # Parsed from that, not from the prose header — the prose wraps, and a
    # sha that wrapped onto the next line silently defeated a line-based grep.
    sha=$(grep -oE '<!-- translated-from: [0-9a-f]{7,40} -->' "$tr" | head -1 |
          grep -oE '[0-9a-f]{7,40}')
    if [ -z "$sha" ]; then
        echo "?  $base — translation records no source commit"
        missing=$((missing + 1))
        continue
    fi

    # Any commits touching the original since the recorded one?
    n=$(git log --oneline "$sha..HEAD" -- "$orig" | wc -l | tr -d ' ')
    if [ "$n" = "0" ]; then
        echo "OK $base — current with $sha"
        ok=$((ok + 1))
    else
        echo "!! $base — $n commit(s) behind (translated from $sha)"
        git log --oneline "$sha..HEAD" -- "$orig" | sed 's/^/     /'
        [ "$VERBOSE" = "1" ] && git diff "$sha..HEAD" -- "$orig" | sed 's/^/     /'
        stale=$((stale + 1))
    fi
done

echo ""
echo "current: $ok   stale: $stale   unknown: $missing"
[ "$stale" = "0" ] && [ "$missing" = "0" ]
