#!/usr/bin/env python3
"""
Build the stratified 40-row subset used for cross-judging (EVALUATION-LIMITS §4.5).

Scoring one model with one judge costs ~5 h locally and real money via a hosted
judge, so the cross-judge matrix runs on a subset. The subset is NOT a random 40
rows: EVALUATION-LIMITS §4.10.2 found that the 46 rows whose question text is
duplicated (the MINI/MAXI pairs) score measurably lower on factual_correctness
than the 136 unique ones. A subset that under- or over-samples them would not be
comparable to the full-run numbers, so the 25 % duplicate share is preserved.

Two properties matter and are asserted below:

- **Whole pairs only.** §4.10.2's finding is that the *same answer text* scores
  1.0 at one index of a pair and 0.0 at the other. Half a pair cannot show that.
- **Identical indices for every model.** The three eval_data files share question
  order, so the same row indices are the same questions — which is what makes the
  per-model comparison paired rather than three different populations.

Deterministic (fixed seed), so the qwen3.6 judge run can score the same 40 rows.

Usage:
    python3 rag-eval/make_subset.py [N]        # default 40
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

RESULTS = Path(__file__).parent / "results"
MODELS = [
    "eval_data__ollama_gemma3_27b-it-fp16.json",
    "eval_data__ollama_gemma4_31b-it-bf16.json",
    "eval_data__ollama_qwen3.6_27b-mtp-bf16.json",
]
SEED = 20260801


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    rows = {m: json.loads((RESULTS / m).read_text()) for m in MODELS}

    ref = rows[MODELS[0]]
    questions = [r["user_input"] for r in ref]
    for m in MODELS[1:]:
        if [r["user_input"] for r in rows[m]] != questions:
            sys.exit(f"FAILED: {m} has a different question order — indices would "
                     "not line up and the comparison would be unpaired")

    by_question: dict[str, list[int]] = defaultdict(list)
    for i, q in enumerate(questions):
        by_question[q].append(i)
    dup_pairs = [idxs for idxs in by_question.values() if len(idxs) > 1]
    unique = [idxs[0] for idxs in by_question.values() if len(idxs) == 1]

    dup_rows = sum(len(p) for p in dup_pairs)
    share = dup_rows / len(ref)
    # Round to whole pairs: sampling half a MINI/MAXI pair loses the effect.
    n_pairs = round(n * share / 2)
    n_unique = n - n_pairs * 2

    rnd = random.Random(SEED)
    picked_pairs = rnd.sample(dup_pairs, n_pairs)
    picked_unique = rnd.sample(unique, n_unique)
    idx = sorted([i for p in picked_pairs for i in p] + picked_unique)

    assert len(idx) == n, (len(idx), n)
    assert len(set(idx)) == n, "duplicate indices picked"
    for p in picked_pairs:
        assert all(i in idx for i in p), "a MINI/MAXI pair was split"

    print(f"full set : {len(ref)} rows, {dup_rows} duplicate-question rows "
          f"({share:.1%})")
    print(f"subset   : {n} rows, {n_pairs * 2} duplicate-question rows "
          f"({n_pairs * 2 / n:.1%}) from {n_pairs} whole pairs, "
          f"{n_unique} unique")
    print(f"indices  : {idx}")

    for m in MODELS:
        out = RESULTS / m.replace(".json", f"__sub{n}.json")
        out.write_text(json.dumps([rows[m][i] for i in idx],
                                  ensure_ascii=False, indent=2))
        chars = sum(len("".join(r["retrieved_contexts"]) + r["response"]
                        + r["user_input"] + r["reference"])
                    for r in (rows[m][i] for i in idx))
        print(f"wrote {out.name}  ({chars:,} chars)")

    # The index list is what makes a later judge run comparable to this one.
    (RESULTS / f"subset{n}_indices.json").write_text(json.dumps(idx))


if __name__ == "__main__":
    main()
