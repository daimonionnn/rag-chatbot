# Slovenský preklad dokumentácie

Preklad dokumentácie z koreňa repozitára. **Anglické originály sú zdroj pravdy** —
ak sa preklad a originál rozchádzajú, platí originál.

## Stav prekladov

| Dokument                                             | Preklad                        | Zdrojový commit |
|------------------------------------------------------|--------------------------------|-----------------|
| [`README.md`](../../README.md)                       | [README.md](README.md)         | `7f56dd2`       |
| [`SETUP.md`](../../SETUP.md)                         | [SETUP.md](SETUP.md)           | `7f56dd2`       |
| [`GUARDRAILS.md`](../../GUARDRAILS.md)               | [GUARDRAILS.md](GUARDRAILS.md) | `9e09e2a`       |
| [`EVALUATION.md`](../../EVALUATION.md)               | [EVALUATION.md](EVALUATION.md) | `4017d16`       |
| [`EVALUATION-LIMITS.md`](../../EVALUATION-LIMITS.md) | [EVALUATION-LIMITS.md](EVALUATION-LIMITS.md) | `4017d16` |
| [`BUGS.md`](../../BUGS.md)                           | [BUGS.md](BUGS.md)             | `1a8de5d` |

## Kontrola aktuálnosti

Preklady zastarávajú **potichu** — to je presne tá trieda problémov, ktorú
`BUGS.md` celý dokumentuje. Preto má každý preklad v hlavičke commit, z ktorého
vznikol, a je na to kontrola:

```bash
docs/sk-translation/check-freshness.sh
```

Skript pre každý preložený dokument porovná zaznamenaný commit s aktuálnym stavom
originálu a nahlási, ktoré preklady sú pozadu. Vypíše aj `git diff`, takže je
vidieť presne, čo treba dopreložiť.

## Konvencie prekladu

- **Technické termíny zostávajú po anglicky** — *retrieval*, *embedding*,
  *chunking*, *prompt*, *hook*, *container*, *rails*, *harness*. V slovenskom
  technickom texte je to bežnejšie a jednoznačnejšie než vymýšľať preklady.
- **Názvy súborov, príkazy, hodnoty configov a chybové hlásenia sa neprekladajú**
  vôbec — musia sa dať skopírovať a vyhľadať.
- **Čísla a namerané hodnoty sa nikdy neprepisujú.** Ak sa preklad a originál
  v čísle rozchádzajú, je to chyba prekladu.
- Odkazy medzi preloženými dokumentmi vedú v rámci tohto adresára; odkazy na kód
  a na originály vedú cez `../../`.
