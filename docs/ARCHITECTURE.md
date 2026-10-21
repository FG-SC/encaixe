# Encaixe — Architecture

Binding design contract for the MVP. It turns the product spec into modules, data shapes, algorithms and interfaces. When this document is silent, prefer the simplest choice that keeps the rules public and testable, and log it in `docs/DECISIONS.md`.

## 1. Principles

1. **Open rules.** Every number that affects filtering, ranking, exploration, privacy or LLM use lives in `app/config.py` (`RULES`). The rules page, `docs/RULES.md` and the front read it from there. No rule number is written by hand anywhere else (tests enforce it).
2. **Evidence over keywords.** A skill is *proven* only when it was used in a dated experience. Listing a skill never beats proving it.
3. **Time is explicit.** Profiles are versioned (`ProfileRevision`), jobs are versioned (`JobVersion`), every event records which versions were judged, and every timestamp comes from `app.clock.now()`.
4. **Nothing disappears silently.** Every excluded item carries machine-readable reasons; every rejected application carries a structured reason.
5. **Privacy by default.** Blind candidate cards until a match; invisible candidates are excluded from every recruiter-side aggregate; k-anonymity on aggregates; data stays local in `var/`.
6. **Light.** Backend steady state ≤ 700 MB RSS with the embedding model loaded; batch commands ≤ 1 GB peak in batches of 64 texts; never two heavy processes at once (`tools/heavy.py`).

## 2. Repository layout

```
encaixe/
├── app/
│   ├── config.py          # RULES (every rule/threshold/hyperparameter) + Settings (env)
│   ├── clock.py           # now() = real UTC time + offset_days (persisted in Setting)
│   ├── db.py              # engine, sessions, init_db(), SQLite pragmas, append-only triggers
│   ├── models.py          # SQLModel tables
│   ├── schemas.py         # canonical Pydantic types and API DTOs
│   ├── texts.py           # every pt-BR user-facing sentence template
│   ├── taxonomy/          # skills.yaml + matcher (aliases, parents, domains, languages, seniority)
│   ├── geo/               # cities.csv, countries.csv, location/eligibility/timezone parsing, haversine
│   ├── companies.py       # name normalization, get_or_create_company
│   ├── extraction/        # heuristic extractor for jobs and CVs, with provenance
│   ├── embeddings/        # backends (onnx | tfidf | fake), embed texts, in-memory index, 2D projection
│   ├── ranking/           # filters, criteria, positions, aggregators, good fit, counterfactuals,
│   │                      # feedback, exploration, deck assembly, explanations
│   ├── profiles/          # candidate profile service + revisions
│   ├── events/            # events, sessions, impressions, application status, matches, purge
│   ├── explore/           # Explorar aggregates (candidate + recruiter), k-anonymity helpers
│   ├── ingest/            # http client + cache, connectors, dedup, closing, snapshots
│   ├── llm/               # Groq client, strict schemas, rate limiter, cache, background worker, status
│   ├── rules/             # one Jinja2 template → docs/RULES.md and the in-app rules page
│   ├── synth/             # synthetic recruiters, candidates, histories, drift oracle
│   ├── eval/              # replay, unbiased oracle check, drift, congestion, aggregator comparison, report + SVG charts
│   ├── bench.py           # encaixe bench
│   ├── api/               # FastAPI app factory + routers; serves front/dist
│   ├── cli.py             # Typer app "encaixe"
│   └── seed/              # seed_jobs.json, recruiters.json, personas/
├── front/                 # Vite + React + TS; `npm run build` → front/dist (served by FastAPI)
├── tests/                 # pytest; offline; EMBEDDINGS=fake
├── tools/heavy.py         # runs a command while holding the one-heavy-process lock
├── docs/                  # ARCHITECTURE, DECISIONS, RULES (generated), EVAL (generated), DEMO
├── var/                   # gitignored: encaixe.db, models/, cache/, snapshots/, uploads/, eval/, heavy.lock
└── pyproject.toml  README.md  FUTURE.md  .env.example  .gitignore
```

## 3. Configuration (`app/config.py`)

`RULES` is a tree of frozen dataclasses. `rules_as_dict()` serializes it; `rules_hash()` is the first 12 hex chars of the sha256 of its canonical JSON. Every event stores `rules_hash`. Names below are binding.

| Section | Field = default | Meaning |
|---|---|---|
| `filters` | `comp_min_ratio = 0.70` | filtered when job comp_max < 70% of the candidate's comp_min (both known) |
| | `seniority_gap_exclude = 3` | filtered when the ladder distance is ≥ 3 |
| `criteria` | `atende = ("requirements","semantic","title","seniority")`, `interessa = ("salary","distance","timezone")` | pillars and display order |
| `precision` | `cosine=0.02, salary=0.05, distance_km=5.0, tz_hours=1.0, history=0.02` | values within the precision are ties |
| `requirements` | `recent_years=3, partial_credit=0.5` | recency window; parent/child credit |
| `good_fit` | `must_share=0.8, max_seniority_gap=1` | absolute "bom encaixe" rule |
| `aggregation` | `aggregator="rank_sum", rrf_k=60, weighted=…` | weighted baseline: Atende {requirements .45, semantic .25, title .15, seniority .15}; Interessa {salary, distance, timezone: 1/3 each}; pillars {atende .7, interessa .3}; with history {atende .6, interessa .25, historico .15} |
| | `tie_break = ("sum","atende","requirements","item_id")` | deterministic total order |
| `feedback` | `half_life_days=21, gamma=0.5, k_min=5, company_penalty=0.15` | history pillar |
| | `lambda_candidate = {role_area:1.0, none:0.5, company:0.0, salary:0.0, arrangement:0.0, seniority:0.0}` | λ per candidate reason |
| | `lambda_recruiter = {skills:1.0, none:0.5, seniority:0.0, salary:0.0, location:0.0, language:0.0}`, `ignored_recruiter = ("job_filled",)` | λ per recruiter reason; ignored reasons have no effect at all |
| `exploration` | `every=10, band_low_pct=20, band_high_pct=60, exclude_top=30` | exploration slots |
| `rankers` | `default="feedback-v1", available=("static-v1","feedback-v1")` | served ranker |
| `reasons` | `candidate=("role_area","company","salary","arrangement","seniority")`, `recruiter=("skills","seniority","salary","location","language","job_filled")` | enums (pt-BR labels in `texts.py`) |
| `events` | `impression_min_ms=500, session_idle_minutes=30, reason_chips_seconds=3` | front behaviour, served to the front |
| `revisions` | `relevant_skill_symdiff=3` | relevant revision threshold |
| `privacy` | `k_anon=5, candidate_default_visible=False, blind_hidden=("name","contact","photo","age")` | blind card + aggregates |
| `workday` | `start_hour=9, end_hour=18` | timezone overlap window |
| `seniority` | ladder `{1:"Estágio",2:"Júnior",3:"Pleno",4:"Sênior",5:"Staff",6:"Principal"}`; `years_fallback=((0,2,2),(2,5,3),(5,9,4),(9,13,5),(13,99,6))` | title rules first; years only as fallback |
| `currency` | `base="BRL"`, `rates_to_brl={…}`, `rates_as_of`, `period_to_month={hour:168, day:21, week:4.33, month:1, year:1/12}` | approximate FX, always flagged |
| `projection` | `method="tsne", knn_star=10, clusters=12, perplexity=30, random_state=42` | market map |
| `embeddings` | model id, `dim=384`, `max_tokens=128`, `batch_size=64`, `job_text_max_words=100`, `candidate_text_max_words=100`, `candidate_text_max_skills=20`, `candidate_text_recent_titles=3` | |
| `llm` | provider, model, `rpm/rpd/tpm/tpd` (from the Groq docs, with date), `onboarding_timeout_s=20`, `background_top_n=20`, prompt versions, `sends` (what is sent) | |
| `ingest` | per-source `enabled`, boards/repos, rate limits, `close_after_missed_runs=2`, `user_agent`, terms URLs | disabled sources are listed with `enabled=False` |

`Settings` (env, `.env` supported): `EMBEDDINGS` (onnx|tfidf|fake), `GROQ_API_KEY`, `LLM_MODEL`, `ENCAIXE_VAR_DIR` (default `./var`), `ENCAIXE_DB_URL`, `EMBED_THREADS`, `LOG_LEVEL`.

The front reads only `GET /api/rules/public`; it never hardcodes a rule number (UI-only constants such as the swipe pixel threshold are fine).

## 4. Data model (`app/models.py`)

SQLModel on SQLite (`var/encaixe.db`, WAL). JSON columns via `sa_column=Column(JSON)`. Embeddings are float32 bytes (`to_blob`/`from_blob`).

- `Company(id, name, name_normalized UNIQUE, aliases: list[str])` — identity only, no size or prestige score.
- `Recruiter(id, name, company_id, synthetic)`
- `Candidate(id, name, contact, headline, city_id, wants: Wants, skills_listed: list[str], languages: list[LanguageLevel], visible_to_recruiters, llm_consent, synthetic, current_revision_id, created_at)`
- `Experience(id, candidate_id, company_id, role, seniority, start, end, skills_used: list[str], responsibilities, outcomes: list[str], provenance)` — a promotion is two consecutive experiences at the same `company_id`.
- `Education(id, candidate_id, degree, field, institution, start, end)`
- `ProfileRevision(id, candidate_id, ts, hash, kind: relevant|minor, snapshot: CandidateProfile JSON, seniority, embedding, title_embedding)` — append-only.
- `Job(id, origin: market|platform, owner_recruiter_id, source, source_id, url, company_id, title, description_text, location_text, city_id, country, requires: Requires, offers: Offers, eligibility: Eligibility, job_tz, domains: list[str], provenance, labels, version, extraction_method, content_hash, first_seen, last_seen, status: open|closed|paused, missed_runs, x, y, cluster)`
- `JobVersion(id, job_id, version, ts, snapshot, embedding, title_embedding)` — the job's current vectors are its latest `JobVersion`; `version` increases only when the posting content changes (an LLM re-extraction updates the vectors of the same version).
- `InteractionEvent` — exactly the spec fields plus `rules_hash`: `id, client_event_id UNIQUE, actor_type, actor_id, item_type, item_id, context_job_id, type, reason, ts, session_id, actor_revision_id, item_revision_id, item_version, ranker_version, slot, propensity, rank_position, rank_sum, rank_detail, rules_hash`. Append-only through SQLite triggers (`BEFORE UPDATE/DELETE → RAISE(ABORT)`); the only exception is the LGPD purge in `app.events.purge`, which lifts the delete trigger inside its own transaction.
- `Match(id, candidate_id, job_id, recruiter_id, ts)`, unique on `(candidate_id, job_id)`.
- `LlmCache(key, task, model, prompt_version, output_json, created_at)`; key = sha256(task + model + prompt_version + content).
- `IngestRun(id, source, board, ts, n_seen, n_new, n_updated, n_closed, error)`
- `Setting(key, value JSON)` — clock offset, ranker/aggregator override from the dev panel, LLM counters, index versions.
- `City` is static (`app/geo/cities.csv`, loaded in memory); `city_id` is its slug (e.g. `florianopolis-sc-br`).

## 5. Canonical schemas (`app/schemas.py`)

```
Provenance   { source_span: str|None, stated: bool, confidence: float, method: "heuristic"|"llm"|"label"|"user" }
LanguageLevel{ language: str, level: "basic"|"intermediate"|"advanced"|"fluent"|"native"|None }
Requires     { skills_must: [skill_id], skills_nice: [skill_id], seniority: int|None, years_min: float|None, languages: [LanguageLevel] }
Offers       { arrangement: "remote"|"hybrid"|"onsite"|None, comp_min, comp_max: float|None, currency, period: "hour"|"day"|"week"|"month"|"year"|None, regime: "clt"|"pj"|"internship"|"contractor"|"other"|None }
Eligibility  { countries: [iso2] }                     # empty = no restriction
Wants        { comp_min, currency="BRL", period="month", arrangements: [..], max_distance_km, languages: [..] }
ExperienceIn { company, role, seniority, start, end, skills_used, responsibilities, outcomes }
EducationIn  { degree, field, institution, start, end }
CandidateProfile { name, contact, headline, city_id, experiences, education, skills_listed, languages, wants }
CandidateDraft   = CandidateProfile + provenance{path: Provenance} + warnings + method + llm_status
JobDraft         = { title, company, description_text, location_text, city_id, country, requires, offers, eligibility, job_tz, provenance, warnings, method }
```
Provenance keys are field paths (`requires.skills_must.pytorch`, `offers.comp_max`, `experiences.0.start`). Dates have month precision (day = 1); "atual/present" → `end = None`.

## 6. Taxonomy, geography, companies

- `taxonomy.load()` → `Taxonomy` with `find_skills(text)` (word-boundary regex; lowercase aliases match case-insensitively, `case_sensitive_aliases` match exactly), `parent`, `children`, `related(a, b)` (direct parent/child), `domain`, `domains` (domain + `also_domains`), `label`, `find_languages(text)`, `seniority_from_title(title)`.
- `geo`: `get_city`, `find_city(text)` (handles "Cidade, UF", "City, CC" and aliases; bare `BR`/`US`/`PT` are never places), `find_eligibility(text)` ("US only", "authorized to work in the United States", "residentes no Brasil", regions such as LATAM expand to country lists), `parse_tz(text)` (case-sensitive abbreviations ET/EST/EDT/CT/MT/PT/PST/PDT/BRT and UTC±N; `PT` only uppercase and in timezone context), `haversine_km`, `tz_overlap_hours(tz_a, tz_b, on_date)`.
- `companies.normalize(name)`: lowercase, no accents, no punctuation, no legal suffixes (inc, llc, ltd, s.a., sa, ltda, me, eireli, …). `get_or_create_company` matches exactly on the normalized name and keeps aliases. "Google LLC" and "google" are the same company.

## 7. Heuristic extraction (`app/extraction/`)

**Job:** HTML → text → remove institutional blocks (about us, benefits, EEO/diversity, privacy) → sections anchored at line start (requirements / requisitos / qualificações; nice to have / diferenciais / desejáveis; responsibilities / responsabilidades) → skills per section (no sections: every skill is `must`, marked inferred) → seniority (title, then text, then `years_min`) → years ("3+ years", "mínimo de 2 anos") → languages → arrangement → city → eligibility → job timezone → salary → regime (CLT/PJ/estágio). Each value carries `Provenance`.

**Salary:** a currency marker plus number(s) in salary context (salário, salary, compensation, remuneração, bolsa, pay range, "R$ X – Y") with a period; reject funding and scale contexts (raised, funding, series, valuation, customers, users, ARR, revenue, captação, investimento, usuários, clientes).

**CV:** sections (Resumo, Experiência, Formação, Skills/Competências, Idiomas) → experiences (role, company, ranges such as "jan/2022 – atual", "03/2020 - 05/2022", "2019–2021", "Mar 2020 – Present") → `skills_used` per experience block → `skills_listed` from the skills section → education → languages → headline → city. Years of experience are the union of the intervals: overlaps are not counted twice.

Each trap from the spec has a dedicated test (`tests/test_traps.py::test_trap_1_…` … `test_trap_9_…`).

## 8. Embeddings (`app/embeddings/`)

- `get_embedder()`: `EMBEDDINGS=onnx` (default; `fastembed` is an alias) | `tfidf` | `fake`. When the model cannot load, it falls back to tfidf and logs `WARNING embeddings fallback to tfidf: <reason>`; the reason shows in the dev panel.
- `onnx`: the quantized ONNX export of `paraphrase-multilingual-MiniLM-L12-v2` on ONNX Runtime (CPU arena off, `threads` from settings), tokenized with the model's sentencepiece vocabulary (XLM-R ids: sentencepiece id + 1, `<s> … </s>`, 128 tokens), mean pooling. Both files are pinned by commit and cached in `var/models`. It reproduces fastembed 0.8.1 exactly (DECISIONS #35) with 211 MB less RAM.
- `embed(texts) -> float32 (n, d)`, L2-normalized, processed in batches of `RULES.embeddings.batch_size`.
- tfidf: TfidfVectorizer(1–2-grams) + TruncatedSVD, fitted on the current corpus and persisted in `var/models/tfidf.joblib`. fake: deterministic hashed bag of words (tests only).
- Texts (≤ ~100 words, no personal data): job = title + must + nice skills + first sentences of the role summary (no institutional text); candidate = headline + titles of the 3 most recent experiences + up to 20 skills (proven before listed) + description of the most recent experience. Title vectors: job title; candidate = mean of experience-title vectors (headline when there are no experiences). A test asserts the embedder never receives longer strings.
- `JobIndex` / `CandidateIndex`: in-memory numpy matrices with the vectors and the structured arrays the ranking needs, rebuilt when `Setting["jobs_version"]` / `["candidates_version"]` changes.
- Projection (`encaixe project`, run after ingest/snapshot/seed): PCA(50) → t-SNE(2, init="pca", random_state=42; PCA-2 when n < 50); KMeans(`clusters`) on the vectors; each cluster is labelled by the majority taxonomy domain of its jobs plus its top skills. The candidate's star = similarity-weighted mean of the (x, y) of the `knn_star` most similar open jobs (an explainable rule shown in the UI).

## 9. Ranking engine (`app/ranking/`)

Entry points: `rank_for_candidate(session, candidate_id, ranker=None, aggregator=None) -> RankResult` and `rank_for_job(session, job_id, ranker=None, aggregator=None) -> RankResult`. Vectorized with numpy; p95 < 500 ms for 2,000 jobs or 300 candidates.

```
RankResult  { items: [RankedItem], filtered: [FilteredItem], meta: {n_total, n_eligible, n_filtered, ranker_version, aggregator, rules_hash} }
RankedItem  { item_id, order, final_sum, pillars{name: {sum, position}}, criteria{name: {raw, display, position, unknown, not_applicable, flags}},
              good_fit{is_good_fit, must_credit, must_total, seniority_gap, evaluable}, applicant (B side), history_top[] }
FilteredItem{ item_id, reasons: [{code, value, threshold, adjust}] }
```

### 9.1 Hard filters (pair-level, same code for both sides; every failing filter is recorded)
1. `closed` (job not open, C side) / `not_visible` (candidate not visible, B side).
2. `arrangement_not_accepted`: the job's arrangement is not among the candidate's accepted arrangements.
3. `beyond_distance`: onsite, hybrid or unknown-arrangement job (a job that does not say it is remote counts as onsite) whose city is farther than `max_distance_km` (haversine between cities); with no known city, a non-remote job whose country differs from the candidate's. Unknown city in the candidate's own country → not filtered, flagged.
4. `country_eligibility`: the job lists countries and the candidate's country is not among them.
5. `salary_below_min`: converted job comp_max (comp_min when it is the only value) < `comp_min_ratio` × candidate comp_min, both known.
6. `seniority_gap`: |job level − candidate level| ≥ `seniority_gap_exclude`, both known.
7. `out_of_area`: the candidate proves none of the job's must requirements (zero credit, half credits count as evidence) **and** shares no domain with the job. Job domains = majority domain(s) of its must + nice skills. Candidate domains = domains (incl. `also_domains`) of the skills they prove; with no proven skills, the listed ones. A job with no recognized skills is never out of area (flagged).

### 9.2 Criteria (raw values)
- `requirements`: lexicographic key (must_proven, must_recent, must_listed, nice_proven), each a share in [0,1]. Credits per must: 1 if proven; `partial_credit` if a direct parent/child is proven; recent = same, restricted to experiences overlapping the last `recent_years`; listed = listed but not proven (partial for a listed parent/child). Required languages are musts: proven when the candidate declares the language at the required level or above. No musts → unknown.
- `semantic`: cosine(job vector, candidate vector) — current versions.
- `title`: cosine(job title vector, candidate title vector).
- `seniority`: |job level − candidate level| (lower is better); unknown when either side is unknown.
- `salary`: slack = (job comp_max in the candidate's currency/period − candidate comp_min) / candidate comp_min; FX conversion flagged `câmbio aproximado`; an undisclosed salary counts as slack `RULES.criteria.salary_unknown_slack` = 0 (exactly the minimum, flagged "salário não informado", DECISIONS #39); unknown (median) only when the candidate declared no minimum.
- `distance`: 0 for an accepted remote job or the same city; otherwise km; unknown when a city is missing.
- `timezone`: only remote jobs: overlap hours of the 09–18 workday between the candidate's city timezone and the job's timezone; non-remote jobs are `not_applicable` (neutral, like unknown); remote jobs without timezone information are unknown.

### 9.3 Positions, pillars, order
- `positions(values, better, precision)`: unknown and not-applicable values are imputed with the **median of the known values** (tuples: the median element in lexicographic order) and ranked with everyone else. Then sort best-first and group ties: a group starts at a value v0 and takes the following values while |v − v0| ≤ precision (exact equality without precision); each member gets the group's mean position. Effect (stated on the rules page): a job with a good disclosed salary moves up, a bad one moves down, an undisclosed one stays in the middle.
- Pillar sum = Σ of its criteria positions; pillar position = `positions(pillar sum, min)` with exact ties.
- `rank_sum`: final sum = Σ pillar positions; order by `tie_break` = (final sum ↑, Atende position ↑, Requirements position ↑, item id ↑).
- `rrf`: pillar score = Σ 1/(k + criterion position); pillar position = rank of the score; final score = Σ 1/(k + pillar position), higher first; same tie-break.
- `weighted` (baseline only): min–max normalize each criterion within the list (reverse "lower is better"; unknown = 0.5; constant = 0.5); requirements scalar = k1 + k2/10 + k3/100 + k4/1000 before normalization; weighted sums with the configured weights; higher first.
- `static-v1` = Atende + Interessa. `feedback-v1` adds the Historico pillar when the actor has ≥ `k_min` judgments; otherwise it equals static-v1.
- B side: one ranking over all eligible candidates, then a stable partition: applicants first (badge "interessado(a)"), then the rest.

### 9.4 Good fit (absolute)
Passes the filters, must credit / must total ≥ `must_share`, seniority gap ≤ `max_seniority_gap` (unknown job level counts as no gap, flagged). A job with no must requirements is not evaluable and never counts as a good fit.

### 9.5 Counterfactuals and unlock analysis
- Per C-side card that is not a good fit: the smallest change that makes it one. Skills: add missing musts, simulated as used in a recent experience, greedily (zero-credit skills first, ties broken by market unlock count) until the share reaches `must_share`. Preferences: when only a preference filter blocks the job, the preference change that lifts it (accept hybrid, raise `max_distance_km` to X, lower comp_min to Y). A seniority gap > `max_seniority_gap` is reported as "no small change". The message always speaks of "bom encaixe", never positions.
- Unlock (Raio-X top 3, Explorar top 10): for every skill the candidate does not prove, the number of open jobs of the candidate's area (not out of area today, DECISIONS #41) that become good fits when the skill is added as recently used (filters recomputed). Vectorized over skills × jobs.

### 9.6 Feedback (`feedback-v1`)
- Judgments of the actor (candidate; or recruiter within `context_job_id`): likes = `swipe_right`, dislikes = `swipe_left`; recruiter reasons in `ignored_recruiter` are dropped entirely.
- `w(e) = 0.5^(Δt_days / half_life_days) · gamma^(n_rev(e))`; `n_rev` = relevant revisions since the event — of the candidate actor (C side) or of the judged candidate (B side).
- `fb(i) = [Σ_likes w·sim − Σ_dislikes λ(reason)·w·sim] / Σ_all w`, where `sim` uses the item's vector **at event time** (job version / candidate revision recorded on the event) against the current vector of item i.
- C side: `historico(i) = fb(i) − Σ_company dislikes company_penalty · w(e)` for jobs of the disliked company. Positions with precision `history`.
- The explanation lists the top contributing past items ("parecida com *Analista de BI*, que você curtiu").

### 9.7 Decks, exploration, reappearance
- Deck = ranked eligible items minus already-judged items, page of 20. Reappearance exceptions: (B) a rejected candidate with a relevant revision after the rejection → badge "perfil atualizado desde sua última avaliação"; (C) a platform job where the application did not advance, after a relevant revision of the candidate → "seu perfil mudou desde a recusa"; (C) a job the candidate rejected whose version changed → "vaga atualizada".
- Exploration: every `every`-th card of a page is drawn uniformly from the items between the `band_low_pct` and `band_high_pct` percentiles of the current list, excluding the top `exclude_top` and anything already shown to the actor (any impression). Empty band → no draw. `slot="explore"`, `propensity = 1/|band|`; ranked cards have `propensity=1`. RNG seeded by (actor, session, card index) for reproducibility. Filters run before everything: feedback never resurrects a filtered item.
- Each card carries `rank_meta` (position, sums, pillar and criterion positions, slot, propensity, ranker_version, rules_hash); the front echoes it on events.

## 10. Events, sessions, status, matches, revisions

- `POST /api/events` accepts one event or a batch. A known `client_event_id` returns the original event (`created=false`). The server fills `ts`, revisions/versions, `rules_hash`.
- Impressions: the front records a card visible for ≥ `impression_min_ms`; the server deduplicates per `(actor, item, session_id, ranker_version)`. A swipe without a prior impression in that session inserts the impression first (with a derived `client_event_id`).
- Sessions: UUID in `localStorage`, renewed after `session_idle_minutes` without activity; reloads keep the session.
- Reasons: candidate `swipe_left` → optional reason from `reasons.candidate`. Recruiter `swipe_left` on an **applicant** → a reason from `reasons.recruiter` is required (422 otherwise); on non-applicants it is optional. No free text anywhere.
- Application status (platform jobs), derived only from events: latest candidate `swipe_right` = application time; after it: match → `encaixe`; recruiter `swipe_left` → `não avançou` (with reason); recruiter impression → `vista` (date); otherwise `enviada`. A new application after a rejection reopens it as `enviada`.
- Match: created when the latest candidate judgment on the job and the latest recruiter judgment on the candidate (in that job) are both right, in any order. Contact is released only for matched pairs.
- Revisions: saving a profile builds the canonical snapshot and its hash; identical hash → no revision; `relevant` when an experience or education entry was added, the seniority changed, or the symmetric difference of skill sets ≥ `relevant_skill_symdiff`; otherwise `minor`. The LLM never rewrites a saved profile.

## 11. Open rules

- One Jinja2 template (`app/rules/rules.md.j2`) renders `docs/RULES.md` (`encaixe rules export`) and the in-app page (`GET /api/rules` → markdown, html, rules JSON, hash). Content: filters with thresholds; pillars and criteria; lexicographic requirements; ties and unknown values (including the salary side effect); aggregator in use; good fit; feedback (half-life, revision discount, effect of each reason); exploration rate and that likes from drawn cards are used too; sessions; what recruiters see and don't see; what is sent to the LLM. It ends with a worked example computed live by the ranking engine on a fixed tiny example, so numbers always match the config. Snapshot test: changing a config value changes both outputs.
- "Por que estou vendo isto?" lists, for each criterion, the raw value and the position ("Requisitos: 4 de 5 obrigatórios comprovados, 2ª de 48"), the pillar positions, the sum, the history items, the slot and the flags, plus: "a posição compara esta vaga com as outras da sua lista; bom encaixe é uma régua fixa". Positions appear only there, never on the card face. Test: re-sorting the items using only the displayed numbers and the published tie-break reproduces the deck order exactly (ties, unknowns, applicants group, company penalty).
- "Vagas que não te mostramos": grouped by reason (fixed order), each job with value vs threshold, each group with a shortcut to adjust the preference behind it. Test: eligible + filtered = open jobs.
- Rejection feedback: the company's reason, the objective gaps (missing musts, seniority gap, salary outside range), the counterfactual; when the reason does not match the data, say so honestly. Candidates see company and job, never the recruiter's name.
- All sentences live in `app/texts.py` (pt-BR, direct, respectful, always with a next step; "não avançou", never "reprovado").

## 12. Privacy

- Blind card until match: no name, contact, photo or age. Company and institution names stay visible (owner's decision; hiding them is a `blind_hidden` switch, shown on the rules page). Internal promotions show as "promoção interna".
- Real candidates start invisible; the toggle reads "visível para recrutadores, anônimo até o encaixe". Invisible candidates are excluded from every recruiter-side aggregate.
- k-anonymity: any aggregate count < `k_anon` renders as "<5"; map cells with fewer than `k_anon` candidates are not shown.
- `encaixe export --candidate <id>` / `GET /api/candidates/{id}/export`: everything stored about the person, events included. `encaixe purge --candidate <id>` / `DELETE /api/candidates/{id}`: candidate, revisions, events where they are actor or item, matches, CV LLM cache.

## 13. Explorar

**Candidate:** market map (t-SNE points coloured by cluster/domain, the candidate's star, good fits highlighted); geographic map (Leaflet circle markers per city with eligible / good-fit / filtered counts, plus a remote counter; points without background when offline); "qual skill destrava mais vagas" (top 10 bars with example jobs); salary distribution of good fits vs the candidate's minimum (FX flagged); revealed preferences from left-swipe reasons (salary, arrangement, seniority) compared with declared preferences; profile timeline (revisions and good-fit counts per revision).

**Recruiter (per job):** funnel (visible → pass filters → good fit → applied → seen → advanced/not advanced → matches); per-requirement funnel and the bottleneck ("qual requisito está matando o funil": the must whose removal adds the most good fits); candidate pool map (projected candidates on a grid, cells < k hidden) and candidates by city (cells < k hidden); market benchmark (similar market jobs, salary ranges, arrangements); aggregated candidate left-swipe reasons on the job (k-anonymous); congestion (how many of this job's top-5 candidates are also in the top-5 of other platform jobs). Every aggregate excludes invisible candidates and applies k-anonymity.

## 14. Ingestion and snapshots

- Sources enabled: Greenhouse job boards, Lever postings, GitHub issues of Brazilian job repositories (the terms check found no explicit permission; the owner turned them on, DECISIONS #24). Others are listed disabled, without connectors; a disabled source runs only with `--accept-terms`.
- HTTP: identifiable User-Agent, per-source rate limits from config, on-disk cache (`var/cache/http`, ETag/Last-Modified), `--record` / `--offline` modes; `encaixe bench` replays recorded responses.
- Scope (`RULES.scope`, `app/ingest/scope.py`, DECISIONS #38): only onsite/hybrid postings in the region (Santa Catarina) and remote postings open to Brazil are stored; the rest is counted per board in the `ingest_out_of_scope` setting and in the run report. A stored job that falls out of scope closes at once.
- Pipeline: raw posting → heuristic extraction → scope → upsert by `(source, source_id)`; cross-source dedup by normalized company + normalized title + city; `last_seen` update; `IngestRun` per (source, board); a job missing from 2 consecutive runs of its source is closed. GitHub labels become `stated` fields (`method="label"`); issue bodies are stored without contact data (e-mails, phones) — the card links to the issue.
- Every job shows its origin with a link ("via Greenhouse — <empresa>", "via backend-br/vagas").
- `encaixe ingest --all` (cron-friendly, heuristic only). `encaixe snapshot save|load <name>` stores jobs (with provenance/method), companies and the LLM cache entries they used in `var/snapshots/`; loading recomputes vectors and the projection.

## 15. LLM (`app/llm/`)

- Enabled only with `GROQ_API_KEY`. Strict structured outputs (`json_schema`, `strict: true`) through `ChatGroq.with_structured_output(..., method="json_schema", strict=True)` when supported by the pinned langchain-groq, otherwise the OpenAI-compatible HTTP endpoint.
- `llm/schemas.py`: every property required, optional = union with null, `additionalProperties: false` everywhere; an offline test checks the generated schemas. Responses are re-validated with Pydantic; any failure falls back to the heuristic with the reason logged.
- Client-side token buckets (requests and tokens per minute) and daily counters; 429 honours `retry-after` with backoff. Every call goes through `LlmCache`.
- Uses: CV extraction at onboarding (only with `llm_consent`, synchronous, one call, 20 s timeout, falls back with a visible notice); platform job extraction; background upgrade of market jobs entering someone's top 20 (asyncio worker; updates the job and its provenance `method`). Outside onboarding the LLM never blocks a request.
- Dev panel: on / off / error (with reason), model, requests today, cache hits, queue size.

## 16. Synthetic data

- `encaixe synth recruiters`: 5 fictional companies with one recruiter each and 1–3 platform jobs; Lumen Dados / Carla has no preloaded job (her "ML Engineer Jr" text is `app/seed/personas/lumen_ml_engineer_jr.txt`).
- `encaixe synth candidates --n 100 --seed 42`: personas with dated experiences, education, taxonomy-consistent skills, seniority, cities weighted towards SC, preferences, visible; ~10% get a relevant revision mid-history; plus swipe histories (candidate and recruiter judgments over simulated days, driven by a hidden utility) so replay has data.
- Ana is not generated: `app/seed/personas/ana.txt`.

## 17. Evaluation (`encaixe eval …` → `docs/EVAL.md` + `docs/eval/*.svg`)

- **Replay:** events in chronological order; for each judgment, rebuild the state at that time (open jobs, actor revision, only earlier events), rank with each variant and record the rank of the judged item. Metrics: MRR and Recall@{5,10,20} of liked items, AUC likes vs dislikes, NDCG@10. Variants: static-v1, feedback-v1, feedback-v1 without time decay, without revision discount; aggregators rank_sum / rrf / weighted.
- **Drift:** simulated users with a known oracle utility; on a known day a share of users changes preference (with and without a relevant revision). Daily decks from each variant, swipes from the oracle with noise. Metrics per day: oracle precision@10 and NDCG@10; recovery time after the drift.
- **Congestion:** concentration of recruiter-side exposure (distinct candidates across all platform top-5 lists, Gini of exposure) per variant — measured, not optimized.
- **Latency:** p95 of ranking for 2,000 jobs / 300 candidates.
- The report states seeds, snapshot, rules hash and the honest outcome, including when learning does not beat the static ranking. The default aggregator changes only if the numbers say so.

## 18. Bench (`encaixe bench`)

Five steps, each in a fresh subprocess with a psutil sampling thread for peak RSS: server start + warm-up (model loaded, one deck ranked), embedding 1,000 jobs, 2D projection, `eval drift`, `ingest --all` against recorded responses with the LLM off. Prints a table against the budget and writes `var/eval/bench.json`.

## 19. HTTP API (`/api`)

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /rules`, `GET /rules/public` | rules page (markdown, html, JSON, hash); front-facing rule values and pt-BR labels |
| `GET /meta/skills`, `GET /meta/cities` | taxonomy and cities for editors |
| `POST /candidates/parse` | CV text or PDF (+ `llm_consent`) → `CandidateDraft` |
| `POST /candidates`, `GET /candidates`, `GET /candidates/{id}` | create from the reviewed draft (first revision), list for the local profile picker, read |
| `PUT /candidates/{id}/profile`, `PATCH /candidates/{id}/settings` | new revision (returns kind); visibility / LLM consent |
| `GET /candidates/{id}/xray` | Raio-X data (understood profile, star, good-fit count, top-3 unlock skills, share-card data without personal data) |
| `GET /candidates/{id}/deck`, `GET /candidates/{id}/filtered` | job deck (cards with rank_meta, explanation, counterfactual, badges, filtered count); filtered list grouped by reason |
| `GET /candidates/{id}/jobs/{job_id}` | job detail with explanation (direct actions use `slot=direct`) |
| `GET /candidates/{id}/applications`, `GET /candidates/{id}/saved` | applications with status timeline and rejection feedback; saved market jobs |
| `GET /candidates/{id}/explore`, `GET /candidates/{id}/export`, `DELETE /candidates/{id}` | Explorar data; export; purge |
| `GET /recruiters`, `POST /recruiters` | local recruiter profiles |
| `POST /jobs/parse`, `POST /recruiters/{rid}/jobs`, `GET /recruiters/{rid}/jobs`, `PATCH /jobs/{id}`, `GET /jobs/{id}` | publish platform jobs (review step), list, pause/close, public detail with source attribution |
| `GET /recruiters/{rid}/jobs/{jid}/deck`, `GET /recruiters/{rid}/jobs/{jid}/candidates/{cid}` | blind candidate deck; blind (or, after a match, full) profile + explanation |
| `GET /recruiters/{rid}/jobs/{jid}/funnel`, `GET /recruiters/{rid}/jobs/{jid}/explore`, `GET /recruiters/{rid}/matches` | funnel, Explorar, matches with contact |
| `POST /events` | idempotent events; returns created flag and any new match |
| `GET /market/map`, `GET /market/stats` | projection points and clusters; per-source counts and last ingest runs |
| `GET /dev/status`, `POST /dev/clock`, `POST /dev/ranker`, `POST /dev/demo/reset` | dev panel |

FastAPI serves `front/dist` at `/` with SPA fallback.

## 20. Front (`front/`)

- Navigation by state (role + tab), no router. Zustand stores: `app` (role, tab, current candidate/recruiter/job), `rules` (from `/api/rules/public`), `session` (session id with idle renewal), `outbox` (events with `client_event_id` generated once per card view; StrictMode-safe; idempotent retries), `deck`.
- Candidate: Onboarding (paste text or PDF, LLM and visibility toggles, review with "declarado" × "inferido" chips, editable experiences, education for review, preferences) → Raio-X (understood profile, market map with the star, good-fit count, top-3 unlock skills, 4:5 share card without name/contact/current company, signed "feito no Encaixe — vagas com regras abertas") → Deck (swipe with Pointer Events + requestAnimationFrame, keyboard ←/→, reason chips for the configured seconds, "Por que estou vendo isto?", counterfactual, filtered counter → list) → Candidaturas → Explorar → Perfil (edit → revision kind shown, visibility, export, delete).
- Recruiter: Vagas (publish by pasting text → review → notice "quem se candidatou verá o motivo da recusa e o que faltou") → Deck per job (blind cards, applicants first, mandatory reason for applicants) → Funil → Explorar → Encaixes.
- Shared: header (role switch, profile picker/creator, "Como o Encaixe decide"), rules page, dev panel, "É um encaixe!" (two puzzle pieces snapping together; `prefers-reduced-motion` disables motion).
- Identity tokens as CSS variables (primary `#0E7C66`, accent `#F59E0B`, text `#111827`, background `#FAFAF7`, success `#16A34A`, alert `#DC2626`), Inter via `@fontsource`, AA contrast, keyboard navigation, `aria-label`s, mobile-first.
- Charts: Observable Plot rendered in `useEffect` into a ref. Maps: Leaflet with OSM raster tiles and attribution; offline → points without tiles.
- Vitest covers deck logic, outbox idempotency under double effects, session renewal and swipe thresholds.

## 21. Demo story ("recusada, soube por quê, evoluiu, deu encaixe")

1. `encaixe demo reset` (snapshot or seed jobs + synthetic B side + 100 synthetic candidates, vectors and projection).
2. Ana pastes her CV → review → Raio-X. "Sales Manager" appears under "Vagas que não te mostramos" as `fora da área`.
3. Carla (Lumen Dados) publishes "ML Engineer Jr" by pasting its text, and sees the transparency notice.
4. Ana finds the job in her deck and applies (swipe right) → status `enviada`.
5. Carla's deck shows Ana's blind card first ("interessado(a)"); she checks "Por que estou vendo isto?" and declines with reason `skills`.
6. Ana's Candidaturas: `não avançou`, reason `skills`, gaps PyTorch and deep learning, counterfactual to a good fit.
7. Dev panel advances the clock; Ana adds a dated experience using PyTorch and deep learning → relevant revision.
8. The job returns to Ana's deck with "seu perfil mudou desde a recusa"; she applies again (`enviada`).
9. Ana returns to Carla's deck with "perfil atualizado desde sua última avaliação", now 5 of 5 musts; Carla swipes right → "É um encaixe!" on both sides; contact released.

`tests/test_demo_story.py` runs this story through the API; `docs/DEMO.md` is the live script.
