#!/usr/bin/env python3
"""
Fix "This event loop is already running" in the inline TrustyAI RAGAS provider.

The provider drives ragas' synchronous `evaluate()` from a worker thread
(`asyncio.to_thread`), but its embeddings wrapper bridges sync->async like this
(upstream even flags it with a TODO):

    def embed_query(self, text):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.aembed_query(text))

From that worker thread `get_event_loop()` hands back the server's loop, which is
already running, so `run_until_complete` raises and the whole evaluation job
fails. Only metrics that need embeddings are affected — `faithfulness` (LLM only)
completes fine, while `answer_relevancy`, `answer_similarity` etc. kill the job.
The LLM wrapper is unaffected because its sync `generate_text` raises
NotImplementedError, so ragas always takes the async path there.

Fix: capture the server's loop when the wrapper is constructed (which happens on
the loop) and submit coroutines to it with `run_coroutine_threadsafe`, the
correct primitive for calling into a loop from another thread.

Idempotent; exits non-zero if the expected source is missing so a provider
upgrade cannot silently drop the patch.
"""
from __future__ import annotations

import pathlib
import sys
from importlib.util import find_spec

OLD_INIT = "        self.set_run_config(run_config)"
NEW_INIT = """        self.set_run_config(run_config)
        # Patched: remember the server's event loop so the sync embed_* methods
        # can hand coroutines to it from ragas' worker thread.
        try:
            self._ls_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._ls_loop = None"""

OLD_METHODS = '''    def embed_query(self, text: str) -> list[float]:
        """Embed query using asyncio.get_event_loop() to call async version."""
        # TODO: propose a way to configure BaseRagasEmbeddings to use sync or async
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.aembed_query(text))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents using asyncio.get_event_loop() to call async version."""
        # TODO: propose a way to configure BaseRagasEmbeddings to use sync or async
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.aembed_documents(texts))'''

NEW_METHODS = '''    def _ls_run_sync(self, coro):
        """Patched bridge from ragas' sync calls to our async embedding API.

        Upstream called loop.run_until_complete() on an already-running loop,
        which raises "This event loop is already running". ragas runs in a
        worker thread, so the coroutine must be submitted to the server's loop.
        """
        loop = getattr(self, "_ls_loop", None)
        if loop is not None and loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
        return asyncio.run(coro)

    def embed_query(self, text: str) -> list[float]:
        return self._ls_run_sync(self.aembed_query(text))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._ls_run_sync(self.aembed_documents(texts))'''


def main() -> int:
    spec = find_spec("llama_stack_provider_ragas")
    if spec is None or spec.origin is None:
        print("patch: llama_stack_provider_ragas not importable", file=sys.stderr)
        return 1
    target = (pathlib.Path(spec.origin).parent
              / "inline" / "wrappers_inline.py")
    if not target.is_file():
        print(f"patch: {target} not found", file=sys.stderr)
        return 1

    src = target.read_text()
    if "_ls_run_sync" in src:
        print(f"patch: already applied to {target}")
        return 0
    for needle, what in ((OLD_INIT, "set_run_config call"),
                         (OLD_METHODS, "embed_query/embed_documents")):
        if needle not in src:
            print(f"patch: expected {what} not found — provider changed, "
                  "re-check the fix", file=sys.stderr)
            return 1

    src = src.replace(OLD_METHODS, NEW_METHODS, 1)
    src = src.replace(OLD_INIT, NEW_INIT, 1)
    target.write_text(src)
    print(f"patch: applied RAGAS embeddings event-loop fix to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
