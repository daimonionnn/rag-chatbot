#!/usr/bin/env python3
"""
Let the inline TrustyAI RAGAS provider judge with models that have no
text-completions endpoint.

The provider asks the judge for text through the **legacy completions** API:

    request = OpenAICompletionRequestWithExtraBody(model=..., prompt=...)
    response = await self.inference_api.openai_completion(request)

Ollama serves both `/v1/completions` and `/v1/chat/completions`, so this is
invisible for the local judges. Anthropic serves only the latter — measured
against api.anthropic.com with a valid key:

    POST /v1/completions        -> 404
    POST /v1/chat/completions   -> 200

so every judge call failed with `Error code: 404 - not_found_error` and the whole
evaluation produced no scores. The 404 is easy to misread as a bad model id (a
wrong model name returns 404 too, with the model in the message) — it is the
endpoint that is missing, not the model.

Fix: for judges whose provider cannot do text completions, translate the request
to a single-user-message chat completion and read the text back out of
`choice.message.content` instead of `choice.text`.

**The translation is deliberately limited to those providers.** Text and chat
completions differ in more than transport: chat applies the model's chat
template, so the judge sees a differently framed prompt and may score
differently. Routing the existing local judges through the new path would
silently invalidate every score already recorded in EVALUATION.md, so `ollama/*`
keeps the byte-identical path it had. The consequence — that the hosted judge is
prompted through chat while the local ones were prompted through raw completion —
is a caveat of the cross-judge comparison, not something this patch can remove:
there is no endpoint on which both kinds of judge can be prompted identically.

Idempotent; exits non-zero if the expected source is missing so a provider
upgrade cannot silently drop the patch.
"""
from __future__ import annotations

import pathlib
import sys
from importlib.util import find_spec

OLD_CALL = "                response = await self.inference_api.openai_completion(request)"
NEW_CALL = "                response = await _ls_generate(self.inference_api, request)"

OLD_TEXT = '                text = choice.text if choice else ""'
NEW_TEXT = "                text = _ls_choice_text(choice)"

HELPER = '''

# --- patched in: chat-completions fallback for judges without /v1/completions --

# Providers whose backend serves only /v1/chat/completions. Anthropic is the
# reason this exists (EVALUATION-LIMITS.md §4.5 needs a judge that is not one of
# the models under test); anything not listed here keeps the original path.
_LS_CHAT_ONLY_PREFIXES = ("anthropic/",)


def _ls_needs_chat(model_id: str) -> bool:
    return str(model_id).startswith(_LS_CHAT_ONLY_PREFIXES)


async def _ls_generate(inference_api, request):
    """Run `request` on whichever completions endpoint the provider serves."""
    if not _ls_needs_chat(request.model):
        return await inference_api.openai_completion(request)

    from llama_stack_api import OpenAIChatCompletionRequestWithExtraBody

    # Only the fields the provider actually sets are carried over. `temperature`
    # is passed through as-is including None: Claude Opus 5 rejects a non-default
    # temperature outright, so score_ragas.py omits it for this judge and the
    # value arriving here is None, which the request model drops.
    chat = OpenAIChatCompletionRequestWithExtraBody(
        model=request.model,
        messages=[{"role": "user", "content": request.prompt}],
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        stop=request.stop,
    )
    return await inference_api.openai_chat_completion(chat)


def _ls_choice_text(choice) -> str:
    """Text of a choice from either endpoint (`.text` vs `.message.content`)."""
    if choice is None:
        return ""
    text = getattr(choice, "text", None)
    if text is not None:
        return text
    message = getattr(choice, "message", None)
    return (getattr(message, "content", None) or "") if message is not None else ""

'''

MARKER = "_LS_CHAT_ONLY_PREFIXES"


def main() -> None:
    spec = find_spec("llama_stack_provider_ragas")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("patch: llama_stack_provider_ragas is not installed")
    path = pathlib.Path(next(iter(spec.submodule_search_locations))) / "inline" / "wrappers_inline.py"
    if not path.is_file():
        sys.exit(f"patch: {path} not found")

    src = path.read_text()
    if MARKER in src:
        print(f"patch: chat-completions fallback already present in {path}")
        return

    for needle in (OLD_CALL, OLD_TEXT):
        if needle not in src:
            sys.exit(f"patch: expected source not found in {path}:\n{needle}")

    src = src.replace(OLD_CALL, NEW_CALL).replace(OLD_TEXT, NEW_TEXT)

    # Insert the helpers above the first class so they are defined at import time
    # regardless of which class ends up calling them.
    anchor = "\nclass LlamaStackInlineEmbeddings"
    if anchor not in src:
        sys.exit(f"patch: anchor class not found in {path}")
    src = src.replace(anchor, HELPER + anchor, 1)

    path.write_text(src)
    print(f"patch: applied RAGAS chat-completions fallback to {path}")


if __name__ == "__main__":
    main()
