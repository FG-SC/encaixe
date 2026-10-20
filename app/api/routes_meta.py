"""Meta endpoints: health and the front-facing rule values."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__, texts
from app.config import RULES, rules_hash
from app.schemas import (
    EventTimings,
    ExplorationPublic,
    Health,
    LabeledOption,
    PrivacyPublic,
    ReasonsPublic,
    RulesPublic,
    SeniorityLevelOut,
)

router = APIRouter(prefix="/api", tags=["meta"])


def _options(codes: tuple[str, ...] | list[str], labels: dict[str, str]) -> list[LabeledOption]:
    return [LabeledOption(code=c, label=labels.get(c, c)) for c in codes]


def build_rules_public() -> RulesPublic:
    """Everything the front needs from RULES; the front never hardcodes a rule number."""
    return RulesPublic(
        rules_hash=rules_hash(),
        events=EventTimings(
            impression_min_ms=RULES.events.impression_min_ms,
            session_idle_minutes=RULES.events.session_idle_minutes,
            reason_chips_seconds=RULES.events.reason_chips_seconds,
        ),
        exploration=ExplorationPublic(every=RULES.exploration.every),
        reasons=ReasonsPublic(
            candidate=_options(RULES.reasons.candidate, texts.REASON_LABELS_CANDIDATE),
            recruiter=_options(RULES.reasons.recruiter, texts.REASON_LABELS_RECRUITER),
            recruiter_required_for_applicants=RULES.reasons.recruiter_required_for_applicants,
        ),
        arrangements=_options(tuple(texts.ARRANGEMENT_LABELS), texts.ARRANGEMENT_LABELS),
        regimes=_options(tuple(texts.REGIME_LABELS), texts.REGIME_LABELS),
        periods=_options(tuple(texts.PERIOD_LABELS), texts.PERIOD_LABELS),
        language_levels=_options(tuple(texts.LANGUAGE_LEVEL_LABELS), texts.LANGUAGE_LEVEL_LABELS),
        seniority=[SeniorityLevelOut(level=k, label=v) for k, v in sorted(RULES.seniority.ladder.items())],
        privacy=PrivacyPublic(
            k_anon=RULES.privacy.k_anon,
            below_k_label=texts.below_k_label(),
            candidate_default_visible=RULES.privacy.candidate_default_visible,
            blind_hidden=_options(RULES.privacy.blind_hidden, texts.BLIND_HIDDEN_LABELS),
            texts=dict(texts.PRIVACY_TEXTS),
        ),
    )


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(ok=True, version=__version__, rules_hash=rules_hash())


@router.get("/rules/public", response_model=RulesPublic)
def rules_public() -> RulesPublic:
    return build_rules_public()
