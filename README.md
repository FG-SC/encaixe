# Encaixe — job matching with open rules

**Encaixe** ("fit", in Portuguese) is a two-sided job-matching MVP for the Brazilian market — candidates and recruiters — built around one promise: **the rules are public**. Anyone can see how the ranking decides, why a job or a candidate showed up, why something did not, and what would change the result. The UI is in Brazilian Portuguese; the code, docs and this README are in English.

> Portfolio project, local-first, free to run (local embeddings, optional free-tier LLM). All people in the demo are synthetic; all seed companies are fictional.

## Why

Applicant-tracking systems increasingly use AI in the first screening, and candidates rarely learn which rules counted, why they were filtered out, or what to improve. According to figures attributed to *Folha de S.Paulo* and Comscore, fewer than 1% of applicants on Gupy, a large Brazilian ATS, were hired in 2023 (reported figure; not independently verified by this project). On the other side, recruiters work with lists and rarely see which requirement is emptying their funnel; talent-market analytics are enterprise contracts.

Encaixe answers with five commitments, valid for both sides:

1. **The rule is public.** "Como o Encaixe decide" ([docs/RULES.md](docs/RULES.md)) is generated from the same config the ranking uses ([app/config.py](app/config.py)). There is no hidden rule; a test fails if the page and the config disagree.
2. **Every card explains itself.** "Por que estou vendo isto?" shows each criterion's raw value and position, each pillar's position and the sum; the positions shown **reconstruct the order of the list exactly** (tested), including ties, unknown values, the applicants-first group and the learned pillar.
3. **Nothing disappears silently.** Filtered jobs are listed with the reason and the threshold they did not pass ("elegíveis + filtradas = todas as vagas abertas" is a test).
4. **Every rejection has a reason.** Recruiters pick a structured reason (no free text); the candidate sees it, the objective gaps, and what would change it.
5. **Every gap becomes a path.** "With PyTorch, you would prove 5 of 5 must requirements and become a good fit for this job."

## How the ranking works

- **Hard filters first** (non-negotiables, each with its reason): arrangement, distance, country eligibility, salary below 70% of the candidate's minimum, seniority three or more levels apart, and *out of area* (no proven must requirement and no taxonomy domain in common). Learning never resurrects a filtered item.
- **No hand-picked weights.** Following the logic of Joel Greenblatt's "magic formula" (*The Little Book That Beats the Market*, 2005), each item is ranked on each criterion, positions are summed within two pillars — **Atende** (does the candidate meet what the job asks?) and **Interessa** (does the job offer what the candidate wants?) — and the list is ordered by the sum of pillar positions. Scale-free: cosines, kilometres and salaries all become comparable positions.
- **Evidence over keywords.** The requirements criterion is lexicographic: share of musts *proven* (used in a dated experience) → proven in the last 3 years → only *listed* → nice-to-haves. Fifty listed skills cannot beat five used recently (tested).
- **Unknowns stay in the middle** (median imputation), and the page says so: a job that discloses a good salary moves up, a bad one moves down, an undisclosed one stays in the middle.
- **An absolute "good fit" rule** (≥ 80% of musts proven, at most one seniority level apart) drives counts and counterfactuals, so "3rd in your list" and "not a good fit yet" never contradict each other.
- **Time is explicit — the technical thesis.** Profiles are versioned (relevant vs minor revisions); every event records which version was judged. The learned pillar (`feedback-v1`) weighs swipes by `0.5^(days/21) · 0.5^(relevant revisions since)`, using the item *as it was* when judged, so a candidate who evolved escapes an old rejection, and a job where an application did not advance comes back after a relevant revision.
- **Reciprocal and blind.** A match needs both sides; the recruiter sees a blind card (no name, contact, photo or age) until the match. Companies and schools are shown, but never ranked: there is no prestige score.
- **Exploration** draws every 10th card from the 20th–60th percentile band, labelled as drawn, with its propensity logged.

Alternatives (reciprocal rank fusion, Cormack et al., SIGIR 2009; a weighted baseline) are implemented and compared in the evaluation; the default changes only if the numbers say so.

## Evaluation (honest numbers)

From [docs/EVAL.md](docs/EVAL.md): 727 open jobs (659 real postings from Greenhouse, Lever and GitHub inside the sample scope, frozen in a local snapshot, plus 68 fictional ones), 100 synthetic candidates with simulated histories, local embeddings. People are simulated, so every number below measures the method against a stated synthetic oracle, not real hiring outcomes.

| | result |
|---|---|
| Replay (where liked jobs land among 727) | `feedback-v1` MRR 0.064 vs `static-v1` 0.046, Recall@20 0.30 vs 0.17. The replay's AUC is distorted by the logging policy (static comes out at 0.46, below random), which the unbiased check explains |
| Unbiased check against the oracle (all eligible jobs, no logging policy) | `static-v1` AUC 0.78, precision@10 0.58 against a 0.31 share of liked jobs; RRF 0.79 / 0.61; the weighted baseline reaches precision@10 0.81 on an oracle that is itself a weighted sum, which the report flags |
| Drift (preference switch on a known day) | learning helps before the switch (precision@10 0.66 vs 0.33), falls *further* right after it (0.20 vs 0.28: old likes point the wrong way) and ends the window above static (0.40 vs 0.28); without time decay it ends at 0.34 |
| Congestion | 24 distinct candidates fill 39 top-5 slots (≈33 expected at random); Gini of exposure 0.81 — measured, not optimized |
| Latency | p95 214 ms for 2,000 jobs, 57 ms for 300 candidates (target 500 ms) |
| Memory (`encaixe bench`) | server with the model loaded 471 MB (budget 700); embedding 1,000 jobs 541 MB; t-SNE 160 MB; drift 526 MB; ingestion 92 MB (budget 1 GB) |

## Stack

Python 3.12 · FastAPI · SQLModel/SQLite · Typer · numpy/scikit-learn · local embeddings: `paraphrase-multilingual-MiniLM-L12-v2` on ONNX Runtime with its sentencepiece vocabulary (no PyTorch) · optional Groq LLM (`openai/gpt-oss-20b`, strict structured outputs) · Vite + React + TypeScript · Zustand · Observable Plot · Leaflet + OpenStreetMap. Designed for a machine with ~3 GB of free RAM: one heavy process at a time (`tools/heavy.py`).

## Quickstart

```bash
cd encaixe
python -m venv .venv
python tools/heavy.py -- .venv/Scripts/python -m pip install -c constraints.txt -e ".[dev]"   # Linux/macOS: .venv/bin/python
python tools/heavy.py -- npm --prefix front ci
python tools/heavy.py -- npm --prefix front run build      # production build, served by FastAPI

.venv/Scripts/encaixe demo reset     # seed jobs + synthetic B side + 100 synthetic candidates with histories
.venv/Scripts/encaixe serve          # http://127.0.0.1:8000
```

The first run downloads the embedding model (~250 MB) into `var/models`; without it, Encaixe falls back to TF-IDF and says so in the dev panel. To demo on real postings, after the first `demo reset`: `encaixe ingest --all`, `encaixe snapshot save demo`, then `encaixe demo reset --snapshot demo` (the snapshot keeps the fictional seed jobs the demo story uses). Then follow the demo script in [docs/DEMO.md](docs/DEMO.md): Ana is rejected, learns why, evolves, and it becomes a match.

Useful commands, with the venv activated (`encaixe --help` lists them all; wrap batch commands in `python tools/heavy.py --` on a small machine):

| command | what it does |
|---|---|
| `encaixe seed` | load the 60 fictional jobs and the synthetic recruiters (offline mode) |
| `encaixe ingest --all` | fetch real jobs from the enabled sources (cron-friendly; heuristic extraction) |
| `encaixe sources` | which job sources are on, and why |
| `encaixe snapshot save NAME` / `load NAME` | freeze/restore the jobs so the demo and the replay are reproducible |
| `encaixe synth candidates --n 100 --seed 42` | synthetic candidates and their simulated histories |
| `encaixe eval all` | replay, unbiased oracle check, drift, congestion, latency → [docs/EVAL.md](docs/EVAL.md) |
| `encaixe bench` | peak RSS of five steps against the RAM budget |
| `encaixe rules export` | regenerate [docs/RULES.md](docs/RULES.md) from the config |
| `encaixe export --candidate ID` / `purge --candidate ID` | everything stored about a person / delete it (LGPD) |
| `encaixe clock advance --days N` | the demo's clock |

Tests: `python tools/heavy.py -- .venv/Scripts/python -m pytest` (offline, fake embeddings) and `npm --prefix front test`.

## Data, sources and privacy

- **Everything stays local**, in `var/` (database, model cache, HTTP cache, snapshots), which is never committed. Seed and test data are fictional.
- **What goes to the LLM**: nothing unless `GROQ_API_KEY` is set. With a key, a CV is sent only when the person ticks "Usar IA para ler meu CV" (off by default), once, at onboarding; recruiter-published jobs and market jobs entering someone's top 20 may be re-read in the background. The LLM never rewrites a saved profile; any failure falls back to the heuristic extractor, visibly.
- **Scope: a sample.** Ingestion keeps onsite/hybrid jobs in Santa Catarina and remote jobs open to people in Brazil; other postings are not stored, only counted per board, and the rules page states the rule.
- **Job sources.** Greenhouse and Lever public job-board APIs and GitHub issues of Brazilian job repositories, only through their documented endpoints, serially, at least 1 s apart, once a day per board. A terms check (2026-10-19) found public endpoints and no prohibition, but no explicit permission to aggregate and redisplay third-party postings; they first shipped disabled and were **turned on by the project owner's decision** (2026-10-20), which the rules page states. Every job links back to its source, contacts are stripped, and GitHub issue bodies are never redisplayed. Other boards are listed and off; We Work Remotely's terms forbid this use.
- **Recruiter-side aggregates** exclude candidates who chose to be invisible and render any count below 5 as "<5".
- AI in recruitment is classified as high-risk by the EU AI Act (Regulation (EU) 2024/1689, Annex III, point 4); in Brazil, the LGPD (Lei 13.709/2018, art. 20) gives people the right to request a review of automated decisions. Encaixe is a portfolio MVP, not a compliance product, but it is designed in that spirit.

## Prior art (the swipe is not new)

| | what it does | what Encaixe adds |
|---|---|---|
| Switch (2014) | two-sided swiping, mutual match, anonymous candidates | public rules, a reason for every rejection, a path to improve |
| Jobr (acquired by Monster, 2016) | job swiping, recruiter tools | the same transparency on both sides |
| Jobshift | swipe + AI that writes and sends applications | deciding well rather than applying in bulk |
| Jobright | 0–100 match score for candidates (US jobs) | the rule behind the score, published; the recruiter side |
| Gupy | Brazilian ATS with AI screening | an explanation at every step |
| Eightfold | career-trajectory matching, rediscovering past applicants (enterprise) | open and free; time handled explicitly and measured |
| LinkedIn Talent Insights, Lightcast | talent-market analytics (enterprise) | analytics inside the decision flow, for free |

Matching people and jobs is a *reciprocal* recommendation problem (Pizzato et al., "RECON: a reciprocal recommender for online dating", RecSys 2010): both sides must want the match, capacity is limited (one hire per job), behavioural data is scarce, people change over time, and mistakes are costly. Each of those differences became a rule here.

## Repository map

`app/` backend (config, extraction, taxonomy, geography, embeddings, ranking, events, explore, ingest, llm, synth, eval) · `front/` web app · `tests/` · `docs/` ([ARCHITECTURE](docs/ARCHITECTURE.md), [DECISIONS](docs/DECISIONS.md), [RULES](docs/RULES.md), [EVAL](docs/EVAL.md), [DEMO](docs/DEMO.md)) · [FUTURE.md](FUTURE.md) · [NOTICE](NOTICE) (GeoNames CC BY 4.0, Unicode CLDR, UN M49).
