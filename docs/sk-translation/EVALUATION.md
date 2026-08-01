<!-- translated-from: 3ce3a92 -->
# 3 — RAGAS evaluácia

> **Slovenský preklad.** Zdroj: [`../../EVALUATION.md`](../../EVALUATION.md)
> v commite `3ce3a92`. Anglický originál je zdroj pravdy — ak sa rozchádzajú,
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

---

## 3.8 Čo je thinking hodný

gemma4 aj qwen3.6 pred odpoveďou uvažujú; gemma3 nie. §3.7 ich merala s
reasoningom zapnutým, čím zostali otvorené dve veci: koľko ten reasoning prinesie
a — tam označené za otvorený problém — či rozdiely tej veľkosti presahujú vlastný
šum judge-a. Jeden experiment vyrieši oboje.

Oba modely sa prehnali znova s vypnutým reasoningom, proti rovnakému judge-ovi,
rovnakým otázkam a **rovnakým načítaným kontextom, prevzatým verbatim** z behu
s thinkingom (`run_rag.py --no-think`, prečo to musí obchádzať OpenAI-kompatibilnú
cestu, je v BUGS.md D12). Jediné, čím sa tie dva stĺpce líšia, je teda odpoveď.

Beh 2026-07-26 22:39 → 2026-07-27 10:46, trvanie 726 min, nula zlyhaných jobov.
Že `think: false` funguje, sa overilo, nie predpokladalo: reasoning sa vrátil ako
presne **0 znakov** naprieč všetkými 364 generovaniami a v probe `eval_count`
klesol 237 → 24 (gemma4) a 173 → 26 (qwen3.6).

### Noise floor, nameraný zadarmo

`context_precision` a `context_recall` skórujú *retrieval*, a ten bol medzi behmi
držaný bajtovo identický. Čímkoľvek sa pohnú, je teda judge nesúhlasiaci sám so
sebou, nie efekt:

| Retrieval metrika | gemma4 Δ | qwen3.6 Δ |
|-------------------|---------:|----------:|
| context_precision | −0.0014  | −0.0063   |
| context_recall    | −0.0027  | +0.0000   |

Na tomto harnesse je teda **|Δ| zhruba do 0.006 šum**. `context_recall` pre
qwen3.6 sa zreprodukoval na cifru presne (+0.0000), čo je najsilnejší dostupný
dôkaz, že samotná pipeline je stabilná a že tá variabilita je judge-ova.

### Výsledky

Párované cez riadky, ktoré oskórovali oba behy — NaN riadky nie sú v oboch tie
isté, takže priemery cez plných 182 by porovnávali odlišné populácie.

| Metrika             | gemma4 ON | gemma4 OFF | Δ       | qwen3.6 ON | qwen3.6 OFF | Δ       |
|---------------------|----------:|-----------:|--------:|-----------:|------------:|--------:|
| faithfulness        | 0.9868    | 0.9873     | +0.0005 | 0.9711     | 0.9737      | +0.0025 |
| answer_relevancy    | 0.6507    | 0.6381     | −0.0126 | 0.6634     | 0.6413      | −0.0220 |
| answer_similarity   | 0.9242    | 0.9223     | −0.0019 | 0.8914     | 0.9086      | +0.0172 |
| factual_correctness | 0.8414    | 0.8363     | −0.0051 | 0.8010     | 0.8351      | +0.0341 |

| Generovanie (182 otázok) | thinking zap | thinking vyp | zrýchlenie |
|--------------------------|-------------:|-------------:|-----------:|
| gemma4                   | 76,5 min     | 22,1 min     | 3,5×       |
| qwen3.6                  | 42,3 min     | 11,2 min     | 3,8×       |

| Dĺžka odpovede, medián znakov | zap | vyp |
|-------------------------------|----:|----:|
| gemma4                        | 268 | 247 |
| qwen3.6                       | 355 | 294 |

### Ako to čítať

**Thinking nie je jednoznačne lepší a pre qwen3.6 je väčšinou horší.** Jeho
vypnutie stálo 3,5–3,8× menej času na generovanie a s metrikami pohlo takto:

- **`answer_relevancy` klesá u oboch modelov** (−0.0126, −0.0220) — jediná
  konzistentná cena za odobratie reasoningu a jediný efekt, ktorý sa reprodukuje
  naprieč modelmi.
- **`factual_correctness` u qwen3.6 *stúpa* o +0.0341** — asi päťnásobok noise
  flooru a viac než ktorýkoľvek rozdiel gemma4 vs qwen3.6 v §3.7. Reasoning tomuto
  modelu na tomto korpuse faktickú presnosť aktívne škodil.
- **`answer_similarity` u qwen3.6 stúpa o +0.0172.** Táto metrika je čisto
  embedding-ová, bez judge-a v slučke, takže nenesie žiadny jeho šum.
- **gemma4 sa takmer nehýbe.** Pri floore 0.006 je reálna len zmena
  `answer_relevancy`; `faithfulness`, `answer_similarity` aj `factual_correctness`
  sú všetky v šume.
- **`faithfulness` je v šume u oboch.** Reasoning nerobí odpovede podloženejšími
  v načítanom texte.

Jeden mechanizmus vierohodne vysvetľuje všetky smery naraz: **odpovede sú bez
reasoningu kratšie** (qwen3.6 medián 355 → 294). Kratšie odpovede sedia bližšie
k úsečnej FAQ-referencii, čo dvíha `answer_similarity` aj `factual_correctness`,
a pokrývajú menej, čo znižuje `answer_relevancy` — presne ten efekt dĺžky, ktorý
§3.7 pozorovala *naprieč* modelmi, tu zreprodukovaný *vnútri* modelu. To robí
zo ziskov qwen3.6 slabšie tvrdenie, než samotné čísla naznačujú, a najmä
`answer_similarity` treba čítať s [EVALUATION-LIMITS.md §4.3](EVALUATION-LIMITS.md)
v ruke: dala 0.9943 zápornej verzii faktu a 0.9899 desaťnásobne nesprávnej sume,
takže „podobnejšie" nie je „správnejšie".

Praktické čítanie: **pre tento korpus reasoning nestojí za svoju cenu.** Ztrojnásobí
čas generovania, aby kúpil zhruba dva body `answer_relevancy`, a u qwen3.6 vzdá
viac `factual_correctness`, než kdekoľvek získa.

---

## 3.9 Ktorý model a nakoľko sa dá poradiu veriť

§3.7 a §3.8 odmerali päť konfigurácií. Tu sú zozbierané na jednej škále, s noise
floorom 0.006 z §3.8, aby sa rozdiely, ktoré nie sú reálne, nečítali ako poradie.

| Konfigurácia     | faithfulness | answer_relevancy | answer_similarity | factual_correctness | medián znakov | generovanie |
|------------------|-------------:|-----------------:|------------------:|--------------------:|--------------:|------------:|
| **gemma3**       | 0.9820       | 0.6030           | **0.9628**        | **0.8885**          | 248           | 17 min      |
| gemma4 think     | 0.9872       | 0.6507           | 0.9242            | 0.8438              | 268           | 76 min      |
| gemma4 no-think  | **0.9874**   | 0.6381           | 0.9223            | 0.8361              | 247           | 22 min      |
| qwen3.6 think    | 0.9713       | **0.6634**       | 0.8914            | 0.8008              | 355           | 41 min      |
| qwen3.6 no-think | 0.9740       | 0.6413           | 0.9086            | 0.8351              | 294           | **11 min**  |

`faithfulness` gemma3 od gemma4 neodlíši — 0.9820 vs 0.9874 je vnútri noise
flooru. Zvyšné tri majú každá jasného víťaza.

**Poradie na tomto korpuse: gemma3, potom gemma4, potom qwen3.6.** gemma3 berie
dve zo štyroch metrík s odstupom ďaleko mimo šumu (+0.039 `answer_similarity`,
+0.045 `factual_correctness` nad druhým v poradí); gemma4 berie `faithfulness`,
ale len v rámci šumu voči gemma3; qwen3.6 berie `answer_relevancy` a je posledná
v zhode s referenciou.

### Nie je to artefakt dĺžky

§3.8 ukázala, že kratšie odpovede skórujú vyššie na metrikách zhody s referenciou,
čím by sa dal náskok gemma3 zjavne odvysvetliť. Dáta to nepotvrdzujú. gemma3
(medián 248 znakov) a gemma4 no-think (247) sú rovnako dlhé a napriek tomu sa
líšia o **0.040** na `answer_similarity` a o **0.052** na `factual_correctness`.
Efekt dĺžky je reálny *vnútri* modelu a rozdiely *medzi* nimi nevysvetľuje.

### Confound, ktorý zaberá

**gemma3 je judge** (§4.5) a metrika, ktorú vyhráva najpresvedčivejšie,
`factual_correctness`, je judge-om skórovaná. Judge preferujúci odpovede, ktoré
vyzerajú ako jeho vlastný výstup, je učebnicový tvar tohto javu a nič v týchto
behoch ho nevie vylúčiť.

Čiastočný protidôkaz: `answer_similarity` **žiadneho judge-a v slučke nemá** — je
to kosínusová podobnosť embeddingov — a gemma3 vedie aj tam, pri rovnakej dĺžke
odpovede. Takže gemma3 naozaj produkuje text najbližší referencii, s judge-om aj
bez neho. Lenže `answer_similarity` je tá metrika, ktorú §4.3 odmerala ako takmer
slepú voči správnosti (0.9943 zápornej verzii faktu), takže „najbližšie
k referencii" nie je „najsprávnejšie" — a metrika, ktorá by ten krok urobila, je
práve tá zaťažená confoundom.

**Rozhodnuté v §3.10** preskórovaním existujúcich odpovedí každého modelu
judge-om, ktorý nie je jedným zo súťažiacich. Prvé miesto gemma3 obstálo; druhé
a tretie nie.

### Praktické odporúčanie

- **gemma3 ako default** pre tento korpus: vyhráva zhodu s referenciou, generuje
  najrýchlejšie spomedzi možností bez thinkingu a je to pôvodná voľba PoC.
- **gemma3 nezvláda tool calling vôbec** (BUGS.md B3), takže ak sa chce
  Agent-based mód, je mimo hru a voľbou je **qwen3.6 s vypnutým thinkingom** —
  najrýchlejšia zo všetkých piatich s 11 min a `factual_correctness` 0.8351
  namiesto 0.8008.
- **Thinking nezapínať ani na jednom.** Na gemma4 nekúpi nič merateľné za 3,5×
  dlhší čas generovania a na qwen3.6 aktívne stojí faktickú presnosť.

---

## 3.10 Cross-judged: ktoré časti poradia sú o modeloch

§3.9 zoradila päť konfigurácií a [EVALUATION-LIMITS.md §4.5](EVALUATION-LIMITS.md)
namietla, že judge bol jedným zo súťažiacich: gemma3 skórovala každý beh vrátane
vlastného a metrika, ktorú vyhráva najpresvedčivejšie — `factual_correctness` —
je skórovaná judge-om. Táto sekcia preskóruje tie isté odpovede judge-om, ktorý
súťažiacim nie je nijako, `anthropic/claude-opus-5`, a hlási, čo sa pohlo.

Nič sa negenerovalo nanovo. Uložené odpovede a ich retrieved contexts sa čítajú
doslovne, takže **judge je jediné, čo sa oproti §3.7 líši**. Beh 2026-08-01,
40 riadkov na model, ~62 min a ~$11 na model, nula zlyhaných volaní judge-a.

### Podmnožina a prečo to nie je 40 náhodných riadkov

§4.10.2 odmerala, že 46 riadkov s duplicitným textom otázky (dvojice MINI/MAXI)
skóruje na `factual_correctness` nižšie než 136 unikátnych, a to pri každom
modeli. Podmnožina, ktorá by ich vzorkovala v inom pomere, by nebola porovnateľná
s plným behom, takže `rag-eval/make_subset.py` ten podiel zachováva — 25,0 %
oproti 25,3 % plného setu — a berie **iba celé dvojice**, keďže efekt z §4.10.2
spočíva v tom, že *tá istá odpoveď* skóruje 1.0 na jednom indexe dvojice a 0.0 na
druhom. Obaja judge-ovia skórujú tých istých 40 indexov a uložené 182-riadkové
výsledky sa pred akýmkoľvek porovnaním nareže na tie isté indexy, takže zmena
judge-a nie je nikdy confoundnutá so zmenou vzorky.

### Výsledky

Párovo cez riadky, ktoré oskórovali obaja judge-ovia (`n` sa líši podľa metriky,
lebo ktorýkoľvek judge môže riadok neoskórovať — v praxi to spravila len gemma3,
na 2 riadkoch `faithfulness` a 1 riadku `factual_correctness`; claude-opus-5
vrátil skóre pre všetkých 40 riadkov všetkých 6 metrík u všetkých 3 modelov).
`context_precision` a `context_recall` sú tu vynechané a rozobrané nižšie; nikdy
nevidia odpoveď, takže modely zoradiť nevedia.

| Metrika             | gemma3          | gemma4     | qwen3.6    | gemma3                 | gemma4     | qwen3.6    | n   |
|---------------------|----------------:|-----------:|-----------:|-----------------------:|-----------:|-----------:|----:|
|                     | *judge: gemma3* |            |            | *judge: claude-opus-5* |            |            |     |
| faithfulness        | 0.9794          | **0.9846** | 0.9598     | 0.9971                 | **1.0000** | 0.9732     | 38  |
| answer_relevancy    | 0.5896          | 0.6498     | **0.6791** | 0.7173                 | 0.7920     | **0.8073** | 40  |
| answer_similarity   | **0.9564**      | 0.9160     | 0.8759     | **0.9564**             | 0.9160     | 0.8759     | 40  |
| factual_correctness | **0.9023**      | 0.8369     | 0.7733     | **0.8810**             | 0.7718     | 0.7679     | 39  |

**Víťaz každej metriky je nezmenený.** Všetky štyri vyberajú pod oboma judge-mi
ten istý model.

### Prvé miesto gemma3 nie je artefakt sebahodnotenia

Obava znela konkrétne tak, že gemma3 nafukuje vlastnú `factual_correctness`.
Nenafukuje — presnejšie, čokoľvek robí svojmu skóre, robí gemma4 viac:

| `factual_correctness` | judge gemma3 | judge claude-opus-5 |
|-----------------------|-------------:|--------------------:|
| gemma3 − gemma4       | +0.0654      | **+0.1092**         |
| gemma3 − qwen3.6      | +0.1290      | +0.1131             |

Náskok nad gemma4 sa pod neutrálnym judge-om takmer zdvojnásobí a náskok nad
qwen3.6 sa udrží (zmena −0.016 je vnútri šumového pásma nižšie). Hypotéza z §4.5
mierila správnym smerom na nesprávny cieľ: confound bol skutočný, ale margin
gemma3 **podhodnocoval**, nie vyrábal.

### Čo neprežilo: druhé miesto

| `factual_correctness` | judge gemma3 | judge claude-opus-5 |
|-----------------------|-------------:|--------------------:|
| gemma4 − qwen3.6      | +0.0636      | **+0.0039**         |

Pod neutrálnym judge-om sú tieto dva nerozoznateľné — 0.0039 je šestina
rozlíšenia tejto vzorky. Tých šesť bodov, ktoré ich delilo, bol podstatne názor
gemma3, nie vlastnosť odpovedí. gemma4 si drží `faithfulness`, qwen3.6
`answer_relevancy`, a metrika, ktorá to mala rozseknúť, to neseká.

**Poradie sa teda delí na dve časti.** „gemma3 prvá" je zistenie o modeloch.
„gemma4 druhá, qwen3.6 tretia" bolo zistenie o judge-ovi.

### Úrovne metrík závisia od judge-a, poradia nie

`answer_relevancy` stúpla o +0.128 až +0.142 **všetkým trom** modelom pri
zachovaní ich poradia. Jej absolútna hodnota preto sama o sebe nehovorí takmer
nič — 0.72 od jedného judge-a a 0.59 od druhého popisujú tie isté odpovede. Čítať
ju treba len ako porovnanie v rámci jedného judge-a. V tabuľke §3.7 to nie je
vidieť nikde, tá číslo prezentuje, akoby bolo vlastnosťou modelu.

`answer_similarity` sa naprieč judge-mi reprodukuje na štyri desatinné miesta,
ako musí: je to kosínusová podobnosť embeddingov bez judge-a v slučke. To, že
vyšla identicky, je kontrola, ktorá dáva zvyšku tabuľky váhu — potvrdzuje, že
obaja judge-ovia videli tie isté riadky, narezané rovnako.

### Druhé šumové pásmo, opäť zadarmo

`context_precision` a `context_recall` konzumujú referenciu, kontexty a otázku —
nikdy odpoveď. Naprieč tromi súbormi modelov sú tie vstupy **bajtovo identické**,
takže tri skórovania by mali vrátiť po jednej hodnote. Vracajú dve, na oboch
metrikách. §3.8 presne týmto odvodila svoje pásmo 0.006:

| Skórované na   | context_precision | context_recall |
|----------------|------------------:|---------------:|
| súbore gemma3  | 0.8983            | **0.9679**     |
| súbore gemma4  | 0.8983            | 0.9929         |
| súbore qwen3.6 | **0.8995**        | 0.9929         |

V oboch prípadoch sa preklopil presne **jeden riadok zo 40** —
`context_precision` na súbore qwen3.6, `context_recall` na súbore gemma3. gemma3
ako judge sa nespráva lepšie: na `context_precision` rozdelila 0.9914 / 0.9815
medzi dva súbory, kým `context_recall` zreprodukovala presne.

To určuje rozlíšenie tejto vzorky: jeden riadok je 0.025, takže žiadny rozdiel
pod touto hodnotou nie je interpretovateľný, a pásmo je nutne širšie než 0.006
z §3.8, lebo vzorka je štvrtinová.

Aplikované: pokles vlastnej `factual_correctness` gemma3 o −0.0202 je *pod*
pásmom a sám o sebe neznamená nič; −0.0651 gemma4 a rozšírenie rozdielu
gemma3–gemma4 o +0.0438 sú nad ním.

Zároveň to ukazuje, že retrieval metriky nie sú tie čisté konštanty konfigurácie,
aké predpokladala §4.1. Nad rámec vlastnej nestability každého judge-a sa tí dvaja
navzájom líšia o −0.093 na `context_precision` pri identickom retrievale. Merajú
retrieval *aj* judge-a, a oprava navrhnutá v §4.1 — vykázať ich raz ako vlastnosť
retrieval konfigurácie — platí len v rámci jedného judge-a.

### Čo tento beh oddeliť nevie

Neutrálny judge sa dosahuje cez chat completions, kým lokálni judge-ovia
používajú raw text-completions endpoint, ktorý Anthropic neposkytuje (BUGS.md
A4). Chat aplikuje chat template modelu, takže „iný judge" a „iné zarámovanie
promptu" sa tu pohli spolu a žiadnu časť rozdielov nemožno pripísať jednému skôr
než druhému. Presmerovať cez chat aj lokálnych judge-ov by ich urobilo
porovnateľnými navzájom, ale znehodnotilo by každé číslo v §3.7, takže confound
je zdokumentovaný, nie odstránený.

Dve ďalšie obmedzenia: 40 riadkov namiesto 182, s dôsledkom na rozlíšenie vyššie;
a jeden judge namiesto plnej matice 3×3, takže toto hovorí, že náskok gemma3
prežije *tohto* neutrálneho judge-a, nie každého.
