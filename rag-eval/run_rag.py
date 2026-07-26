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
    .client06-venv/bin/python rag-eval/run_rag.py MODEL [LIMIT]

    MODEL   a model id from `client.models.list()`, e.g.
            ollama/gemma3:27b-it-fp16 · ollama/gemma4:31b-it-bf16 ·
            ollama/qwen3.6:27b-mtp-bf16 (prefix with nemo/ to go through
            the guardrails proxy instead)
    LIMIT   optional; evaluate only the first N questions (smoke tests)

Writes rag-eval/results/eval_data__<model>.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from llama_stack_client import LlamaStackClient

BASE_URL = "http://localhost:8321"
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


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    model = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    client = LlamaStackClient(base_url=BASE_URL, timeout=1800)
    store = next(v for v in client.vector_stores.list().data
                 if v.name == STORE_NAME)
    questions = json.loads(REFERENCE_DATA.read_text())
    if limit:
        questions = questions[:limit]

    print(f"model={model}  store={store.id}  questions={len(questions)}")
    rows, started, n_stripped = [], time.time(), 0
    for n, item in enumerate(questions, 1):
        q = item["user_input"]
        hits = client.vector_stores.search(
            vector_store_id=store.id, query=q, max_num_results=TOP_K)
        contexts = [d.content[0].text for d in hits.data if d.content]
        answer = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": "Kontext:\n" + "\n\n".join(contexts) +
                            f"\n\nOtázka: {q}"},
            ],
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

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    out = out_dir / f"eval_data__{slug}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\nwrote {out}  ({len(rows)} rows, "
          f"{(time.time() - started) / 60:.1f} min total)")
    if n_stripped:
        print(f"NOTE: stripped inline reasoning from {n_stripped}/{len(rows)} "
              f"answers (model emits thinking tokens)")


if __name__ == "__main__":
    main()
