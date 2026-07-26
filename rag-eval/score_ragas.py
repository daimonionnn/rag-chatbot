#!/usr/bin/env python3
"""
Step 2 of the RAGAS evaluation: score the RAG outputs via the llama-stack
TrustyAI RAGAS provider (inline).

Mirrors `ragas_eval_*_metrics.ipynb` from proj-poc-RAGAS, but instead of calling
ragas directly it goes through llama-stack's eval API, which is what the
provider exists for: register the rows as a dataset, register a benchmark with
the metrics, then run it with a judge model.

The embedding model used by the similarity-based metrics is NOT settable per
benchmark — it comes from EMBEDDING_MODEL in the server config
(ollama/qwen3-embedding:4b-fp16 here, matching the upstream PoC).

Usage:
    .client06-venv/bin/python rag-eval/score_ragas.py EVAL_DATA_JSON [JUDGE] [LIMIT]

    JUDGE   judge model, default ollama/gemma3:27b-it-fp16 (the PoC's choice)
    LIMIT   optional; score only the first N rows
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from llama_stack_client import LlamaStackClient

BASE_URL = "http://localhost:8321"
PROVIDER_ID = "trustyai_ragas_inline"
DEFAULT_JUDGE = "ollama/gemma3:27b-it-fp16"
# The upstream PoC's six metrics. `answer_correctness` no longer exists in
# ragas 0.4.x — `factual_correctness` is its successor, and it needs the
# ModeMetric key fix patched into the provider (see BUGS.md) or the job dies
# with KeyError. Override with METRICS=a,b,c to run a subset.
DEFAULT_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_similarity",
    "factual_correctness",
]
METRICS = [m.strip() for m in os.environ["METRICS"].split(",")] \
    if os.environ.get("METRICS") else DEFAULT_METRICS


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    data_path = Path(sys.argv[1])
    judge = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_JUDGE
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    rows = json.loads(data_path.read_text())
    if limit:
        rows = rows[:limit]
    client = LlamaStackClient(base_url=BASE_URL, timeout=7200)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", data_path.stem)
    dataset_id = f"ds__{slug}__{stamp}"
    benchmark_id = f"bm__{slug}__{stamp}"

    print(f"rows={len(rows)}  judge={judge}")
    client.beta.datasets.register(
        dataset_id=dataset_id,
        purpose="eval/question-answer",
        source={"type": "rows", "rows": rows},
        # provider_id in metadata: the provider's own demo notes the datasets
        # API does not route on it correctly without this.
        metadata={"provider_id": "localfs", "size": len(rows),
                  "format": "ragas"},
    )
    client.alpha.benchmarks.register(
        benchmark_id=benchmark_id,
        dataset_id=dataset_id,
        scoring_functions=METRICS,
        provider_id=PROVIDER_ID,
    )

    started = time.time()
    job = client.alpha.eval.run_eval(
        benchmark_id=benchmark_id,
        benchmark_config={
            "eval_candidate": {
                "type": "model",
                "model": judge,
                # max_tokens must be generous: ragas asks the judge for JSON
                # (faithfulness sends one object per extracted statement), and at
                # 1024 the reply was truncated mid-string, so ragas' parser
                # failed and took the whole job down.
                "sampling_params": {"temperature": 0.0, "max_tokens": 4096},
            },
            "scoring_params": {},
        },
    )
    print(f"job: {job}")

    # run_eval may be async (returns a job); poll until it finishes.
    final_state = "completed"
    job_id = getattr(job, "job_id", None)
    if job_id:
        while True:
            st = client.alpha.eval.jobs.status(
                benchmark_id=benchmark_id, job_id=job_id)
            state = str(getattr(st, "status", st)).lower()
            print(f"  [{time.time()-started:6.0f}s] {state}")
            if state in ("completed", "failed", "cancelled"):
                final_state = state
                break
            time.sleep(15)
        result = client.alpha.eval.jobs.retrieve(
            benchmark_id=benchmark_id, job_id=job_id)
    else:
        result = job

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"scores__{slug}__{stamp}.json"
    payload = result.to_dict() if hasattr(result, "to_dict") else str(result)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nwrote {out}  ({(time.time()-started)/60:.1f} min)")

    # Report the truth: a failed job still returns a well-formed but EMPTY
    # payload, so without this check the caller happily logs success and a whole
    # multi-model benchmark can "finish" with no scores at all.
    scored = payload.get("scores") if isinstance(payload, dict) else None
    if final_state != "completed" or not scored:
        print(f"FAILED: job state={final_state}, metrics returned="
              f"{len(scored or {})} — see the llamastack log for the cause")
        sys.exit(1)
    print(f"OK: {len(scored)} metrics")
    for name, res in scored.items():
        agg = res.get("aggregated_results", {}) if isinstance(res, dict) else {}
        val = next(iter(agg.values()), None) if agg else None
        print(f"  {name:22} {val}")


if __name__ == "__main__":
    main()
