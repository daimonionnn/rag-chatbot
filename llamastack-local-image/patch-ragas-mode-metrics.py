#!/usr/bin/env python3
"""
Recover `factual_correctness` (and any other ModeMetric) in the inline TrustyAI
RAGAS provider.

ragas keys each row's scores by metric, but mode-carrying metrics get the mode
appended (ragas/evaluation.py):

    if isinstance(m, ModeMetric):
        key = f"{m.name}(mode={m.mode})"
    else:
        key = m.name

The provider collects results with `result[m.name]`, i.e. always the bare name.
For `FactualCorrectness` — which is a ModeMetric with mode="f1" — the real key is
"factual_correctness(mode=f1)", so the whole evaluation job dies with
`KeyError: 'factual_correctness'`. It is purely a naming-convention mismatch, not
a limitation of the metric.

Fix: resolve the key the way ragas wrote it (bare name, then "<name>(mode=…)",
then any "<name>(…)"), while still reporting scores under the bare metric name so
the API surface is unchanged.

Idempotent; exits non-zero if the expected source is missing so a provider
upgrade cannot silently drop the patch.
"""
from __future__ import annotations

import pathlib
import sys
from importlib.util import find_spec

OLD = """        # Convert scores to ScoringResult format
        scores = {}
        for metric_name in [m.name for m in metrics]:
            metric_scores = result[metric_name]"""

NEW = """        # Convert scores to ScoringResult format
        scores = {}
        for _ls_metric in metrics:
            metric_name = _ls_metric.name
            metric_scores = _ls_metric_scores(result, _ls_metric)"""

HELPER = '''

def _ls_metric_scores(result, metric):
    """Fetch a metric's per-row scores from a ragas EvaluationResult.

    Added by patch-ragas-mode-metrics.py. ragas appends the mode to the score
    key for ModeMetric instances ("factual_correctness(mode=f1)"), while the
    provider originally looked results up by the bare metric name and therefore
    raised KeyError for those metrics.
    """
    name = metric.name
    try:
        return result[name]
    except KeyError:
        pass
    mode = getattr(metric, "mode", None)
    if mode is not None:
        try:
            return result[f"{name}(mode={mode})"]
        except KeyError:
            pass
    try:
        for key in result._scores_dict:
            if key.startswith(f"{name}("):
                return result[key]
    except Exception:
        pass
    raise KeyError(name)
'''


def main() -> int:
    spec = find_spec("llama_stack_provider_ragas")
    if spec is None or spec.origin is None:
        print("patch: llama_stack_provider_ragas not importable", file=sys.stderr)
        return 1
    target = (pathlib.Path(spec.origin).parent
              / "inline" / "ragas_inline_eval.py")
    if not target.is_file():
        print(f"patch: {target} not found", file=sys.stderr)
        return 1

    src = target.read_text()
    if "_ls_metric_scores" in src:
        print(f"patch: already applied to {target}")
        return 0
    if OLD not in src:
        print("patch: expected score-collection block not found — provider "
              "changed, re-check the fix", file=sys.stderr)
        return 1

    src = src.replace(OLD, NEW, 1)
    src = src.rstrip("\n") + "\n" + HELPER
    target.write_text(src)
    print(f"patch: applied RAGAS ModeMetric key fix to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
