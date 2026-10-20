"""Simulated histories (spec 5.3, 13): personas use the deck day by day and swipe by a hidden utility.

The oracle (utility) is known only to the simulation; the ranking never sees it. It mixes area affinity, the
share of must requirements the person proves, seniority fit, salary and arrangement, plus noise. Histories feed
the replay evaluation and make the Explorar screens and the funnel meaningful in the demo.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.config import RULES, rules_hash
from app.events import record_event
from app.models import Candidate, InteractionEvent, Job, Recruiter
from app.profiles import create_candidate, save_profile
from app.ranking.deck import DeckEntry, _assemble
from app.ranking.engine import rank
from app.ranking.features import CandidateFeatures, JobFeatures, job_comp_max_for
from app.ranking.feedback import make_history_fn
from app.ranking.index import job_index
from app.ranking.pair import RequirementEval
from app.ranking.service import candidate_features_for, pairs_for_candidate, rank_for_job
from app.synth.personas import Persona, Taste

LIKE_THRESHOLD = 0.55


def utility(domains: dict[str, float], c: CandidateFeatures, j: JobFeatures, req: RequirementEval) -> float:
    """The hidden "true" utility of a job for a simulated person (0–1, before noise)."""
    affinity = max((domains.get(d, 0.1) for d in j.domains), default=0.3)
    reqs = req.must_share if req.known else 0.5
    gap = abs(j.level - c.level) if j.level is not None and c.level is not None else 1
    seniority = max(0.0, 1.0 - gap / 3)
    job_max, _ = job_comp_max_for(j, c.wants)
    salary = 0.6 if job_max is None or not c.wants.comp_min else (1.0 if job_max >= c.wants.comp_min else 0.2)
    arrangement = 1.0 if (j.arrangement is None or j.arrangement in c.wants.arrangements) else 0.0
    return 0.45 * affinity + 0.25 * reqs + 0.15 * seniority + 0.10 * salary + 0.05 * arrangement


def taste_at(taste: Taste, day: int) -> dict[str, float]:
    if taste.drift_day is not None and taste.drift_domains is not None and day >= taste.drift_day:
        return taste.drift_domains
    return taste.domains


def p_like(u: float, noise: float, rng: random.Random) -> bool:
    return (u + rng.gauss(0, noise)) >= LIKE_THRESHOLD


def left_reason(domains: dict[str, float], c: CandidateFeatures, j: JobFeatures, rng: random.Random) -> str | None:
    affinity = max((domains.get(d, 0.1) for d in j.domains), default=0.3)
    if affinity < 0.3 and rng.random() < 0.7:
        return "role_area"
    job_max, _ = job_comp_max_for(j, c.wants)
    if job_max is not None and c.wants.comp_min and job_max < c.wants.comp_min and rng.random() < 0.7:
        return "salary"
    if j.level is not None and c.level is not None and abs(j.level - c.level) >= 2 and rng.random() < 0.6:
        return "seniority"
    return None


def _event(session: Session, **kw: object) -> None:
    """Direct insert for trusted simulated events (platform applications go through record_event)."""
    session.add(InteractionEvent(client_event_id=str(uuid.uuid4()), rules_hash=rules_hash(), **kw))  # type: ignore[arg-type]


def simulate(
    session: Session,
    personas: list[Persona],
    sim_start: datetime,
    days: int,
    seed: int,
    sessions_per_week: float = 2.0,
    cards: int = 8,
) -> dict[str, int]:
    """Create the candidates and play their histories day by day (chronological; revisions in place)."""
    rng = random.Random(seed + 1)
    created: list[tuple[Persona, int]] = []
    for p in personas:
        cand = create_candidate(session, p.profile, synthetic=True, visible=True, ts=sim_start).candidate
        created.append((p, cand.id))  # type: ignore[arg-type]
    session.flush()
    idx = job_index(session)
    by_id = {j.job_id: j for j in idx.jobs}
    judged: dict[int, set[int]] = {cid: set() for _, cid in created}
    recruiters = session.exec(select(Recruiter)).all()
    counts = {
        "sessions": 0,
        "impressions": 0,
        "likes": 0,
        "dislikes": 0,
        "applications": 0,
        "recruiter_reviews": 0,
        "revisions": 0,
    }
    for day in range(days):
        ts_day = sim_start + timedelta(days=day)
        for p, cid in created:
            if p.revision_day == day and p.revised_profile is not None:
                cand = session.get(Candidate, cid)
                save_profile(session, cand, p.revised_profile, ts=ts_day)  # type: ignore[arg-type]
                counts["revisions"] += 1
            if rng.random() > sessions_per_week / 7:
                continue
            counts["sessions"] += 1
            session_id = f"sim-{cid}-{day}"
            ts = ts_day + timedelta(hours=rng.randint(8, 21), minutes=rng.randint(0, 59))
            c = candidate_features_for(session, cid)
            pairs = pairs_for_candidate(c, idx.jobs, idx.emb, idx.title_emb)
            hist = make_history_fn(session, "candidate", cid, until=ts)
            if hist is not None:
                hist(pairs)
            result = rank(pairs, side="candidate", ranker="feedback-v1")
            entries = [DeckEntry(it) for it in result.items if it.item_id not in judged[cid]]
            page = _assemble(entries, set(), cards, rng.randint(0, 10**9))
            domains = taste_at(p.taste, day)
            for k, e in enumerate(page):
                j = by_id[e.item.item_id]
                job = session.get(Job, j.job_id)
                base = dict(
                    actor_type="candidate",
                    actor_id=cid,
                    item_type="job",
                    item_id=j.job_id,
                    ts=ts,
                    session_id=session_id,
                    actor_revision_id=c.revision_id,
                    item_version=j.version,
                    ranker_version=result.meta["ranker_version"],
                    slot=e.item.slot,
                    propensity=e.item.propensity,
                    rank_position=e.item.order,
                    rank_sum=e.item.final_sum,
                )
                _event(session, type="impression", **base)
                counts["impressions"] += 1
                like = p_like(utility(domains, c, j, e.item.req), p.taste.noise, rng)
                judged[cid].add(j.job_id)
                ts_swipe = ts + timedelta(seconds=5 + 3 * k)
                if like and job is not None and job.origin == "platform":
                    record_event(
                        session, {**base, "client_event_id": str(uuid.uuid4()), "type": "swipe_right", "ts": ts_swipe}
                    )
                    counts["applications"] += 1
                elif like:
                    _event(session, type="swipe_right", **{**base, "ts": ts_swipe})
                else:
                    _event(
                        session, type="swipe_left", reason=left_reason(domains, c, j, rng), **{**base, "ts": ts_swipe}
                    )
                counts["likes" if like else "dislikes"] += 1
        if day % 7 == 6:
            counts["recruiter_reviews"] += _recruiters_review(session, recruiters, ts_day + timedelta(hours=10), rng)
        session.flush()
    return counts


def _recruiters_review(session: Session, recruiters: list[Recruiter], ts: datetime, rng: random.Random) -> int:
    """Once a week each recruiter reviews the top of each of their jobs (applicants first)."""
    from app.events import applicants

    n = 0
    for rec in recruiters:
        for job in session.exec(select(Job).where(Job.owner_recruiter_id == rec.id, Job.status == "open")).all():
            apps = applicants(session, job.id)  # type: ignore[arg-type]
            result = rank_for_job(session, job.id, applicants=apps)  # type: ignore[arg-type]
            done = {
                e.item_id
                for e in session.exec(
                    select(InteractionEvent).where(
                        InteractionEvent.actor_type == "recruiter",
                        InteractionEvent.context_job_id == job.id,
                        InteractionEvent.type.in_(("swipe_left", "swipe_right")),
                    )
                )
            }  # type: ignore[attr-defined]
            for it in [x for x in result.items if x.item_id not in done][:6]:
                share = it.req.must_share if it.req.known else 0.0
                gap = it.good_fit.seniority_gap or 0
                good = it.good_fit.is_good_fit or (share >= 0.6 and gap <= 1)
                reason = None
                if not good:
                    reason = (
                        "skills" if share < 0.6 else ("seniority" if gap >= 2 else rng.choice(["salary", "location"]))
                    )
                base = dict(
                    client_event_id=str(uuid.uuid4()),
                    actor_type="recruiter",
                    actor_id=rec.id,
                    item_type="candidate",
                    item_id=it.item_id,
                    context_job_id=job.id,
                    ts=ts,
                    session_id=f"sim-r{rec.id}-{ts.date()}",
                    slot="ranked",
                    rank_position=it.order,
                    rank_sum=it.final_sum,
                    ranker_version=result.meta["ranker_version"],
                )
                record_event(session, {**base, "type": "impression"})
                record_event(
                    session,
                    {
                        **base,
                        "client_event_id": str(uuid.uuid4()),
                        "type": "swipe_right" if good else "swipe_left",
                        "reason": reason,
                        "ts": ts + timedelta(seconds=20),
                    },
                )
                n += 1
    return n


def sim_start_for(days: int, today: date) -> datetime:
    from app import clock

    now = clock.now()
    return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


__all__ = ["simulate", "utility", "taste_at", "LIKE_THRESHOLD", "RULES"]
