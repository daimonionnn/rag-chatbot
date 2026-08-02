#!/usr/bin/env python3
"""
Slovak language-quality test: the half of EVALUATION-LIMITS.md §4.4 that
multiple choice cannot reach.

§4.4 measured two things the RAGAS suite misses. `run_belebele.py` covers
comprehension and reasoning objectively. This covers what only free text shows:
whether the Slovak is *correct* — morphology, agreement, register — and whether
it is Slovak at all. §4.4's specific worry was that a model answering in fluent
Czech would score well and nothing would flag it.

Two kinds of check, deliberately separated:

- **Objective, no judge.** Czech orthographic markers (ř, ě, ů) are decisive:
  they do not occur in Slovak. Slovak-only characters (ô, ľ, ĺ, ŕ, ä) going
  missing across a whole answer is the weaker signal of the same drift. Neither
  needs a model to adjudicate, so neither inherits §4.5's judge problem.
- **Rubric, judged by claude-opus-5.** Grammar and naturalness need a reader.
  The judge is the neutral one from EVALUATION.md §3.10 — using gemma3 or
  qwen3.6 here would put a contestant in charge of scoring its rivals' Slovak,
  which is exactly the confound that section exists to avoid.

The prompts in `prompts_sk.json` are chosen to stress the places Slovak breaks:
numeral-noun agreement (1 pacient / 2 pacienti / 5 pacientov), genitive plural,
the rhythmic shortening rule, clitic order, aspect. A model with shaky Slovak
tends to survive ordinary prose and fail exactly there.

Usage:
    python3 sk-eval/run_fluency.py generate MODEL     # answers -> results/
    python3 sk-eval/run_fluency.py judge              # score everything generated
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"
OLLAMA = "http://localhost:11434/api/chat"
LLAMASTACK = "http://localhost:8321/v1/chat/completions"
JUDGE = "anthropic/claude-opus-5"

CZECH_ONLY = set("řěůŘĚŮ")
SLOVAK_ONLY = set("ôľĺŕäÔĽĹŔÄ")

RUBRIC = """Hodnotíš kvalitu SLOVENČINY v odpovedi jazykového modelu. Nehodnotíš, či je odpoveď fakticky správna — iba jazyk a splnenie zadania.

ZADANIE, ktoré model dostal:
{prompt}

ODPOVEĎ modelu:
{answer}

Ohodnoť tri osi, každú celým číslom 1 až 5:

1. "grammar" — gramatika a morfológia: pádové koncovky, zhoda podmetu s prísudkom, zhoda čísloviek s podstatnými menami, slovesný vid, rytmické krátenie. 5 = bez chyby, 3 = chyby, ktoré rodený hovorca zaregistruje, 1 = text je gramaticky rozbitý.
2. "naturalness" — znie to ako slovenčina rodeného hovorcu? Penalizuj čechizmy, doslovné kalky z angličtiny, neprirodzený slovosled a kostrbaté väzby. 5 = prirodzené, 1 = zjavne preložené alebo cudzie.
3. "task" — splnil model zadanie? 5 = splnil presne, 1 = nesplnil.

Ak nájdeš konkrétne chyby, vypíš ich doslovne do "errors" (max 5, každá ako krátky reťazec s chybným tvarom a správnym tvarom). Ak žiadne, daj prázdne pole.

Odpovedz IBA týmto JSON objektom, bez akéhokoľvek ďalšieho textu:
{{"grammar": <1-5>, "naturalness": <1-5>, "task": <1-5>, "errors": [<reťazce>]}}"""


def post(url: str, body: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def script_flags(text: str) -> dict:
    """Orthographic evidence about which language was actually produced."""
    cz = sorted(set(text) & CZECH_ONLY)
    sk = sorted(set(text) & SLOVAK_ONLY)
    letters = sum(c.isalpha() for c in text)
    diacritics = sum(c in "áäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ" for c in text)
    return {"czech_chars": cz, "slovak_chars": sk,
            "diacritic_rate": round(diacritics / letters, 4) if letters else 0.0}


def generate(model: str) -> None:
    prompts = json.loads((HERE / "prompts_sk.json").read_text())
    RESULTS.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    rows, t0 = [], time.time()
    for i, p in enumerate(prompts, 1):
        r = post(OLLAMA, {"model": model,
                          "messages": [{"role": "user", "content": p["prompt"]}],
                          "stream": False,
                          "options": {"temperature": 0.0, "num_predict": 8192}})
        answer = r["message"].get("content") or ""
        rows.append({**p, "answer": answer, **script_flags(answer)})
        print(f"  [{i:2}/{len(prompts)}] {p['id']:18} {len(answer):5} znakov"
              f"  cz={rows[-1]['czech_chars']}", flush=True)
    out = RESULTS / f"fluency__{slug}.json"
    out.write_text(json.dumps({"model": model, "minutes": round((time.time()-t0)/60, 1),
                               "rows": rows}, ensure_ascii=False, indent=1))
    print(f"wrote {out}")


def judge_all() -> None:
    files = sorted(RESULTS.glob("fluency__*.json"))
    if not files:
        sys.exit("no fluency__*.json to judge — run `generate` first")
    for f in files:
        data = json.loads(f.read_text())
        if all("scores" in r for r in data["rows"]):
            print(f"{f.name}: already judged, skipping")
            continue
        for i, row in enumerate(data["rows"], 1):
            body = {"model": JUDGE, "max_tokens": 8192,
                    "messages": [{"role": "user", "content": RUBRIC.format(
                        prompt=row["prompt"], answer=row["answer"])}]}
            txt = post(LLAMASTACK, body)["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", txt, re.S)
            row["scores"] = json.loads(m.group(0)) if m else None
            s = row["scores"]
            print(f"  [{i:2}] {row['id']:18} "
                  f"{'g=%s n=%s t=%s' % (s['grammar'], s['naturalness'], s['task']) if s else 'UNPARSED'}",
                  flush=True)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"{f.name}: judged")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "generate":
        generate(sys.argv[2])
    elif sys.argv[1] == "judge":
        judge_all()
    else:
        sys.exit(f"unknown command {sys.argv[1]!r}")
