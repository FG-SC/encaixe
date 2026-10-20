"""Taxonomy matching, seniority, languages, geography and company identity."""

from __future__ import annotations

from datetime import date

import pytest
from sqlmodel import Session

from app.companies import get_or_create_company, normalize
from app.geo import haversine_km, tz_overlap_hours
from app.geo import load as load_geo
from app.taxonomy import load as load_tax

TRICKY = [
    ("Experiência com R e Python", {"r", "python"}),
    ("Go to market strategy", set()),
    ("excel at communication", set()),
    ("react quickly to incidents", set()),
    ("conhecimento em IA generativa", {"llm"}),
    ("Power BI (DAX)", {"power_bi", "dax"}),
    ("ML Engineer", {"machine_learning"}),
    ("100 ml de água", set()),
    ("Salário R$ 5.000", set()),
    ("Desenvolvedor Go e React", {"go", "react"}),
    ("Node.js, C# e .NET", {"node_js", "c_sharp", "dotnet"}),
    ("PL/SQL e Oracle", {"oracle_db"}),
    ("Experiência com PyTorch e deep learning", {"pytorch", "deep_learning"}),
    ("Dashboards em Excel", {"data_visualization", "excel"}),
]


@pytest.mark.parametrize(("text", "expected"), TRICKY)
def test_skill_matching(text: str, expected: set[str]) -> None:
    assert set(load_tax().skill_ids(text)) == expected


def test_taxonomy_structure() -> None:
    t = load_tax()
    assert len(t.skills) >= 120
    assert t.parent("pytorch") == "deep_learning" and t.parent("deep_learning") == "machine_learning"
    assert t.related("pytorch", "deep_learning") and not t.related("pytorch", "machine_learning")
    assert t.job_domains(["sales", "negotiation", "crm", "excel"]) == ["business"]
    assert t.domain("excel") is None and t.domains("git") == set()  # transversal
    assert {"analytics", "ml", "backend"} <= t.domains("python")


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("Analista de Dados Jr", 2),
        ("Engenheiro de Dados Pleno/Sênior", 3),
        ("Data Engineer II", 3),
        ("Estagiária de BI", 1),
        ("Tech Lead", 5),
        ("Sales Manager", 4),
        ("Product Manager", None),
        ("Senior Sistemas - Analista", None),
        ("Cientista de Dados", None),
    ],
)
def test_seniority_from_title(title: str, level: int | None) -> None:
    m = load_tax().seniority_from_title(title)
    assert (m.level if m else None) == level


def test_languages() -> None:
    found = [(m.language, m.level) for m in load_tax().find_languages("Inglês avançado e espanhol básico")]
    assert found == [("en", "advanced"), ("es", "basic")]
    assert [(m.language, m.level) for m in load_tax().find_languages("Fluent English")] == [("en", "fluent")]


@pytest.mark.parametrize(
    ("text", "city"),
    [
        ("Florianópolis, SC", "florianopolis-sc-br"),
        ("São José - SC", "sao-jose-sc-br"),
        ("San Jose, CA", "san-jose-ca-us"),
        ("San José, Costa Rica", "san-jose-cr"),
        ("Floripa", "florianopolis-sc-br"),
        ("Joinville/SC", "joinville-sc-br"),
        ("Washington, DC", "washington-dc-us"),
    ],
)
def test_find_city(text: str, city: str) -> None:
    m = load_geo().find_city(text)
    assert m is not None and m.city_id == city


def test_eligibility_phrases() -> None:
    g = load_geo()
    assert g.find_eligibility("Must be located in the United States") == ["US"]
    assert g.find_eligibility("We are located in São Paulo and hire globally") == []
    assert g.find_eligibility("Remoto - Brasil") == ["BR"]
    assert g.find_eligibility("Remote, worldwide") == []
    assert "BR" in g.find_eligibility("Remote (LATAM)") and "US" not in g.find_eligibility("Remote (LATAM)")


def test_distance_and_workday_overlap() -> None:
    g = load_geo()
    km = haversine_km(g.get_city("florianopolis-sc-br"), g.get_city("sao-paulo-sp-br"))  # type: ignore[arg-type]
    assert 480 < km < 500
    assert tz_overlap_hours("America/Sao_Paulo", "America/Sao_Paulo", date(2026, 10, 20), 9, 18) == 9
    assert tz_overlap_hours("America/Sao_Paulo", "Europe/Berlin", date(2026, 10, 20), 9, 18) == 4
    assert tz_overlap_hours("America/Sao_Paulo", "Asia/Tokyo", date(2026, 10, 20), 9, 18) == 0


def test_company_identity(session: Session) -> None:
    assert normalize("Google LLC") == normalize("google") == "google"
    assert normalize("Acme Brasil Ltda. - ME") == "acme brasil"
    a = get_or_create_company(session, "Google LLC")
    b = get_or_create_company(session, "google")
    assert a is not None and b is not None and a.id == b.id and "google" in b.aliases
