#!/usr/bin/env python3
"""
Slovak reading-comprehension and reasoning test for the three benchmarked models.

EVALUATION-LIMITS.md §4.4 measured that nothing in the RAGAS suite scores Slovak:
no metric targets grammar, morphology or fluency, and a model answering in fluent
Czech would pass unflagged. This is the reasoning half of the gap; `run_fluency.py`
is the language-quality half.

**Why Belebele.** 900 multiple-choice reading-comprehension items over FLORES
passages, professionally translated into 122 languages — not machine-translated,
which matters when the thing being measured *is* the language. Answers are one of
four, so scoring is objective and needs no judge: the whole
judge-is-a-contestant problem from §4.5 does not arise.

**Why sk and en on the same items.** The 900 items are parallel across languages,
so running the identical questions in both isolates the variable of interest.
Accuracy in Slovak alone conflates "can this model reason" with "can this model
read Slovak"; the sk−en difference on the same items is the Slovak penalty, with
reasoning ability held constant. A model that is simply weaker will score lower
in both and show a small gap; a model that is weak *at Slovak* shows a large one.

Thinking is left enabled where the model supports it: this is the one axis where
reasoning models might earn their cost, and disabling it would decide the answer
in advance (contrast EVALUATION.md §3.8, where it bought nothing on a
retrieval-and-copy task).

Usage:
    python3 sk-eval/run_belebele.py MODEL [LIMIT]

Writes sk-eval/results/belebele__<model>.json
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OLLAMA = "http://localhost:11434/api/chat"

# One letter is asked for, but models add prose anyway, so the parser below is
# deliberately forgiving rather than the prompt being more insistent — a stricter
# prompt would bias toward models that follow formatting instructions, which is
# not what this measures.
TEMPLATE = {
    "sk": ("Prečítaj si úryvok a odpovedz na otázku. Vyber jednu možnosť.\n\n"
           "ÚRYVOK:\n{passage}\n\nOTÁZKA: {question}\n\n"
           "1) {a1}\n2) {a2}\n3) {a3}\n4) {a4}\n\n"
           "Odpovedz iba číslom správnej možnosti (1, 2, 3 alebo 4)."),
    "en": ("Read the passage and answer the question. Choose one option.\n\n"
           "PASSAGE:\n{passage}\n\nQUESTION: {question}\n\n"
           "1) {a1}\n2) {a2}\n3) {a3}\n4) {a4}\n\n"
           "Answer with only the number of the correct option (1, 2, 3 or 4)."),
}


def ask(model: str, prompt: str) -> tuple[str, float]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        # Deterministic decoding, and a ceiling generous enough that a thinking
        # model can reason and still answer — BUGS.md A5 is the cautionary tale
        # of a budget that reasoning consumed entirely, leaving empty output.
        "options": {"temperature": 0.0, "num_predict": 8192},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        msg = json.load(r)["message"]
    return (msg.get("content") or ""), time.time() - t0


def parse(text: str) -> int | None:
    """First standalone 1-4 in the reply, or None if the model never committed."""
    m = re.search(r"\b([1-4])\b", text)
    return int(m.group(1)) if m else None


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    model = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    data = {lang: json.loads((HERE / f"belebele_{lang}.json").read_text())
            for lang in ("sk", "en")}
    if limit:
        data = {k: v[:limit] for k, v in data.items()}
    n = len(data["sk"])

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", model)

    rows, started = [], time.time()
    for i in range(n):
        rec = {"question_number": data["sk"][i]["question_number"],
               "gold": int(data["sk"][i]["correct_answer_num"])}
        for lang in ("sk", "en"):
            r = data[lang][i]
            prompt = TEMPLATE[lang].format(
                passage=r["flores_passage"], question=r["question"],
                a1=r["mc_answer1"], a2=r["mc_answer2"],
                a3=r["mc_answer3"], a4=r["mc_answer4"])
            text, secs = ask(model, prompt)
            rec[lang] = {"answer": parse(text), "secs": round(secs, 1),
                         "raw": text[:200]}
        rows.append(rec)
        done = i + 1
        rate = (time.time() - started) / done
        print(f"  [{done:3}/{n}] sk={rec['sk']['answer']} en={rec['en']['answer']} "
              f"gold={rec['gold']}  {rate:.1f}s/item  eta {rate*(n-done)/60:.0f}m",
              flush=True)

    acc = {lang: sum(1 for r in rows if r[lang]["answer"] == r["gold"]) / n
           for lang in ("sk", "en")}
    unparsed = {lang: sum(1 for r in rows if r[lang]["answer"] is None)
                for lang in ("sk", "en")}
    payload = {"model": model, "n": n, "accuracy": acc, "unparsed": unparsed,
               "minutes": round((time.time() - started) / 60, 1), "rows": rows}
    (out_dir / f"belebele__{slug}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1))

    print(f"\n{model}  n={n}  ({payload['minutes']} min)")
    print(f"  accuracy sk : {acc['sk']:.3f}   unparsed {unparsed['sk']}")
    print(f"  accuracy en : {acc['en']:.3f}   unparsed {unparsed['en']}")
    print(f"  sk − en     : {acc['sk'] - acc['en']:+.3f}   <- the Slovak penalty")


if __name__ == "__main__":
    main()
