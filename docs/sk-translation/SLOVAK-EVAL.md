<!-- translated-from: 3fdaa91 -->
# 5 — Brzdí tieto modely samotná slovenčina?

> **Slovenský preklad.** Zdroj: [`../../SLOVAK-EVAL.md`](../../SLOVAK-EVAL.md)
> v commite `3fdaa91`. Anglický originál je zdroj pravdy — ak sa rozchádzajú,
> platí on. Prehľad prekladov: [INDEX.md](INDEX.md).

[EVALUATION-LIMITS.md §4.4](EVALUATION-LIMITS.md) odmerala, že RAGAS sada
neskóruje slovenčinu **vôbec**: žiadna metrika necieli na gramatiku, morfológiu,
register ani plynulosť, a model odpovedajúci plynulou češtinou by prešiel
neoznačený. Pomenovala dve lacné doplnenia a obe nechala nepostavené. Toto sú tie
dve, postavené a spustené.

Je to samostatný dokument, nie sekcia [EVALUATION.md](EVALUATION.md), pretože ide
o iné meranie: iný korpus, iné skórovanie a — pri jednej polovici — žiadny judge.

---

## 5.1 Čo sa meria a prečo v takomto tvare

Dve polovice, lebo „je tá slovenčina dobrá" sú dve otázky, ktoré sa rozchádzajú.
Model môže slovenčine dokonale rozumieť a písať ju zle; opačne je to zriedkavejšie,
ale nie je to jedna schopnosť.

| Polovica                                                   | Otázka | Skórovanie |
|------------------------------------------------------------|-----|-----|
| **A** — [`run_belebele.py`](../../sk-eval/run_belebele.py) | Rozumie model slovenskému textu a vie nad ním uvažovať? | Objektívne, výber zo štyroch, **bez judge-a** |
| **B** — [`run_fluency.py`](../../sk-eval/run_fluency.py)   | Je slovenčina, ktorú model *produkuje*, správna a prirodzená? | Pravopisné kontroly (bez judge-a) + rubrika skórovaná `claude-opus-5` |

### Prečo Belebele a prečo oba jazyky

[Belebele](https://huggingface.co/datasets/facebook/belebele) (Meta,
CC-BY-SA-4.0) je 900 položiek čítania s porozumením nad úryvkami z FLORES,
**profesionálne preložených** do 122 jazykov. To je rozhodujúca vlastnosť: keď je
meranou vlastnosťou jazyk, strojovo preložený benchmark meria prekladač. Tá istá
úvaha vylúčila slovenské časti
[mlmm-evaluation](https://github.com/nlp-uoregon/mlmm-evaluation)
(ARC/HellaSwag/MMLU preložené cez ChatGPT) aj
[skLEP](https://arxiv.org/abs/2506.21508), ktorý je GLUE-štýlové sekvenčné
značkovanie stavané na fine-tunované enkodéry, nie na generatívne modely.

Položky sú naprieč jazykmi paralelné, takže **tých istých 100 otázok beží po
slovensky aj po anglicky**. Samotná slovenská presnosť mieša „vie tento model
uvažovať" s „vie tento model čítať po slovensky". Rozdiel sk−en ich oddelí, so
schopnosťou uvažovať držanou konštantne už konštrukciou. Celkovo slabší model
skóruje nižšie v oboch a medzera bude malá; model slabý *v slovenčine* bude mať
medzeru veľkú.

Thinking ostáva zapnutý tam, kde ho model podporuje. Toto je tá jediná os, kde by
si uvažujúci model mohol svoju cenu zaslúžiť, a vypnúť ho by znamenalo rozhodnúť
otázku vopred — na rozdiel od [EVALUATION.md §3.8](EVALUATION.md), kde thinking
na úlohe „nájdi a skopíruj" nepriniesol nič.

### Prečo prompty v polovici B vyzerajú takto

Bežná slovenská próza tieto modely neodlíši. Tých 18 promptov v
[`sk-eval/prompts_sk.json`](../../sk-eval/prompts_sk.json) cieli tam, kde sa
slovenčina naozaj láme: zhoda čísloviek s podstatnými menami (1 pacient /
2 pacienti / 5 pacientov), genitív plurálu, rytmické krátenie, poradie príkloniek,
slovesný vid, formálny register. Chyby nižšie padli presne tam a takmer nikde
inde, čo je dôkaz, že cielenie fungovalo.

Judge je `claude-opus-5` — ten neutrálny z [EVALUATION.md §3.10](EVALUATION.md).
Použiť gemma3 alebo qwen3.6 by znamenalo dať súťažiacemu na starosť hodnotenie
slovenčiny jeho súperov, čo je confound zo §4.5 v novom kostýme.

---

## 5.2 Polovica A — porozumenie a uvažovanie

100 položiek, beh 2026-08-02, 0 neparsovateľných odpovedí zo 600.

| Model   | slovenčina | angličtina | **sk − en** | Čas       |
|---------|-----------:|-----------:|------------:|----------:|
| gemma3  | 0.930      | 0.950      | **−0.020**  | **6 min** |
| gemma4  | 0.940      | 0.970      | −0.030      | 80 min    |
| qwen3.6 | **0.950**  | 0.970      | **−0.020**  | 39 min    |

**Slovenčina nebrzdí ani jeden z týchto modelov.** Každá penalizácia sú dve až
tri položky zo sta. Všetky tri čítajú slovenčinu zhruba tak dobre ako angličtinu
a otvorená otázka §4.4 — či je jazyk skrytým handicapom — má odpoveď nie, pre
všetky tri.

**Model, ktorý RAGAS radí posledný, rozumie slovenčine najlepšie.** qwen3.6 je
posledná v [EVALUATION.md §3.9](EVALUATION.md) (`factual_correctness` 0.77–0.80)
a tu prvá. Odstupy 1–2 položky sú v šume, takže to nedokazuje lepšie porozumenie —
ale niečo vylučuje: **jej posledné miesto nie je spôsobené slabšou slovenčinou.**
Ostáva vysvetlenie zo §4.2 a §4.10.4 — píše dlhšie, rozvitejšie odpovede a
metriky merajúce zhodu s referenciou trestajú presne to.

**Rozlíšenie.** Pri 100 položkách je jedna položka jeden bod, takže rozdiely
medzi modelmi pod ~5 bodov sú nečitateľné. Pre otázku, na ktorú bola táto
polovica stavaná, to nevadí — každý model sa porovnáva *sám so sebou* v dvoch
jazykoch na identických položkách — ale znamená to, že slovenský stĺpec sa nemá
používať na zoradenie modelov. Celých 900 položiek by len na gemma4 stálo osem
hodín.

---

## 5.3 Polovica B — slovenčina, ktorú produkujú

18 promptov na model, 54 hodnotení rubrikou, všetky sparsované.

### Pravopisné kontroly (bez judge-a)

| Model   | české `ř ě ů` | odpovede bez `ô ľ ĺ ŕ ä` | medián diakritiky | medián dĺžky |
|---------|--------------:|-------------------------:|------------------:|-------------:|
| gemma3  | **0 / 18**    | 5 / 18                   | 0.107             | 362          |
| gemma4  | **0 / 18**    | 6 / 18                   | 0.112             | 272          |
| qwen3.6 | **0 / 18**    | 5 / 18                   | 0.109             | 419          |

### Rubrika, 1–5, hodnotil `claude-opus-5`

| Model   | gramatika | prirodzenosť | zadanie  | vypísaných chýb |
|---------|----------:|-------------:|---------:|----------------:|
| gemma3  | **4.28**  | 3.78         | 4.17     | 56              |
| gemma4  | 4.22      | **3.94**     | **4.67** | 33              |
| qwen3.6 | 4.17      | 3.83         | 4.39     | 49              |

**Gramatika ich neodlíši.** Rozptyl 0.11 na päťbodovej škále cez 18 promptov je
šum. Ani jeden model nemá v slovenčine výhodu nad ostatnými; náskok gemma4 je
v *plnení zadania* (4.67), čo je iná schopnosť.

**4.2 z 5 znamená kompetentná slovenčina so skutočnými chybami, nie bezchybná.**
Vzorka toho, čo judge zachytil — všetko overené v uložených odpovediach:

| Model   | napísané                | správne               | jav                |
|---------|-------------------------|-----------------------|--------------------|
| gemma3  | filozofi boli **múdry** | múdri                 | zhoda              |
| gemma3  | on **mu sa** odvďačil   | on **sa mu** odvďačil | poradie príkloniek |
| gemma4  | až ich bolo **dvojich** | dvaja                 | zhoda čísloviek    |
| gemma4  | počet **návštevov**     | návštev               | genitív plurálu    |
| qwen3.6 | **Této** zimné steny    | **Tieto**             | český tvar         |

Najslabšie prompty naprieč modelmi boli poradie príkloniek (3.33), zhoda
čísloviek, predložkové väzby a rytmické krátenie — teda javy, kvôli ktorým boli
tie prompty napísané.

### Nález, na ktorom záleží najviac

qwen3.6 napísala **„Této zimné steny"**. `této` je český tvar. **Pravopisná
kontrola ho nezachytila**, lebo neobsahuje `ř`, `ě` ani `ů` — kontrola vrátila
pre tú istú odpoveď prázdny zoznam českých znakov.

§4.4 mala pravdu, keď sa obávala prieniku češtiny, a takto to vyzerá: nie česky
vyzerajúca veta, ale jediné české funkčné slovo vnútri inak čistej slovenčiny.
Kontrola tried znakov nájde len české slová nesúce exkluzívne písmená; čokoľvek
napísané zo spoločnej abecedy prejde. **Objektívna kontrola je nutná, ale nie
postačujúca** — bez rubriky by bol tento prípad neviditeľný.

Stojí za zmienku, kde sa to stalo: v tej istej trojvetovej odpovedi qwen3.6
správne napísala `krásni` aj `múdri` — teda práve tie tvary rytmického krátenia,
na ktoré prompt cielil — a zlyhala na ukazovacom zámene. Stresové prompty chyby
vynesú na povrch; nevynesú nutne tie, ktoré si predpovedal.

---

## 5.4 Čo to dokazuje a čo nie

**Dokázané.** Slovenčina nie je handicapom ani pre jeden z tých troch, ani
v porozumení, ani v produkcii. Všetky tri píšu kompetentnú slovenčinu so
skutočnými chybami, v nerozoznateľnej miere. Nič z toho nebolo vidieť v žiadnej
RAGAS metrike, čo je téza §4.4 zopakovaná s číslami.

**Nedokázané.** Či je slovenčina jedného modelu lepšia než druhého — odstupy sú
v šume na oboch poloviciach. Belebele meria porozumenie krátkeho úryvku, nie
znalosť slovenských reálií či práva. Rubrika je názor jedného judge-a na 18
promptov, nie kalibrácia voči rodenému hovorcovi, ktorú §4.4 označuje za jedinú
skutočnú validáciu a ktorá ostáva nespravená. A test s odpoveďami po ~900 znakov
nehovorí nič o dlhej konverzácii.

**Cena.** ~2 h GPU celkovo (6 / 80 / 39 min na polovicu A plus generovanie) a ~$1
za hodnotenie. gemma4 minula trinásťnásobok času gemma3, aby skončila o jednu
položku pred ňou — rovnaký obchod, aký našla [EVALUATION.md §3.8](EVALUATION.md)
na RAGAS korpuse, zreprodukovaný na inej úlohe.

---

## 5.5 Ako to zopakovať

```bash
python3 sk-eval/fetch_belebele.py 100          # výrez datasetu, gitignorovaný
python3 sk-eval/run_belebele.py MODEL 100      # polovica A, na model
python3 sk-eval/run_fluency.py generate MODEL  # odpovede polovice B, na model
python3 sk-eval/run_fluency.py judge           # rubrika nad všetkým vygenerovaným
```

Obe polovice púšťaj pre jeden model, kým je rezidentný — každý má ~50 GB a Ollama
drží naraz jeden. Krok s judge-om potrebuje `ANTHROPIC_API_KEY` a stack zo
[SETUP.md](SETUP.md); všetko ostatné je lokálne.
