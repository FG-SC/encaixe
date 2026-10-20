"""Privacy by default (spec 10): blind cards, k-anonymity, export and purge."""

from __future__ import annotations

from sqlmodel import Session, col, delete, or_, select

from app import taxonomy as tax_mod
from app import texts
from app.config import RULES
from app.db import allow_event_delete
from app.embeddings.texts import recent_experiences
from app.models import (
    Candidate,
    Education,
    Experience,
    InteractionEvent,
    LlmCache,
    Match,
    ProfileRevision,
    Setting,
)
from app.profiles import bump_candidates_version
from app.profiles.levels import candidate_level
from app.schemas import CandidateProfile


def _period(exp) -> str:  # type: ignore[no-untyped-def]
    def fmt(d) -> str:  # type: ignore[no-untyped-def]
        return f"{d.month:02d}/{d.year}" if d else "?"

    return f"{fmt(exp.start)} – {fmt(exp.end) if exp.end else 'atual'}"


def candidate_card_profile(profile: CandidateProfile, matched: bool, contact: str | None = None) -> dict:
    """What a recruiter sees. Until the match, the fields in RULES.privacy.blind_hidden (name, contact, photo, age)."""
    tax = tax_mod.load()
    hidden = set(RULES.privacy.blind_hidden) if not matched else set()
    exps = recent_experiences(profile.experiences)
    companies = [((e.company or "").strip().lower()) for e in exps]
    out_exps = []
    for i, e in enumerate(exps):
        same_next = i + 1 < len(exps) and companies[i] and companies[i] == companies[i + 1]
        same_prev = i > 0 and companies[i] and companies[i] == companies[i - 1]
        out_exps.append(
            {
                "role": e.role,
                "company": None if "company_names" in hidden else e.company,
                "period": _period(e),
                "skills_used": [tax.label(s) for s in e.skills_used],
                "internal_promotion": bool(same_next or same_prev),
                "dated": e.start is not None,
            }
        )
    proven = {s for e in profile.experiences if e.start for s in e.skills_used}
    return {
        "blind": not matched,
        "name": None if "name" in hidden else profile.name,
        "contact": None if "contact" in hidden else (contact or profile.contact),
        "headline": profile.headline,
        "seniority_label": texts.seniority_label(candidate_level(profile)),
        "city_id": profile.city_id,
        "experiences": out_exps,
        "education": [
            {
                "degree": d.degree,
                "field": d.field,
                "institution": None if "institution_names" in hidden else d.institution,
                "in_progress": d.end is None and d.start is not None,
            }
            for d in profile.education
        ],
        "skills_proven": [tax.label(s) for s in sorted(proven)],
        "skills_listed": [tax.label(s) for s in sorted(set(profile.skills_listed) - proven)],
        "languages": [
            {
                "language": texts.LANGUAGE_LABELS.get(lang.language, lang.language),
                "level": texts.LANGUAGE_LEVEL_LABELS.get(lang.level or "", None),
            }
            for lang in profile.languages
        ],
        "hidden_fields": [texts.BLIND_HIDDEN_LABELS[h] for h in RULES.privacy.blind_hidden] if not matched else [],
    }


def k_anon(n: int) -> str:
    return texts.k_anon_count(n)


# --------------------------------------------------------------------------- export and purge


def export_candidate(session: Session, candidate_id: int) -> dict | None:
    """Everything Encaixe stores about the person, events included (LGPD)."""
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        return None
    events = session.exec(
        select(InteractionEvent)
        .where(
            or_(
                (InteractionEvent.actor_type == "candidate") & (InteractionEvent.actor_id == candidate_id),
                (InteractionEvent.item_type == "candidate") & (InteractionEvent.item_id == candidate_id),
            )
        )
        .order_by(col(InteractionEvent.ts))
    ).all()
    return {
        "candidate": cand.model_dump(mode="json"),
        "experiences": [
            e.model_dump(mode="json")
            for e in session.exec(select(Experience).where(Experience.candidate_id == candidate_id)).all()
        ],
        "education": [
            e.model_dump(mode="json")
            for e in session.exec(select(Education).where(Education.candidate_id == candidate_id)).all()
        ],
        "revisions": [
            r.model_dump(mode="json", exclude={"embedding", "title_embedding"})
            for r in session.exec(select(ProfileRevision).where(ProfileRevision.candidate_id == candidate_id)).all()
        ],
        "events": [e.model_dump(mode="json") for e in events],
        "matches": [
            m.model_dump(mode="json")
            for m in session.exec(select(Match).where(Match.candidate_id == candidate_id)).all()
        ],
        "stored_in": "var/ (local SQLite database); nothing is sent anywhere except, with consent, the CV text "
        "to the LLM provider at onboarding",
    }


def purge_candidate(session: Session, candidate_id: int) -> dict[str, int]:
    """Delete the candidate, revisions, events where they are actor or item, matches and the CV LLM cache."""
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        return {}
    counts: dict[str, int] = {}
    cache_keys = [
        s.value
        for s in session.exec(select(Setting).where(col(Setting.key).startswith(f"llm_cv_cache:{candidate_id}:"))).all()
    ]
    with allow_event_delete(session):
        res = session.exec(
            delete(InteractionEvent).where(
                or_(  # type: ignore[call-overload]
                    (InteractionEvent.actor_type == "candidate") & (InteractionEvent.actor_id == candidate_id),
                    (InteractionEvent.item_type == "candidate") & (InteractionEvent.item_id == candidate_id),
                )
            )
        )
        counts["events"] = res.rowcount or 0
    for model, key in (
        (Match, Match.candidate_id),
        (ProfileRevision, ProfileRevision.candidate_id),
        (Experience, Experience.candidate_id),
        (Education, Education.candidate_id),
    ):
        res = session.exec(delete(model).where(key == candidate_id))  # type: ignore[call-overload]
        counts[model.__name__.lower()] = res.rowcount or 0
    if cache_keys:
        res = session.exec(delete(LlmCache).where(col(LlmCache.key).in_(cache_keys)))  # type: ignore[call-overload]
        counts["llm_cache"] = res.rowcount or 0
    session.exec(delete(Setting).where(col(Setting.key).startswith(f"llm_cv_cache:{candidate_id}:")))  # type: ignore[call-overload]
    session.delete(cand)
    bump_candidates_version(session)
    session.flush()
    counts["candidate"] = 1
    return counts
