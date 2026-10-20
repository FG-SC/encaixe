# Decisions

Choices made where the product spec was silent or open to interpretation, and every deviation from it. Each one is also reflected in `app/config.py` and, when it affects users, on the rules page.

| # | Decision | Why |
|---|---|---|
| 1 | Unknown and not-applicable criterion values are imputed with the median of the known values, then ranked with everyone else. | The spec says an unknown value gets the median position and "stays in the middle"; imputing the median value does exactly that and keeps good disclosed salaries above and bad ones below. |
| 2 | Tie-break chain: final sum → Atende position → Requirements position → item id. | The spec gives the first two steps. Requirements next keeps evidence first (and makes the keyword-stuffing guarantee hold in symmetric cases); the id makes the order total and reproducible. |
| 3 | The timezone criterion is "not applicable" (neutral) for non-remote jobs. | The spec defines it only for remote jobs. |
| 4 | The modality filter has two reasons: modality not accepted, and onsite/hybrid beyond `max_distance_km`. | Each has a different adjustment shortcut in "Vagas que não te mostramos". |
| 5 | For the out-of-area filter, a candidate without proven skills uses the domains of their listed skills. | Otherwise every job would be out of area for someone with no dated experience yet. |
| 6 | A job without recognized must requirements is "not evaluable" and never counts as a good fit. | "Proves ≥ 80% of 0 requirements" would make good-fit counts meaningless. |
| 7 | The blind card also hides company and institution names until the match (configurable). | Consistent with the decision against a prestige score: the first screening sees evidence, not brands. Internal promotions still show. |
| 8 | Weighted baseline: Interessa criteria weigh 1/3 each; with the history pillar, pillars weigh 0.6 / 0.25 / 0.15; the requirements tuple becomes k1 + k2/10 + k3/100 + k4/1000. | The spec gives only the Atende and pillar weights. It is a baseline for the evaluation, never served. |
| 9 | Seniority fallback by years (used only when titles say nothing): <2 → Júnior, 2–5 → Pleno, 5–9 → Sênior, 9–13 → Staff, 13+ → Principal; students → Estágio. | The spec says titles rule and years are only a fallback, without thresholds. |
| 10 | Events carry an extra `rules_hash` column. | So every recorded judgment can be traced to the exact rule set that produced the list. |
| 11 | Events are append-only, with one exception: the LGPD purge (`allow_event_delete`). | The spec requires both append-only events and the deletion of a candidate's events on request. |
| 12 | k-anonymity renders every count from 0 to 4 as "<5". | Literal reading of the spec ("aggregate with a count below 5 appears as <5"). |
| 13 | `Job.version` bumps only when the posting content changes; an LLM re-extraction updates the vectors of the same version. | A better extraction is not a new posting and must not trigger the "vaga atualizada" badge. |
| 14 | Embedding batch size is 32 instead of 64. | The development machine had about 1.4 GB of free RAM; fastembed's temporaries grow linearly with the batch (see research notes). |
| 15 | fastembed vectors are cast to float32 and L2-normalized by Encaixe. | fastembed 0.8.1 returns mean-pooled, non-normalized float64 vectors for this model. |
| 16 | ONNX Runtime's CPU memory arena is disabled (`enable_cpu_mem_arena=False`). | Measured on the dev machine: 605 MB after loading the model; embedding 256 texts in batches of 32 peaked at 815 MB with the arena and 613 MB without it (the arena keeps the batch buffers). Needed for the 700 MB steady-state budget. |
| 17 | When a job has a requirements section, skills found only in its title are desirable, not required. | The requirements list is what the company states; "ML Engineer" in a title would otherwise add a must that the posting never lists. |
| 18 | "Transversal" skills (Excel, Git, negotiation, project management…) define no domain and do not count as proof of area. | An analyst who uses Excel must not make a sales job "in area"; an analyst who builds sales dashboards does not prove sales. |
| 19 | Sentences stating an interest ("Interesse em machine learning") do not create listed skills. | Interest is not a claim of skill. |
| 20 | A Brazilian CV written in Portuguese gets Portuguese (native) as an inferred language. | CVs rarely list the mother tongue; it is shown as "inferido" for review. |
