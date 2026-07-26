<!-- translated-from: ddb460e -->
# 3 — RAGAS evaluácia

> **Slovenský preklad.** Zdroj: [`../../EVALUATION.md`](../../EVALUATION.md)
> v commite `ddb460e`. Anglický originál je zdroj pravdy — ak sa rozchádzajú,
> platí on. Prehľad prekladov: [INDEX.md](INDEX.md).

Adaptované z dvoch vzájomne sa dopĺňajúcich upstream repozitárov:

- [`llama-stack-provider-ragas`](https://github.com/Sheryl-shiyi/llama-stack-provider-ragas)
  (fork TrustyAI verzie) — RAGAS ako **out-of-tree llama-stack eval provider**
- [`proj-poc-RAGAS`](https://github.com/Sheryl-shiyi/proj-poc-RAGAS) —
  **metodika experimentu**: 182 slovenských QA párov, porovnanie štyroch modelov,
  jeden judge model hodnotiaci všetky behy

Nie sú to alternatívy: architektonický diagram samotného PoC beží ako „Llama Stack
+ RAGAS inline", teda presne na tomto provideri. Provider je engine, PoC je
harness.

Prerekvizita: stack z [SETUP.md](SETUP.md). Chyby, na ktoré sme tu narazili, sú
v [BUGS.md](BUGS.md).

---

## 3.1 Zladenie s pôvodným PoC

Jeho prezentácia setup presne dokumentuje a my ho kopírujeme:

| Parameter    | Upstream PoC                           | Tu                                         |
|--------------|----------------------------------------|--------------------------------------------|
| Embedding    | Qwen3-4B, dim 2560                     | `ollama/qwen3-embedding:4b-fp16`, dim 2560 |
| Chunking     | 512 tokenov, overlap 64                | rovnako                                    |
| Judge        | Gemma-3-27B (LLM-as-judge)             | `ollama/gemma3:27b-it-fp16`                |
| Framework    | RAGAS, inline režim                    | TrustyAI provider, inline                  |
| Dataset      | 182 QA párov z FAQ *Peňaženky zdravia* | rovnako, aj s ich odpoveďami v `reference` |
| Vector store | PGVector                               | FAISS (lokálne)                            |
| Serving      | vLLM na OpenShift AI                   | Ollama na hoste                            |

Ich repozitár obsahuje odvodené QA páry, ale **nie** zdrojové PDF, takže korpus
(16 PDF od VšZP) je dodaný lokálne v `docs/data/vszp` a naingestovaný do jedného
storu `vszp`.

Retrieval na slovenčine je po prepnutí embeddingu takmer presný — pri prvej
evaluačnej otázke je top chunk práve tá FAQ položka, ktorá na ňu odpovedá,
a takmer slovo za slovom sa zhoduje s referenčným textom.

---

## 3.2 Provider

Verzia providera **0.7.0** je tá, ktorá mieri na llama-stack **0.6.x**, takže
presne sedí na náš image (jeho branch `main` je v režime údržby; 0.7.0 je
finálna). Inštaluje sa v `Containerfile-0.6.0` a zapája v `config-0.6.0.yaml`:

```yaml
apis: [..., eval, benchmarks, datasetio]
providers:
  eval:
  - provider_id: ${env.EMBEDDING_MODEL:+trustyai_ragas_inline}
    provider_type: inline::trustyai_ragas
    module: llama_stack_provider_ragas.inline      # externý provider
```

Provider je podmienený premennou `EMBEDDING_MODEL` (nastavenou
v `compose-model-override.yml`), ktorá je zároveň embedding modelom, čo používajú
metriky založené na podobnosti — nastaviť sa nedá per benchmark.

Varianta providera `remote` potrebuje Kubeflow Pipelines server a nepoužívame ju.
Zapojený je len `localfs` datasetio, keďže naše evaluačné dáta sú lokálne.

Overenie, že je aktívny:

```bash
curl -s http://localhost:8321/v1/providers | grep -o '"trustyai_ragas_inline"'
```

---

## 3.3 Harness

Dva kroky, zrkadliace notebooky z PoC:

```bash
# 1. otázky -> RAG -> {user_input, response, retrieved_contexts, reference}
.client06-venv/bin/python rag-eval/run_rag.py ollama/gemma3:27b-it-fp16 [LIMIT]

# 2. tie riadky -> dataset + benchmark -> run_eval s judge modelom
.client06-venv/bin/python rag-eval/score_ragas.py \
    rag-eval/results/eval_data__ollama_gemma3_27b-it-fp16.json \
    ollama/gemma3:27b-it-fp16 [LIMIT]
```

`run_rag.py` prijme akékoľvek zaregistrované id modelu, takže prefix `nemo/` meria
guardrailovanú cestu namiesto priamej. `reference` (ground truth) vždy pochádza
z datasetu upstream PoC, čím zostávajú naše čísla porovnateľné s ich.

Výstupy končia v `rag-eval/results/` (v gitignore — sú generované a odvodené
z interných dokumentov).

### Metriky

Všetkých šesť metrík z PoC, keď je provider opatchovaný:

```
faithfulness · answer_relevancy · context_precision · context_recall
answer_similarity · factual_correctness
```

`answer_correctness` v ragas 0.4.x už neexistuje; jej nástupcom je
`factual_correctness`, ktorá si vyžadovala opravu providera, aby vôbec fungovala —
ragas kľúčuje skóre ModeMetric ako `factual_correctness(mode=f1)`, kým provider ich
hľadal pod čistým názvom (pozri [BUGS.md](BUGS.md)). Sadu sa dá prepísať cez
`METRICS=a,b,c`.

---

## 3.4 Náklady

Namerané: **~15–17 s na (riadok, metrika)** pri skórovaní a ~7 s na otázku pri
generovaní.

| Rozsah                                          | Reálny čas |
|-------------------------------------------------|------------|
| generovanie, 182 otázok, jeden model            | ~21 min    |
| skórovanie, 182 riadkov × 6 metrík, jeden model | ~5 h       |
| **celý beh, jeden model**                       | **~5,3 h** |
| celý beh, tri modely                            | **~16 h**  |
| podmnožina 40 otázok, tri modely                | ~3,5 h     |

Judge a testovaný model sú väčšinou odlišné, takže Ollama ich raz za model
prehodí (~30 s). Embedding model (8 GB) zostáva rezidentný vedľa LLM bez
thrashingu.

---

## 3.5 Výsledok smoke testu

Dva riadky, gemma3 generuje aj hodnotí — cieľom bolo dokázať funkčnosť celej
pipeline ešte pred tým, než sa pustí ~16-hodinový beh:

| Metrika             | Agregát |
|---------------------|---------|
| faithfulness        | 1.000   |
| context_precision   | 1.000   |
| context_recall      | 1.000   |
| answer_similarity   | 0.975   |
| answer_relevancy    | 0.673   |
| factual_correctness | 0.665   |

Dva riadky nedokazujú nič o kvalite — dokazujú, že je to správne zapojené.

---

## 3.6 Než začneš tým číslam veriť

Prečítaj si [EVALUATION-LIMITS.md](EVALUATION-LIMITS.md). Krátka verzia, všetko
odmerané na tomto stacku:

- Modely dokážu rozlíšiť len **štyri** zo šiestich metrík; dve z nich odpoveď
  vôbec nevidia a merajú namiesto toho zdieľanú vrstvu retrievalu.
- 99 % otázok **aj** ich referenčných odpovedí sa nachádza doslovne v PDF, ktoré
  je v korpuse, takže je to bližšie k úlohe „nájdi a skopíruj" než k benchmarku
  uvažovania.
- `answer_similarity` dá **negovanému faktu** alebo **10× nesprávnej sume v eurách**
  skóre ~0,99, kým **úplne správna odpoveď po anglicky** dostane 0,83 — je to
  kontrola plynulosti a témy, nie správnosti.
- **Žiadna metrika nemeria kvalitu slovenčiny**, takže odpoveď v plynulej češtine
  alebo v kostrbatej slovenčine by prešla bez povšimnutia.

---

## 3.7 Výsledky celého benchmarku

Všetkých 182 otázok, všetky tri modely, judge `ollama/gemma3:27b-it-fp16` po celý
čas (takže výhrada „judge je jeden zo súťažiacich"
z [EVALUATION-LIMITS.md §4.5](EVALUATION-LIMITS.md) platí na každý gemma3
stĺpec). Bežalo 2026-07-25 21:56 → 2026-07-26 16:57, celkovo 1141 min (~19 h —
dlhšie než odhadovaných ~16 h; prečo, je v tabuľke časov nižšie). Nula zlyhaných
jobov; riadky `NaN` (z odpovede judge-a, ktorú ragas nedokázal rozparsovať, pozri
[BUGS.md](BUGS.md) A2) sa počítali ako chýbajúce a sú z priemerov nižšie vylúčené,
namiesto toho, aby priemer stláčali na nulu.

| Metrika             | gemma3     | gemma4     | qwen3.6    | Rozlišuje modely?               |
|---------------------|-----------:|-----------:|-----------:|:-------------------------------:|
| context_recall      | 0.9960     | 0.9960     | 0.9932     | nie — len retrieval, pozri §4.1 |
| context_precision   | 0.9882     | 0.9844     | 0.9851     | nie — len retrieval, pozri §4.1 |
| faithfulness        | 0.9820     | **0.9872** | 0.9713     | áno                             |
| answer_relevancy    | 0.6030     | 0.6507     | **0.6634** | áno                             |
| answer_similarity   | **0.9628** | 0.9242     | 0.8914     | áno                             |
| factual_correctness | **0.8885** | 0.8438     | 0.8008     | áno                             |

`context_recall` vyšla medzi gemma3 a gemma4 **bit-presne rovnako** (0,9960 =
0,9960), čím sa priamo potvrdila predpoveď z §4.1: keď je retrieval konštantný, tá
metrika modely rozlíšiť nedokáže.

### Generovanie a kvalita dát

|                                                   | gemma3 | gemma4 | qwen3.6 |
|---------------------------------------------------|-------:|-------:|--------:|
| čas generovania (182 otázok)                      | 17 min | 76 min | 41 min  |
| dĺžka odpovede, medián znakov                     | 248    | 268    | 355     |
| dĺžka odpovede, max znakov                        | 820    | 1977   | 1919    |
| tagy `<think>`/`<reasoning>` uniknuté do odpovede | 0      | 0      | 0       |
| riadky NaN pri faithfulness                       | 2      | 3      | 2       |
| riadky NaN pri factual_correctness                | 1      | 5      | 0       |

gemma4 aj qwen3.6 deklarujú schopnosť `thinking`; gemma3 nie. Napriek tomu
**nedošlo k úniku reasoning textu do žiadnej odpovede** u žiadneho modelu —
ochrana `strip_reasoning()` v `run_rag.py` sa nemusela ani raz uplatniť (jej log
riadok sa nikdy nevypísal). 4,5× dlhší čas generovania u gemma4 pri len o málo
dlhšom výstupe je konzistentný s tým, že Ollama vracia reasoning tokeny mimo
`content` — takže ten čas navyše je cena za latenciu, nie riziko kontaminácie.

### Ako čítať tie štyri skutočné metriky spolu

- **gemma3** vedie na `answer_similarity` a `factual_correctness` — je najbližšie
  k referenčnému textu.
- **qwen3.6** vedie na `answer_relevancy`, gemma4 tesne za ňou; obe pred gemma3.
- **gemma4** vedie na `faithfulness`.
- Dĺžka odpovede rastie monotónne s odstupom od referencie (gemma3 248 znakov →
  gemma4 268 → qwen3.6 355), čo je očakávaný tvar, ak dlhšie a rozvinutejšie
  odpovede lexikálne odbočujú od úsečnej FAQ-referencie, pričom stále zostávajú
  dobre podložené a k téme.

Ani jeden z týchto rozdielov by sa nemal čítať ako poradie bez výhrad
z [EVALUATION-LIMITS.md §4.10](EVALUATION-LIMITS.md) — najmä preto, že sa našla
konkrétna, odmeraná chyba datasetu (duplicitné otázky s nezhodnými referenciami),
ktorá stláča `factual_correctness` u všetkých troch modelov, a neexistujú opakované
behy, ktoré by ukázali, či rozdiely tejto veľkosti presahujú vlastný šum judge-a.
