#!/usr/bin/env python3
"""
Runtime patch for RAG UI chat behavior and token sliders.

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

Also preserves chat history while changing sidebar settings (model, processing
mode, sampling params, system prompt). Upstream wires eight sidebar widgets to a
session-clearing callback — seven to `on_change=reset_agent`, plus the MCP
selector to `on_reset` — and `reset_agent` is `st.session_state.clear()`, so
touching any one of them wipes the conversation and opens a fresh server-side one.

Dropping those callbacks is safe here because nothing in the page depends on
them: `ChatConfig` is rebuilt from the widgets on *every* rerun (model, sampling
params, prompt and all), and no function in chat.py is decorated with
`@st.cache_resource`, so the `st.cache_resource.clear()` half of the reset has
nothing to clear either. Upstream already treats a full reset as unnecessary for
the guardrail selectors, which use the narrower `reset_conversation()` instead.
`Clear Chat & Reset Config` still calls `reset_agent()`, so the explicit way to
start over is untouched.

The Evaluations page has the same low 512 default and gets the same treatment
(it is not reachable in the UI — app.py registers only Chat, Upload Documents
and Inspect — but is patched for consistency).

Runs at container START (see compose-model-override.yml, which mounts this
script and wraps the rag-ui entrypoint to run it first), not at image build
time — so it applies without a rebuild, survives the upstream image being
rebuilt, and never touches the RAG/ clone itself (see README.md "Layout").
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

UI = pathlib.Path("/app/llama_stack_ui/distribution/ui")


RESET_CALLBACK_FILE = UI / "page/playground/chat.py"

# The session-wiping callbacks, in the two shapes upstream writes them: on their
# own line among other kwargs, and inline alongside them (only the System Prompt
# text_area). The two cases cannot share one pattern, because deleting the bare
# text ", on_change=reset_agent," from
#     "System Prompt", value=default_prompt, on_change=reset_agent, height=100
# consumes *both* commas and leaves `value=default_prompt height=100` — a
# SyntaxError that stops the Chat page importing at all. So: own-line matches
# take the whole line, inline matches keep the comma that separates the kwargs.
# Ordered alternation, so the own-line branch is tried first.
RESET_CALLBACK = re.compile(
    r"^[ \t]*on_change=(?:reset_agent|on_reset),[ \t]*\n"
    r"|[ \t]*on_change=(?:reset_agent|on_reset),",
    re.MULTILINE,
)

# `on_reset` is left as an accepted-but-unused parameter of
# render_toolgroup_selection rather than removed from both its signature and its
# call site: two edits that must land together, on a page where a half-applied
# pair would call it with one argument too many and break Agent-based mode.
# An unused parameter costs nothing and keeps the diff against upstream smaller.

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


def strip_reset_callbacks() -> tuple[int, str | None]:
    """Strip the session-clearing callbacks.

    Returns (count removed, error) — error is None on success. Re-running is a
    no-op: the container is patched in place, so a restart runs this again.
    """
    target = RESET_CALLBACK_FILE
    if not target.is_file():
        return 0, f"{target} not found"

    src = target.read_text()
    patched, removed = RESET_CALLBACK.subn("", src)

    # Editing Python with a regex earns a syntax check before the write: a bad
    # substitution here does not degrade the page, it stops chat.py importing.
    try:
        ast.parse(patched)
    except SyntaxError as exc:
        return 0, f"{target.name} would not parse after the edit ({exc.msg}, " \
                  f"line {exc.lineno}) — left untouched"

    # The invariant that actually matters, and it holds on a re-run too, where
    # nothing is left to remove.
    for leftover in ("on_change=reset_agent", "on_change=on_reset"):
        if leftover in patched:
            return 0, f"{leftover} still present in {target.name} — " \
                      "pattern no longer matches, re-check the fix"

    if removed:
        target.write_text(patched)
    return removed, None


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
            print(f"patch: expected pattern not found in {target.name} — "
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
              if bounds else f"patch: {target.name}: updated")
        applied += 1

    # Hard failure, like the required slider edit above: the container not
    # starting is a message that gets read, whereas a warning buried in the
    # startup log is how the reset-on-every-setting-change bug comes back
    # unnoticed.
    removed, error = strip_reset_callbacks()
    if error:
        print(f"patch: {error}", file=sys.stderr)
        return 1

    print(f"patch: {applied} applied, {skipped} already current, "
          f"{removed} reset-on-change callbacks removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
