"""Decks (spec 8, 9): the ranked list minus judged items, with reappearance rules and exploration slots.

Reappearance (spec 8): an item already judged does not come back, except
- side B: a rejected candidate with a relevant revision after the rejection ("perfil atualizado…");
- side C: a platform job where the application did not advance, after a relevant revision of the candidate
  ("seu perfil mudou desde a recusa");
- side C: a job the candidate rejected whose version changed ("vaga atualizada").
Exploration: every RULES.exploration.every-th card of a page is drawn uniformly from the band between the
band_low_pct and band_high_pct percentiles of the current list, excluding the top exclude_top and anything
already shown; propensity = 1/|band|. Filters run first: feedback never resurrects a filtered item.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
from sqlmodel import Session, col, select

from app import texts
from app.config import RULES
from app.events import JUDGMENTS, applicants, match_for
from app.events.status import candidate_judgments, not_advanced_jobs
from app.jobs import company_name
from app.models import Candidate, InteractionEvent, Job, ProfileRevision, Setting
from app.ranking.counterfactual import smallest_change
from app.ranking.engine import RankedItem, RankResult
from app.ranking.explain import counterfactual_text, explain_item, filtered_groups, requirement_chips
from app.ranking.feedback import make_history_fn
from app.ranking.service import rank_for_candidate, rank_for_job
from app.schemas import CandidateProfile, Offers

SERVED_RANKER_KEY = "served_ranker"
SERVED_AGGREGATOR_KEY = "served_aggregator"


def served(session: Session) -> tuple[str, str]:
    r = session.get(Setting, SERVED_RANKER_KEY)
    a = session.get(Setting, SERVED_AGGREGATOR_KEY)
    return (
        r.value if r and r.value else RULES.rankers.default,
        a.value if a and a.value else RULES.aggregation.aggregator,
    )


def set_served(session: Session, ranker: str | None = None, aggregator: str | None = None) -> tuple[str, str]:
    for key, value, allowed in (
        (SERVED_RANKER_KEY, ranker, RULES.rankers.available),
        (SERVED_AGGREGATOR_KEY, aggregator, RULES.aggregation.available),
    ):
        if value is None:
            continue
        if value not in allowed:
            raise ValueError(f"{value!r} not in {allowed}")
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
            session.add(row)
    session.flush()
    return served(session)


@dataclass
class DeckEntry:
    item: RankedItem
    badges: list[str] = field(default_factory=list)


def _seed(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _assemble(entries: list[DeckEntry], shown: set[int], limit: int, seed: int) -> list[DeckEntry]:
    """Page of ``limit`` cards; every ``every``-th card is an exploration draw when the band is not empty."""
    rules = RULES.exploration
    n = len(entries)
    band = [
        e
        for i, e in enumerate(entries)
        if i >= rules.exclude_top
        and rules.band_low_pct / 100 <= i / max(n, 1) <= rules.band_high_pct / 100
        and e.item.item_id not in shown
    ]
    rng = np.random.default_rng(seed)
    page: list[DeckEntry] = []
    used: set[int] = set()
    ranked_iter = iter(entries)
    for k in range(1, limit + 1):
        if k % rules.every == 0:
            pool = [e for e in band if e.item.item_id not in used]
            if pool:
                pick = pool[int(rng.integers(len(pool)))]
                pick.item.slot = "explore"
                pick.item.propensity = 1.0 / len(pool)
                page.append(pick)
                used.add(pick.item.item_id)
                continue
        nxt = next((e for e in ranked_iter if e.item.item_id not in used), None)
        if nxt is None:
            break
        page.append(nxt)
        used.add(nxt.item.item_id)
    return page


def _rank_meta(item: RankedItem, result: RankResult) -> dict:
    return {
        "rank_position": item.order,
        "rank_sum": item.final_sum,
        "slot": item.slot,
        "propensity": item.propensity,
        "ranker_version": result.meta["ranker_version"],
        "aggregator": result.meta["aggregator"],
        "rules_hash": result.meta["rules_hash"],
        "rank_detail": {
            "pillars": item.pillars,
            "criteria": {c: {"raw": d["raw"], "position": d["position"]} for c, d in item.criteria.items()},
        },
    }


def _impressed(session: Session, actor_type: str, actor_id: int, context_job_id: int | None = None) -> set[int]:
    q = select(InteractionEvent.item_id).where(
        InteractionEvent.actor_type == actor_type,
        InteractionEvent.actor_id == actor_id,
        InteractionEvent.type == "impression",
    )
    if context_job_id is not None:
        q = q.where(InteractionEvent.context_job_id == context_job_id)
    return set(session.exec(q).all())


def _relevant_after(session: Session, candidate_id: int, ts) -> bool:  # type: ignore[no-untyped-def]
    return (
        session.exec(
            select(ProfileRevision.id).where(
                ProfileRevision.candidate_id == candidate_id,
                ProfileRevision.kind == "relevant",
                ProfileRevision.ts > ts,
            )
        ).first()
        is not None
    )


# --------------------------------------------------------------------------- job card (side C)


def source_info(job: Job, company: str | None) -> dict:
    label = texts.SOURCE_LABELS.get(job.source, job.source)
    if job.source == "github":
        repo = (job.source_id or "").split("#")[0]
        text = f"via {repo}"
    elif job.origin == "platform":
        text = "publicada no Encaixe"
    elif job.source == "seed":
        text = "vaga fictícia (dados de exemplo)"
    else:
        text = f"via {label}" + (f" — {company}" if company else "")
    return {"key": job.source, "label": label, "url": job.url, "text": text}


def comp_info(offers: Offers) -> dict | None:
    if offers.comp_max is None and offers.comp_min is None:
        return None
    lo, hi = offers.comp_min, offers.comp_max
    cur, per = offers.currency or "BRL", offers.period or "month"
    if lo is not None and hi is not None and lo != hi:
        text = f"{texts.fmt_money(lo, cur, None)} – {texts.fmt_money(hi, cur, per)}"
    else:
        text = texts.fmt_money(hi if hi is not None else lo, cur, per)  # type: ignore[arg-type]
    return {"min": lo, "max": hi, "currency": cur, "period": per, "text": text}


def job_summary(session: Session, job: Job) -> dict:
    offers = Offers.model_validate(job.offers or {})
    company = company_name(session, job.company_id)
    from app import geo as geo_mod

    city = geo_mod.load().get_city(job.city_id)
    return {
        "id": job.id,
        "title": job.title,
        "company": company,
        "city": city.name if city else None,
        "state": city.state if city else None,
        "location_text": job.location_text,
        "arrangement": offers.arrangement,
        "arrangement_label": texts.ARRANGEMENT_LABELS.get(offers.arrangement or "", "modalidade não informada"),
        "comp": comp_info(offers),
        "regime": texts.REGIME_LABELS.get(offers.regime or "", None),
        "seniority_label": texts.seniority_label((job.requires or {}).get("seniority")),
        "origin": job.origin,
        "status": job.status,
        "source": source_info(job, company),
        "version": job.version,
        "extraction_method": job.extraction_method,
    }


def job_card(session: Session, item: RankedItem, result: RankResult, badges: list[str]) -> dict:
    job = session.get(Job, item.item_id)
    assert job is not None
    c = result.meta["candidate"]
    j = item.extra["job"]
    cf = smallest_change(c, j) if not item.good_fit.is_good_fit else None
    explanation = explain_item(item, result.meta["n_items"], "candidate")
    explanation["slot_text"] = texts.EXPLORE_SLOT_TEXT if item.slot == "explore" else None
    all_badges = list(badges)
    if item.good_fit.is_good_fit:
        all_badges.insert(0, "good_fit")
    if item.slot == "explore":
        all_badges.append("explore")
    all_badges.append("platform" if job.origin == "platform" else "market")
    return {
        "item_type": "job",
        "item_id": job.id,
        "job": job_summary(session, job),
        "requirements": requirement_chips(item.req),
        "good_fit": {"is_good_fit": item.good_fit.is_good_fit, "text": explanation["good_fit_text"]},
        "counterfactual": None
        if cf is None
        else {"kind": cf.kind, "skills": cf.skills, "preferences": cf.preferences, "text": counterfactual_text(cf)},
        "badges": [{"code": b, "label": texts.BADGE_LABELS.get(b, b)} for b in all_badges],
        "rank_meta": _rank_meta(item, result),
        "explanation": explanation,
    }


def candidate_deck(
    session: Session,
    candidate_id: int,
    session_id: str | None = None,
    limit: int = 20,
    ranker: str | None = None,
    aggregator: str | None = None,
) -> dict:
    served_ranker, served_agg = served(session)
    ranker, aggregator = ranker or served_ranker, aggregator or served_agg
    history_fn = make_history_fn(session, "candidate", candidate_id) if ranker == "feedback-v1" else None
    result = rank_for_candidate(session, candidate_id, ranker=ranker, aggregator=aggregator, history_fn=history_fn)
    latest: dict[int, InteractionEvent] = {}
    for e in candidate_judgments(session, candidate_id):
        latest[e.item_id] = e
    rejected = not_advanced_jobs(session, candidate_id)
    entries: list[DeckEntry] = []
    for it in result.items:
        ev = latest.get(it.item_id)
        if ev is None:
            entries.append(DeckEntry(it))
            continue
        if ev.type == "swipe_right":
            when = rejected.get(it.item_id)
            if when is not None and _relevant_after(session, candidate_id, when):
                entries.append(DeckEntry(it, ["profile_changed_since_rejection"]))
            continue
        job = it.extra["job"]
        if ev.item_version is not None and job.version > ev.item_version:
            entries.append(DeckEntry(it, ["job_updated"]))
    shown = _impressed(session, "candidate", candidate_id)
    page = _assemble(entries, shown, limit, _seed("candidate", candidate_id, session_id, len(shown)))
    groups = filtered_groups(result.filtered, lambda jid: {"job_id": jid})
    return {
        "cards": [job_card(session, e.item, result, e.badges) for e in page],
        "n_open": result.meta["n_total"],
        "n_eligible": result.meta["n_eligible"],
        "n_filtered": result.meta["n_filtered"],
        "n_remaining": len(entries),
        "filtered_summary": groups["summary"],
        "ranker_version": ranker,
        "aggregator": aggregator,
        "history_active": result.meta["history_active"],
        "rules_hash": result.meta["rules_hash"],
        "session_id": session_id,
    }


def candidate_filtered(session: Session, candidate_id: int) -> dict:
    result = rank_for_candidate(session, candidate_id, ranker="static-v1")

    def describe(job_id: int) -> dict:
        job = session.get(Job, job_id)
        return {"job": job_summary(session, job)} if job else {"job_id": job_id}

    return filtered_groups(result.filtered, describe)


# --------------------------------------------------------------------------- candidate card (side B)


def candidate_card(session: Session, item: RankedItem, result: RankResult, job_id: int, badges: list[str]) -> dict:
    from app.privacy import candidate_card_profile
    from app.profiles import current_profile

    cand = session.get(Candidate, item.item_id)
    assert cand is not None
    profile = current_profile(session, cand) or CandidateProfile()
    matched = match_for(session, cand.id, job_id) is not None  # type: ignore[arg-type]
    explanation = explain_item(item, result.meta["n_items"], "recruiter")
    explanation["slot_text"] = texts.EXPLORE_SLOT_TEXT_RECRUITER if item.slot == "explore" else None
    all_badges = list(badges)
    if item.applicant:
        all_badges.insert(0, "applicant")
    if item.good_fit.is_good_fit:
        all_badges.append("good_fit")
    if item.slot == "explore":
        all_badges.append("explore")
    return {
        "item_type": "candidate",
        "item_id": cand.id,
        "candidate": candidate_card_profile(profile, matched, cand.contact),
        "revision_id": cand.current_revision_id,
        "applicant": item.applicant,
        "requirements": requirement_chips(item.req),
        "good_fit": {"is_good_fit": item.good_fit.is_good_fit, "text": explanation["good_fit_text"]},
        "badges": [{"code": b, "label": texts.BADGE_LABELS.get(b, b)} for b in all_badges],
        "rank_meta": _rank_meta(item, result),
        "explanation": explanation,
    }


def recruiter_deck(
    session: Session,
    recruiter_id: int,
    job_id: int,
    session_id: str | None = None,
    limit: int = 20,
    ranker: str | None = None,
    aggregator: str | None = None,
) -> dict:
    job = session.get(Job, job_id)
    if job is None or job.owner_recruiter_id != recruiter_id:
        raise PermissionError("job not owned by recruiter")
    served_ranker, served_agg = served(session)
    ranker, aggregator = ranker or served_ranker, aggregator or served_agg
    apps = applicants(session, job_id)
    history_fn = (
        make_history_fn(session, "recruiter", recruiter_id, context_job_id=job_id) if ranker == "feedback-v1" else None
    )
    result = rank_for_job(session, job_id, ranker=ranker, aggregator=aggregator, applicants=apps, history_fn=history_fn)
    latest: dict[int, InteractionEvent] = {}
    for e in session.exec(
        select(InteractionEvent)
        .where(
            InteractionEvent.actor_type == "recruiter",
            InteractionEvent.actor_id == recruiter_id,
            InteractionEvent.context_job_id == job_id,
            col(InteractionEvent.type).in_(JUDGMENTS),
        )
        .order_by(col(InteractionEvent.ts), col(InteractionEvent.id))
    ).all():
        latest[e.item_id] = e
    entries: list[DeckEntry] = []
    for it in result.items:
        ev = latest.get(it.item_id)
        if match_for(session, it.item_id, job_id) is not None:
            continue
        if ev is None:
            entries.append(DeckEntry(it))
        elif ev.type == "swipe_left" and _relevant_after(session, it.item_id, ev.ts):
            entries.append(DeckEntry(it, ["profile_updated_since_last_review"]))
        elif ev.type == "swipe_right" and it.applicant and match_for(session, it.item_id, job_id) is None:
            continue
    shown = _impressed(session, "recruiter", recruiter_id, job_id)
    page = _assemble(entries, shown, limit, _seed("recruiter", recruiter_id, job_id, session_id, len(shown)))
    return {
        "cards": [candidate_card(session, e.item, result, job_id, e.badges) for e in page],
        "n_candidates": result.meta["n_total"],
        "n_eligible": result.meta["n_eligible"],
        "n_filtered": texts.k_anon_count(result.meta["n_filtered"]),
        "n_applicants": len(apps),
        "n_remaining": len(entries),
        "ranker_version": ranker,
        "aggregator": aggregator,
        "history_active": result.meta["history_active"],
        "rules_hash": result.meta["rules_hash"],
        "notice": texts.RECRUITER_TRANSPARENCY_NOTICE,
        "session_id": session_id,
    }
