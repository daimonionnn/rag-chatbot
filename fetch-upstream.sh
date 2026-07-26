#!/usr/bin/env bash
# Clone the four upstream repositories this project adapts, pinned to the exact
# commits everything here — the patches, the numbers in EVALUATION.md, the line
# references in BUGS.md — was verified against.
#
# Nothing inside these clones is modified (see README.md "Layout"); they stay
# gitignored and unpinned-by-git-itself on purpose, so this script is the single
# source of truth for "which upstream state does this repo assume". Re-running it
# is a no-op if a clone already exists at the pinned commit.
#
# Usage: ./fetch-upstream.sh
set -euo pipefail
cd "$(dirname "$0")"

clone_at() {
    local dir="$1" url="$2" sha="$3"
    if [ -d "$dir/.git" ]; then
        local current
        current=$(git -C "$dir" rev-parse HEAD)
        if [ "$current" = "$sha" ]; then
            echo "OK      $dir already at $sha"
            return
        fi
        echo "UPDATE  $dir: $current -> $sha"
        # A pinned commit is rarely a branch tip, and GitHub's smart-HTTP only
        # allows `fetch <sha>` for reachable-SHA1-in-want on tips of a shallow
        # clone — fetching an arbitrary older commit fails with "couldn't find
        # remote ref" unless the clone has full history first.
        if git -C "$dir" rev-parse --is-shallow-repository | grep -q true; then
            git -C "$dir" fetch --quiet --unshallow
        fi
        git -C "$dir" fetch --quiet origin
        git -C "$dir" checkout --quiet "$sha"
        return
    fi
    echo "CLONE   $dir <- $url @ $sha"
    git clone --quiet "$url" "$dir"
    git -C "$dir" checkout --quiet "$sha"
}

# dir              url                                                              pinned commit (see README.md "Documentation" / BUGS.md for what was verified against it)
clone_at RAG              https://github.com/Sheryl-shiyi/RAG.git                         9394c39e2b58a072c16282c18610ad08f03bb1ae
clone_at nemo-guardrails  https://github.com/Sheryl-shiyi/Nemo-guardrial-deployment.git   72621f08a3699ed35319c336f002cc53964c37ba
clone_at ragas-poc        https://github.com/Sheryl-shiyi/proj-poc-RAGAS.git              af5c5af715785b73059eff1ceaab4fc39c4b389a
clone_at ragas-provider   https://github.com/Sheryl-shiyi/llama-stack-provider-ragas.git   d1a003ae3e7eedd5ccf127c487847cc091212aec

echo "done."
