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
# Five of the upstream PoC's six metrics. Two naming/compat notes:
#  * `answer_correctness` does not exist in ragas 0.4.x; its successor is
#    `factual_correctness`, but that one CANNOT be used here — ragas names its
#    result column with the mode appended (e.g. "factual_correctness(mode=f1)")
#    while the provider looks the column up by the bare metric name, so the job
#    dies with KeyError: 'factual_correctness'.
#  * everything else below is verified working.
# Override with METRICS=a,b,c to run a subset.
DEFAULT_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_similarity",
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
                "sampling_params": {"temperature": 0.0, "max_tokens": 1024},
            },
            "scoring_params": {},
        },
    )
    print(f"job: {job}")

    # run_eval may be async (returns a job); poll until it finishes.
    job_id = getattr(job, "job_id", None)
    if job_id:
        while True:
            st = client.alpha.eval.jobs.status(
                benchmark_id=benchmark_id, job_id=job_id)
            state = getattr(st, "status", st)
            print(f"  [{time.time()-started:6.0f}s] {state}")
            if str(state).lower() in ("completed", "failed", "cancelled"):
                break
            time.sleep(15)
        result = client.alpha.eval.jobs.retrieve(
            benchmark_id=benchmark_id, job_id=job_id)
    else:
        result = job

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"scores__{slug}__{stamp}.json"
    out.write_text(json.dumps(
        result.to_dict() if hasattr(result, "to_dict") else str(result),
        ensure_ascii=False, indent=2))
    print(f"\nwrote {out}  ({(time.time()-started)/60:.1f} min)")


if __name__ == "__main__":
    main()
