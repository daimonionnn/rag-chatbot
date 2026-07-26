#!/usr/bin/env python3
"""
Step 1 of the RAGAS evaluation: run the eval questions through our RAG stack.

Mirrors `query_rag_system.ipynb` from proj-poc-RAGAS. For each question it
retrieves from the vector store and generates an answer with the model under
test, producing the four fields RAGAS expects:

    user_input, response, retrieved_contexts, reference

`reference` (ground truth) is taken from the upstream PoC's dataset so our
numbers stay comparable to theirs.

Usage:
    .client06-venv/bin/python rag-eval/run_rag.py MODEL [LIMIT] [--no-think]

    MODEL   a model id from `client.models.list()`, e.g.
            ollama/gemma3:27b-it-fp16 · ollama/gemma4:31b-it-bf16 ·
            ollama/qwen3.6:27b-mtp-bf16 (prefix with nemo/ to go through
            the guardrails proxy instead)
    LIMIT   optional; evaluate only the first N questions (smoke tests)

    --no-think  ask the model not to emit reasoning, to measure what thinking
        is worth. Ollama honours `think: false` only on its own /api/chat
        endpoint — it is accepted and **silently ignored** on the
        OpenAI-compatible /v1/chat/completions path that llama-stack (and this
        script's default) uses, so this flag routes generation straight to
        Ollama. Retrieval still goes through llama-stack; in fact the contexts
        from the corresponding thinking-enabled run are reused verbatim when
        that file exists, so the answer is the only thing that differs and the
        two runs are directly comparable. Writes a separate `__nothink` file so
        the baseline is never overwritten. Rejected for nemo/ models, whose
        whole point is the guardrails proxy.

Writes rag-eval/results/eval_data__<model>[__nothink].json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx
from llama_stack_client import LlamaStackClient

BASE_URL = "http://localhost:8321"
OLLAMA_URL = "http://localhost:11434"
STORE_NAME = "vszp"
TOP_K = 5
HERE = Path(__file__).parent
# Ground truth + question list from the upstream PoC (182 Slovak QA pairs).
REFERENCE_DATA = (HERE.parent / "ragas-poc" /
                  "experiment1-Gemma-3-27B-bf16-distributed" /
                  "eval_data_health_wallet.json")

SYSTEM_PROMPT = (
    "Si asistent Všeobecnej zdravotnej poisťovne pre produkty Peňaženka zdravia "
    "a Program Vernosť+. Odpovedaj výhradne na základe poskytnutého kontextu, "
    "vecne a po slovensky. Ak odpoveď v kontexte nie je, povedz to."
)

# gemma4 and qwen3.6 advertise a `thinking` capability; gemma3 does not. If a
# model emits its reasoning inline, that text would be scored as if it were the
# answer, penalising the thinking models for something that is not a quality
# difference. Strip the usual wrappers and say so in the log, so the comparison
# stays about the answers.
THINK_BLOCK = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*?</\1>", re.S | re.I)
THINK_OPEN = re.compile(r"^\s*<(think|thinking|reasoning)\b[^>]*>.*", re.S | re.I)


def strip_reasoning(text: str) -> tuple[str, bool]:
    """Return (answer, stripped?) with any inline reasoning block removed.

    Never returns empty: if stripping would leave nothing (an unclosed block,
    i.e. the reply was reasoning all the way to the end) the original text is
    kept and `stripped` is False, so the log does not claim a clean-up that
    did not happen.
    """
    original = text.strip()
    cleaned = THINK_BLOCK.sub("", text)
    if THINK_OPEN.match(cleaned):
        cleaned = ""
    answer = cleaned.strip() or original
    return answer, answer != original


def generate_no_think(model: str, messages: list[dict]) -> tuple[str, int]:
    """Generate via Ollama's native /api/chat with reasoning turned off.

    Returns (content, thinking_chars). `think: false` is a request, not a
    guarantee — some models still emit some reasoning, so the caller reports how
    much came back rather than assuming none did. Ollama puts it in its own
    `thinking` field here, separate from `content`, which is also why the
    inline-stripping below is not needed on this path.
    """
    # Strip the llama-stack provider prefix: Ollama knows `gemma4:31b-it-bf16`,
    # not `ollama/gemma4:31b-it-bf16`.
    r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=1800.0, json={
        "model": model.split("/", 1)[-1],
        "messages": messages,
        "think": False,
        "stream": False,
    })
    r.raise_for_status()
    msg = r.json().get("message", {})
    return (msg.get("content") or ""), len(msg.get("thinking") or "")


def main() -> None:
    argv = [a for a in sys.argv[1:] if a != "--no-think"]
    no_think = "--no-think" in sys.argv
    if not argv:
        print(__doc__)
        sys.exit(1)
    model = argv[0]
    limit = int(argv[1]) if len(argv) > 1 else None

    if no_think and model.startswith("nemo/"):
        print("--no-think goes straight to Ollama, bypassing the guardrails "
              "proxy that a nemo/ model exists to exercise. Use the ollama/ id.",
              file=sys.stderr)
        sys.exit(1)

    client = LlamaStackClient(base_url=BASE_URL, timeout=1800)
    store = next(v for v in client.vector_stores.list().data
                 if v.name == STORE_NAME)
    questions = json.loads(REFERENCE_DATA.read_text())
    if limit:
        questions = questions[:limit]

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    out = out_dir / f"eval_data__{slug}{'__nothink' if no_think else ''}.json"

    # Reuse the thinking-enabled run's contexts so thinking is the only variable.
    # Keyed by question rather than by position, so a mismatched or reordered
    # baseline degrades to fresh retrieval for the rows it cannot supply instead
    # of silently pairing an answer with the wrong context.
    reuse: dict[str, list[str]] = {}
    if no_think:
        baseline = out_dir / f"eval_data__{slug}.json"
        if baseline.is_file():
            reuse = {r["user_input"]: r["retrieved_contexts"]
                     for r in json.loads(baseline.read_text())}
            print(f"reusing contexts from {baseline.name} ({len(reuse)} rows)")
        else:
            print(f"no baseline at {baseline.name} — retrieving fresh")

    print(f"model={model}  store={store.id}  questions={len(questions)}  "
          f"think={'off' if no_think else 'on'}")
    rows, started, n_stripped = [], time.time(), 0
    n_reused, thinking_chars = 0, 0
    for n, item in enumerate(questions, 1):
        q = item["user_input"]
        contexts = reuse.get(q)
        if contexts is None:
            hits = client.vector_stores.search(
                vector_store_id=store.id, query=q, max_num_results=TOP_K)
            contexts = [d.content[0].text for d in hits.data if d.content]
        else:
            n_reused += 1
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": "Kontext:\n" + "\n\n".join(contexts) +
                        f"\n\nOtázka: {q}"},
        ]
        if no_think:
            answer, n_thinking = generate_no_think(model, messages)
            thinking_chars += n_thinking
            stripped = False
        else:
            answer = client.chat.completions.create(
                model=model, messages=messages,
            ).choices[0].message.content or ""
            answer, stripped = strip_reasoning(answer)
        if stripped:
            n_stripped += 1
        rows.append({
            "user_input": q,
            "response": answer,
            "retrieved_contexts": contexts,
            "reference": item["reference"],
        })
        rate = (time.time() - started) / n
        print(f"  [{n}/{len(questions)}] {rate:5.1f}s/q  {q[:60]}")

    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\nwrote {out}  ({len(rows)} rows, "
          f"{(time.time() - started) / 60:.1f} min total)")
    if n_stripped:
        print(f"NOTE: stripped inline reasoning from {n_stripped}/{len(rows)} "
              f"answers (model emits thinking tokens)")
    if no_think:
        print(f"NOTE: contexts reused for {n_reused}/{len(rows)} rows")
        # `think: false` is a request. Report what actually came back, so a model
        # that ignores it cannot be mistaken for one that complied.
        print(f"NOTE: reasoning returned despite think=false: "
              f"{thinking_chars} chars total"
              + (" (fully disabled)" if thinking_chars == 0 else " — NOT fully disabled"))


if __name__ == "__main__":
    main()
