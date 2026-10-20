"""CV and job extraction, the seed data, embeddings and the market-map projection."""

from __future__ import annotations

import numpy as np
import pytest
from sqlmodel import Session, select

from app import embeddings
from app.config import RULES
from app.embeddings import FakeEmbedder, TfidfEmbedder, embed_texts, get_embedder
from app.embeddings.projection import compute_projection, project_points, star_position
from app.embeddings.texts import candidate_embed_text, candidate_skills_ordered
from app.extraction.cv import extract_cv
from app.extraction.job import RawPosting, extract_job
from app.geo import load as load_geo
from app.jobs import ensure_job_vectors, job_texts, upsert_job
from app.models import Job, JobVersion, Recruiter
from app.seed.loader import load_recruiters, load_seed_jobs, persona_text, seed_jobs_data

# --------------------------------------------------------------------------- CV


def test_ana_cv_extraction() -> None:
    d = extract_cv(persona_text("ana"))
    assert d.name == "Ana Ribeiro Lima"
    assert d.city_id == "florianopolis-sc-br"  # "Lima" in her name is not Lima, Peru
    assert [e.company for e in d.experiences] == ["Maré Logística Digital", "Cooperativa Vale do Itajaí Fictícia"]
    current = d.experiences[0]
    assert current.end is None and current.seniority == 2
    assert {"sql", "python", "power_bi", "statistics"} <= set(current.skills_used)
    assert "machine_learning" not in d.skills_listed  # "Interesse em machine learning" is not a skill claim
    assert {lang.language for lang in d.languages} == {"en", "es", "pt"}
    assert d.education[0].degree == "Bacharelado" and d.education[0].field == "Estatística"
    assert d.provenance["experiences.0.start"].stated is True
    assert d.provenance["languages.pt"].stated is False  # inferred


def test_cv_without_dated_experience_lists_skills_only() -> None:
    d = extract_cv("Fulano de Tal\nHabilidades\nPython, SQL, Docker\n")
    assert d.experiences == [] and set(d.skills_listed) == {"python", "sql", "docker"}
    assert any("nenhuma experiência" in w for w in d.warnings)


# --------------------------------------------------------------------------- jobs and seed


def test_carla_job_has_five_musts() -> None:
    text = persona_text("lumen_ml_engineer_jr")
    title, _, body = text.partition("\n")
    d = extract_job(
        RawPosting(title=title, description=body, company="Lumen Dados", location_text="Florianópolis, SC (híbrido)")
    )
    assert d.requires.skills_must == ["python", "sql", "statistics", "pytorch", "deep_learning"]
    assert d.requires.seniority == 2 and d.offers.arrangement == "hybrid" and d.city_id == "florianopolis-sc-br"
    assert (d.offers.comp_min, d.offers.comp_max, d.offers.regime) == (6000, 8000, "clt")


def test_extractor_quality_on_the_seed() -> None:
    """The fictional seed carries the expected must skills: the heuristic must find them."""
    geo = load_geo()
    tp = fn = fp = 0
    for item in seed_jobs_data():
        d = extract_job(
            RawPosting(
                title=item["title"],
                description=item["description"],
                company=item["company"],
                location_text=item["location_text"],
            )
        )
        exp, got = set(item["expected"]["skills_must"]), set(d.requires.skills_must)
        tp, fn, fp = tp + len(exp & got), fn + len(exp - got), fp + len(got - exp)
        assert d.offers.arrangement == item["expected"]["arrangement"], item["id"]
        assert d.requires.seniority == item["expected"]["seniority"], item["id"]
        assert (d.offers.comp_max is not None) == item["expected"]["has_salary"], item["id"]
        el = item["expected"]["eligibility"]
        want = set() if el is None else ({el} if len(el) == 2 else set(geo.region_members(el)))
        assert set(d.eligibility.countries) == want, item["id"]
    assert tp / (tp + fn) >= 0.95 and tp / (tp + fp) >= 0.95


def test_seed_loads_idempotently(session: Session) -> None:
    counts = load_seed_jobs(session)
    assert counts["new"] == 60
    recs = load_recruiters(session)
    assert len(recs) == 5 and {r.name for r in recs} >= {"Carla Menezes"}
    lumen = next(r for r in recs if r.name == "Carla Menezes")
    assert session.exec(select(Job).where(Job.owner_recruiter_id == lumen.id)).all() == []  # not preloaded
    session.commit()
    again = load_seed_jobs(session)
    assert again["unchanged"] == 60 and again["new"] == 0
    assert len(session.exec(select(Recruiter)).all()) == 5
    sales = session.exec(select(Job).where(Job.title == "Sales Manager")).one()
    assert sales.domains == ["business"]


def test_job_versions_bump_only_on_content_change(session: Session) -> None:
    d = extract_job(RawPosting(title="Analista de Dados", description="Requisitos\n- SQL\n"))
    r1 = upsert_job(session, d, source="t", source_id="1")
    r2 = upsert_job(session, d, source="t", source_id="1")
    d2 = extract_job(RawPosting(title="Analista de Dados", description="Requisitos\n- SQL\n- Python\n"))
    r3 = upsert_job(session, d2, source="t", source_id="1")
    assert (r1.status, r2.status, r3.status) == ("new", "unchanged", "updated")
    assert r3.job.version == 2
    assert len(session.exec(select(JobVersion).where(JobVersion.job_id == r3.job.id)).all()) == 2


# --------------------------------------------------------------------------- embeddings


def test_fake_embedder_is_deterministic_and_normalized() -> None:
    e = FakeEmbedder()
    a = e.embed(["Analista de dados SQL Python", "Analista de dados SQL Python", "Vendas B2B"])
    assert np.allclose(np.linalg.norm(a, axis=1), 1, atol=1e-5)
    assert np.allclose(a[0], a[1]) and float(a[0] @ a[2]) < 0.9


def test_tfidf_backend_fits_once_and_persists(tmp_path) -> None:  # type: ignore[no-untyped-def]
    e = TfidfEmbedder(tmp_path / "tfidf.joblib")
    v = e.embed(["engenheiro de dados spark", "analista de dados sql", "gerente de vendas"])
    assert v.shape == (3, TfidfEmbedder.dim) and (tmp_path / "tfidf.joblib").exists()
    again = TfidfEmbedder(tmp_path / "tfidf.joblib").embed(["engenheiro de dados spark"])
    assert np.allclose(again[0], v[0], atol=1e-5)


def test_fastembed_failure_falls_back_to_tfidf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDINGS", "fastembed")
    from app.config import reset_settings

    reset_settings()
    embeddings.reset_caches()

    def boom(self) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("no model offline")

    monkeypatch.setattr(embeddings.FastEmbedder, "load", boom)
    e = get_embedder()
    assert e.name == "tfidf"
    status = embeddings.embedding_status()
    assert status["requested"] == "fastembed" and "no model offline" in (status["fallback_reason"] or "")


def test_embedder_only_receives_short_strings(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The model truncates at 128 tokens: we never send more than the short strings of spec 7."""
    seen: list[str] = []
    real = FakeEmbedder.embed

    def spy(self, texts):  # type: ignore[no-untyped-def]
        seen.extend(texts)
        return real(self, texts)

    monkeypatch.setattr(FakeEmbedder, "embed", spy)
    load_seed_jobs(session)
    ensure_job_vectors(session)
    profile = extract_cv(persona_text("ana"))
    embed_texts([candidate_embed_text(profile)])
    limit = max(RULES.embeddings.job_text_max_words, RULES.embeddings.candidate_text_max_words)
    assert seen and all(len(t.split()) <= limit for t in seen)
    assert not any("Ana Ribeiro" in t or "@" in t for t in seen)  # no personal data


def test_candidate_text_puts_proven_skills_first() -> None:
    profile = extract_cv(persona_text("ana"))
    ordered = candidate_skills_ordered(profile)
    proven = {s for e in profile.experiences for s in e.skills_used}
    first_listed = next(i for i, s in enumerate(ordered) if s not in proven)
    assert all(s in proven for s in ordered[:first_listed])


def test_projection_and_star(session: Session) -> None:
    load_seed_jobs(session)
    info = compute_projection(session)
    assert info["n"] == 60 and info["clusters"]
    jobs = session.exec(select(Job)).all()
    assert all(j.x is not None and 0 <= j.x <= 1 for j in jobs)
    xy = project_points(np.eye(4, 8, dtype=np.float32))
    assert xy.shape == (4, 2)
    m = np.eye(3, dtype=np.float32)
    x, y, idx = star_position(m[0], m, np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 0.0]]), k=1)
    assert (x, y, idx) == (0.0, 0.0, [0])


def test_job_texts_have_title_and_skills(session: Session) -> None:
    load_seed_jobs(session)
    job = session.exec(select(Job).where(Job.title == "Analista de BI")).one()
    text, title = job_texts(job)
    assert text.startswith("Analista de BI") and "Power BI" in text and title == "Analista de BI"
