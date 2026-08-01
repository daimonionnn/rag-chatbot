#!/usr/bin/env python3
"""
Make the RAGAS per-call timeout configurable, for judges that think.

The inline provider builds ragas' RunConfig with only the worker count set
(`ragas_inline_eval.py`):

    ragas_run_config = RunConfig(max_workers=1)

so `timeout` keeps ragas' default of 180 s per LLM call. That is ample for a
non-thinking judge — gemma3 and claude-opus-5 both average ~16 s per
(row, metric) — but a thinking judge generates reasoning on **every** call, and
qwen3.6 measured ~77 s per (row, metric) with individual calls exceeding the
limit. When one does, ragas' executor abandons the job:

    ERROR ragas.executor: Exception raised in Job[11]: TimeoutError()

and because the provider is deliberately configured with
`raise_exceptions: false` (so one bad row cannot kill a multi-hour run), the row
becomes NaN **silently**. In a 2-row smoke test that was half of
`factual_correctness` — the one metric the cross-judge comparison exists to
settle. The damage is not a visible failure but a quietly shrinking `n`.

The timeout is not reachable through the provider's `ragas_config`, which exposes
only batch_size / show_progress / raise_exceptions / experiment_name /
column_map. This patch reads it from the environment instead:

    RAGAS_TIMEOUT=900   # seconds per LLM call

**Unset means ragas' own default**, so existing runs are bit-for-bit unaffected
and only a slow judge needs the override. Idempotent; exits non-zero if the
expected source is missing so a provider upgrade cannot silently drop the patch.
"""
from __future__ import annotations

import pathlib
import sys
from importlib.util import find_spec

OLD = "        ragas_run_config = RunConfig(max_workers=1)"
NEW = """        # Patched: RAGAS defaults to a 180 s per-call timeout, which a thinking
        # judge exceeds — and `raise_exceptions: false` turns the resulting
        # TimeoutError into a silent NaN row. Unset keeps ragas' own default.
        _ls_timeout = os.environ.get("RAGAS_TIMEOUT")
        ragas_run_config = (
            RunConfig(max_workers=1, timeout=int(_ls_timeout))
            if _ls_timeout
            else RunConfig(max_workers=1)
        )"""

MARKER = "_ls_timeout"


def main() -> None:
    spec = find_spec("llama_stack_provider_ragas")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("patch: llama_stack_provider_ragas is not installed")
    path = (pathlib.Path(next(iter(spec.submodule_search_locations)))
            / "inline" / "ragas_inline_eval.py")
    if not path.is_file():
        sys.exit(f"patch: {path} not found")

    src = path.read_text()
    if MARKER in src:
        print(f"patch: RAGAS timeout override already present in {path}")
        return
    if OLD not in src:
        sys.exit(f"patch: expected source not found in {path}:\n{OLD}")

    src = src.replace(OLD, NEW, 1)
    if "\nimport os\n" not in src:
        # Insert next to the existing stdlib imports rather than at the top, so
        # the module's own import ordering is preserved.
        src = src.replace("from ragas.run_config import RunConfig",
                          "import os\n\nfrom ragas.run_config import RunConfig", 1)

    path.write_text(src)
    print(f"patch: applied RAGAS timeout override to {path}")


if __name__ == "__main__":
    main()
