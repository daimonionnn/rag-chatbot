#!/usr/bin/env python3
"""
Runtime patch for the RAG UI's "Max Tokens" sampling-parameter slider.

Streamlit's st.slider(label, min_value, max_value, value, step) only produces
values reachable by stepping from min_value. With the upstream defaults
(1, 4096, 512, 64), the highest reachable value is 4033 (1 + 63*64) — one step
short of the labelled 4096 ceiling, since the next step (4097) would exceed it.
512 is also a low default for a chatbot answering from retrieved context.

Fixed to (0, 8192, 4096, 64): 8192 is itself a multiple of 64 starting from 0,
so the slider's maximum is actually reachable, and the default sits in the
middle of the new range.

Runs at container START (see compose-model-override.yml, which mounts this
script and wraps the rag-ui entrypoint to run it first), not at image build
time — so it applies without a rebuild, survives the upstream image being
rebuilt, and never touches the RAG/ clone itself (see README.md "Layout").
"""
from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(
    "/app/llama_stack_ui/distribution/ui/page/playground/chat.py"
)
OLD = '''    max_tokens = st.slider(
        "Max Tokens",
        1, 4096, 512, 64,'''
NEW = '''    max_tokens = st.slider(
        "Max Tokens",
        0, 8192, 4096, 64,'''


def main() -> int:
    if not TARGET.is_file():
        print(f"patch: {TARGET} not found", file=sys.stderr)
        return 1
    src = TARGET.read_text()
    if NEW in src:
        print(f"patch: already applied to {TARGET}")
        return 0
    if OLD not in src:
        print("patch: expected Max Tokens slider not found — "
              "frontend changed, re-check the fix", file=sys.stderr)
        return 1
    TARGET.write_text(src.replace(OLD, NEW, 1))
    print(f"patch: Max Tokens slider is now 0-8192, default 4096, in {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
