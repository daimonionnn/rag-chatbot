#!/usr/bin/env python3
"""
Runtime patch for the RAG UI's "Max Tokens" sampling-parameter sliders.

Two problems with the upstream chat slider, st.slider(label, min, max, value,
step) = (1, 4096, 512, 64):

1. Unreachable ceiling. Streamlit only yields values reachable by stepping from
   `min`, so the highest selectable value is 1 + 63*64 = 4033 — one step short
   of the labelled 4096, because 4097 would exceed it.

2. The cap covers reasoning, not just the answer. On the OpenAI-compatible path
   this stack uses, `max_tokens` limits reasoning + content *combined*. Measured
   on gemma4:31b-it-bf16 with max_tokens=200: reasoning consumed the whole
   budget, `content` came back as the empty string and finish_reason=length —
   i.e. the user sees a blank reply with no error. Uncapped, the same model
   spends 1686–2168 completion tokens per answer (~900 of them on reasoning),
   so a 512 default is well inside the range where thinking models get cut off,
   and 4096 leaves less headroom than it appears to.

Fixed to (0, 24576, 16384, 128). Every bound is a multiple of the step from 0, so
the ceiling is genuinely reachable, and both fit the context budget.

Sizing the ceiling matters more than it looks, because `max_tokens` does not get
its own budget — it shares OLLAMA_CONTEXT_LENGTH (32768 here) with the prompt,
and a RAG prompt is never small: ~434 tokens per retrieved chunk, so ~2.4k at the
default Top K=5. Measured against that budget:

    ceiling  8192  fits up to Top K = 50
    ceiling 16384  fits up to Top K = 30
    ceiling 24576  fits up to Top K = 15
    ceiling 32000  NEVER fits — 2372 + 32000 > 32768 even at Top K=5

A ceiling at or near 32768 would therefore be the original bug in a worse form:
selecting it makes Ollama silently truncate the prompt, dropping the retrieved
chunks so the model answers from parametric memory instead of the documents —
confidently, and with nothing in the UI saying so. 24576 keeps the slider honest
for realistic retrieval settings (Top K up to ~15) while leaving the default,
16384, safe up to Top K=30.

The Evaluations page has the same low 512 default and gets the same treatment
(it is not reachable in the UI — app.py registers only Chat, Upload Documents and
Inspect — but is patched for consistency).

Runs at container START (see compose-model-override.yml, which mounts this
script and wraps the rag-ui entrypoint to run it first), not at image build
time — so it applies without a rebuild, survives the upstream image being
rebuilt, and never touches the RAG/ clone itself (see README.md "Layout").
"""
from __future__ import annotations

import pathlib
import re
import sys

UI = pathlib.Path("/app/llama_stack_ui/distribution/ui")

# (file, old, new, required) — required=False for pages whose exact source
# varies more and whose sliders are not on the main chat path.
EDITS = [
    (
        UI / "page/playground/chat.py",
        '''    max_tokens = st.slider(
        "Max Tokens",
        1, 4096, 512, 64,''',
        '''    max_tokens = st.slider(
        "Max Tokens",
        0, 24576, 16384, 128,''',
        True,
    ),
    (
        UI / "page/evaluations/native_eval.py",
        'max_tokens = st.slider("Max Tokens", 0, 4096, 512, 1)',
        'max_tokens = st.slider("Max Tokens", 0, 24576, 16384, 128)',
        False,
    ),
]


def main() -> int:
    applied = skipped = 0
    for target, old, new, required in EDITS:
        if not target.is_file():
            print(f"patch: {target} not found", file=sys.stderr)
            if required:
                return 1
            continue
        src = target.read_text()
        if new in src:
            print(f"patch: already applied to {target.name}")
            skipped += 1
            continue
        if old not in src:
            print(f"patch: expected slider not found in {target.name} — "
                  "frontend changed, re-check the fix", file=sys.stderr)
            if required:
                return 1
            continue
        target.write_text(src.replace(old, new, 1))
        # Report the bounds from `new` itself — a hardcoded message here went
        # stale the first time the numbers were tuned, and logged values the
        # slider no longer had.
        bounds = re.search(r"(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", new)
        print(f"patch: {target.name}: Max Tokens now "
              f"{bounds.group(1)}-{bounds.group(2)}, "
              f"default {bounds.group(3)}, step {bounds.group(4)}"
              if bounds else f"patch: {target.name}: slider updated")
        applied += 1
    print(f"patch: {applied} applied, {skipped} already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
