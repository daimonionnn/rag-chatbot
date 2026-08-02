#!/usr/bin/env python3
"""
Download the Slovak and English halves of Belebele used by `run_belebele.py`.

Belebele (Meta, CC-BY-SA-4.0) is 900 multiple-choice reading-comprehension items
over FLORES passages, **professionally translated** into 122 languages. That last
point is why it was chosen over the machine-translated ARC/HellaSwag/MMLU sets:
when the property being measured is the language itself, a machine-translated
benchmark measures the translator.

The two configs are **parallel** — same items, same order, same correct answers —
which is what makes the sk−en difference in `run_belebele.py` interpretable as a
Slovak penalty with reasoning ability held constant. The script asserts that
rather than assuming it.

The downloaded files are gitignored: this fetches a slice of someone else's
dataset, so the repo keeps the fetcher and the results, not the corpus.

Usage:
    python3 sk-eval/fetch_belebele.py [N]     # default 100 items
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
API = ("https://datasets-server.huggingface.co/rows"
       "?dataset=facebook%2Fbelebele&config={cfg}&split=test"
       "&offset={off}&length={len}")
CONFIGS = {"sk": "slk_Latn", "en": "eng_Latn"}
PAGE = 50  # the rows endpoint caps a request at 100; 50 keeps it comfortable


def fetch(cfg: str, offset: int, length: int, tries: int = 4) -> list[dict]:
    url = API.format(cfg=cfg, off=offset, len=length)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return [x["row"] for x in json.load(r)["rows"]]
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    return []


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    out = {}
    for lang, cfg in CONFIGS.items():
        rows: list[dict] = []
        while len(rows) < n:
            rows += fetch(cfg, len(rows), min(PAGE, n - len(rows)))
            print(f"  {lang}: {len(rows)}/{n}")
        out[lang] = rows

    a, b = out["sk"], out["en"]
    mismatched = [i for i, (x, y) in enumerate(zip(a, b))
                  if x["question_number"] != y["question_number"]
                  or x["correct_answer_num"] != y["correct_answer_num"]
                  or x["link"] != y["link"]]
    if mismatched:
        sys.exit(f"FAILED: sk and en are not parallel at indices {mismatched[:5]} — "
                 "the sk-en comparison would be meaningless")

    for lang, rows in out.items():
        p = HERE / f"belebele_{lang}.json"
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"wrote {p.name}  ({len(rows)} items)")
    print(f"parallel across sk/en: verified on all {n} items")


if __name__ == "__main__":
    main()
