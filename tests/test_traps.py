"""The known traps of the previous version (spec 6). Trap 5 and trap 9 need the ranking: see test_ranking.py."""

from __future__ import annotations

from datetime import date

from app.extraction.dates import union_years
from app.extraction.job import RawPosting, extract_job
from app.extraction.salary import extract_salary
from app.extraction.text import heading_kind, split_sections
from app.geo import load as load_geo
from app.jobs import job_texts
from app.models import Job
from app.money import convert


def test_trap_1_salary_regex_ignores_funding_and_scale() -> None:
    assert extract_salary("We raised $50M in our Series B.") is None
    assert extract_salary("Our app has 100M customers in 12 countries.") is None
    assert extract_salary("Captamos R$ 40 milhões em 2025 e atendemos 2 milhões de clientes.") is None
    assert extract_salary("Faturamento de R$ 10 milhões por ano.") is None
    s = extract_salary("We raised $50M. Salary range: $120,000 - $150,000 per year.")
    assert s is not None and (s.comp_min, s.comp_max, s.currency, s.period) == (120000, 150000, "USD", "year")


def test_trap_2_section_headings_only_at_line_start() -> None:
    assert heading_kind("Requisitos:") == ("must", len("Requisitos:"))
    assert heading_kind("We follow the requirements of our clients.") is None
    assert heading_kind("Pay attention to detail") is None
    text = "O que você vai fazer\nAtender aos requisitos do cliente com Python.\nDiferenciais\nAirflow\n"
    kinds = [s.kind for s in split_sections(text)]
    assert "must" not in kinds and "nice" in kinds
    draft = extract_job(RawPosting(title="Dev", description="Our requirements are simple.\nRequirements\n- Go\n"))
    assert draft.requires.skills_must == ["go"]


def test_trap_3_timezone_abbreviations_are_case_sensitive_and_contextual() -> None:
    g = load_geo()
    assert g.parse_tz("Must overlap 9am-5pm ET") == "America/New_York"
    assert g.parse_tz("Overlap with PT hours") == "America/Los_Angeles"
    assert g.parse_tz("Conhecimento em PT e EN para documentação") is None  # Portuguese, not Pacific Time
    assert g.parse_tz("et al. mostram que") is None  # lowercase "et" is a word
    assert g.parse_tz("Portugal (PT)") is None


def test_trap_4_years_are_the_union_of_intervals() -> None:
    today = date(2026, 10, 1)
    gap = [(date(2015, 1, 1), date(2016, 12, 1)), (date(2023, 1, 1), date(2024, 12, 1))]
    assert union_years(gap, today) == 4.0  # not 2024 - 2015 = 10
    overlap = [(date(2020, 1, 1), date(2021, 12, 1)), (date(2021, 1, 1), date(2022, 12, 1))]
    assert union_years(overlap, today) == 3.0  # 2020-2022, counted once


def test_trap_6_country_codes_in_location_fields() -> None:
    g = load_geo()
    assert g.find_city("BR") is None and g.find_city("US") is None
    assert g.location_country("Remote - BR") == "BR"
    assert g.location_country("Lisboa, PT") == "PT"
    assert g.find_city("Lisboa, PT").city_id == "lisbon-pt"  # type: ignore[union-attr]
    assert g.find_eligibility("Remote - US only") == ["US"]
    # In free text a two-letter code is not a country.
    assert g.find_countries("Conhecimento em PT e EN") == []


def test_trap_7_currencies_are_converted_and_flagged() -> None:
    usd = convert(120_000, "USD", "year", "BRL", "month")
    assert usd is not None and usd.approx_fx and 40_000 < usd.value < 60_000
    brl = convert(6_000, "BRL", "month", "BRL", "month")
    assert brl is not None and brl.value == 6_000 and not brl.approx_fx
    s = extract_salary("Compensation: €60k–€75k per year")
    assert s is not None and s.currency == "EUR" and s.period == "year"


def test_trap_8_institutional_text_is_kept_out_of_skills_and_embeddings() -> None:
    description = (
        "About us\nWe are an AI company: Python, Kubernetes and LLMs everywhere. We raised $30M.\n\n"
        "What you'll do\nAnalyze sales data and build dashboards.\n\n"
        "Requirements\n- SQL\n- Tableau\n\n"
        "Benefits\nGym pass, Python courses.\n\n"
        "We are an equal opportunity employer and value diversity."
    )
    draft = extract_job(RawPosting(title="Data Analyst", description=description))
    assert draft.requires.skills_must == ["sql", "tableau"]
    assert "python" not in draft.requires.skills_nice and "kubernetes" not in draft.requires.skills_nice
    job = Job(
        source="t",
        source_id="1",
        title=draft.title,
        description_text=draft.description_text,
        requires=draft.requires.model_dump(),
    )
    text, _ = job_texts(job)
    assert "equal opportunity" not in text.lower() and "raised" not in text.lower() and "gym" not in text.lower()
