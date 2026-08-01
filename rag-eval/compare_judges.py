#!/usr/bin/env python3
"""
Cross-judge comparison: does a model's score depend on who is judging?

EVALUATION-LIMITS.md §4.5: gemma3 judged every run in EVALUATION.md, including
its own answers, and it wins most decisively on `factual_correctness` — a
judge-scored metric. This script puts the same answers in front of a second
judge and reports what moved.

Two things make the comparison honest, and both are easy to get wrong:

- **Paired on rows, not on averages.** The stored runs cover 182 rows, the
  cross-judge run covers a 40-row subset. Comparing their means would blend the
  change of judge with the change of sample. So the stored per-row scores are
  sliced to exactly the subset's indices first.
- **Same population per metric.** Either judge can fail to score a row (the
  stored gemma3 run has 2 such rows on `faithfulness`, 1 on
  `factual_correctness`). A row missing from either side is dropped from both,
  which is the same rule §3.8 had to adopt for the thinking comparison.

What the numbers cannot separate: the second judge is reached over a different
endpoint (BUGS.md A4 — chat completions vs raw text completions), so "different
judge" and "different prompt framing" move together here. See EVALUATION.md.

Usage:
    python3 rag-eval/compare_judges.py [JUDGE_TAG]

    JUDGE_TAG   substring identifying the cross-judge score files,
                default "anthropic" — files are matched as
                scores__<dataset>__sub40__<stamp>.json, newest per model.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results"

# The three configurations ranked in EVALUATION.md §3.9, with the stored run that
# gemma3 judged. Thinking-enabled variants, matching §3.7's table.
MODELS = {
    "gemma3": ("eval_data__ollama_gemma3_27b-it-fp16",
               "scores__eval_data__ollama_gemma3_27b-it-fp16__20260725-215647.json"),
    "gemma4": ("eval_data__ollama_gemma4_31b-it-bf16",
               "scores__eval_data__ollama_gemma4_31b-it-bf16__20260726-043538.json"),
    "qwen3.6": ("eval_data__ollama_qwen3.6_27b-mtp-bf16",
                "scores__eval_data__ollama_qwen3.6_27b-mtp-bf16__20260726-105549.json"),
}
METRICS = ["faithfulness", "answer_relevancy", "context_precision",
           "context_recall", "answer_similarity", "factual_correctness"]


def usable(v) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))


def rows_of(path: Path, metric: str) -> list:
    scores = json.loads(path.read_text())["scores"]
    return [r.get("score") for r in scores[metric]["score_rows"]]


def newest_subset_scores(dataset: str) -> Path | None:
    cands = sorted(RESULTS.glob(f"scores__{dataset}__sub40__*.json"))
    return cands[-1] if cands else None


def main() -> None:
    idx_file = RESULTS / "subset40_indices.json"
    if not idx_file.is_file():
        sys.exit("missing subset40_indices.json — run make_subset.py first")
    idx = json.loads(idx_file.read_text())

    print(f"paired on {len(idx)} rows, the subset indices used by both judges\n")

    for model, (dataset, stored_name) in MODELS.items():
        stored = RESULTS / stored_name
        fresh = newest_subset_scores(dataset)
        if fresh is None:
            print(f"{model}: no cross-judge scores yet — skipped\n")
            continue

        print(f"=== {model} ===  cross-judge file: {fresh.name}")
        print(f"{'metric':22} {'gemma3 judge':>13} {'new judge':>11} "
              f"{'delta':>9} {'n':>4}")
        for metric in METRICS:
            old_all = rows_of(stored, metric)
            old = [old_all[i] for i in idx]
            new = rows_of(fresh, metric)
            if len(new) != len(idx):
                print(f"  {metric:20} row count {len(new)} != {len(idx)} — skipped")
                continue
            pairs = [(a, b) for a, b in zip(old, new) if usable(a) and usable(b)]
            if not pairs:
                print(f"  {metric:20} no rows scored by both — skipped")
                continue
            oa = sum(p[0] for p in pairs) / len(pairs)
            nb = sum(p[1] for p in pairs) / len(pairs)
            print(f"{metric:22} {oa:13.4f} {nb:11.4f} {nb - oa:+9.4f} {len(pairs):4}")
        print()


if __name__ == "__main__":
    main()
