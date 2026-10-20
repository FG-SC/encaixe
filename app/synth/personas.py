"""Synthetic candidates: dated experiences, education, taxonomy-consistent skills, SC-weighted cities.

Deterministic for a given seed. Names and companies are fictional. Each persona also carries a hidden
preference (``Taste``) used only by the simulation (histories, drift evaluation), never by the ranking.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

from app import geo as geo_mod
from app.schemas import CandidateProfile, EducationIn, ExperienceIn, LanguageLevel, Wants

DOMAIN_WEIGHTS = {
    "analytics": 0.24,
    "ml": 0.16,
    "data_eng": 0.15,
    "backend": 0.16,
    "frontend": 0.08,
    "devops": 0.07,
    "research": 0.05,
    "business": 0.09,
}
CORE = {
    "analytics": [
        "sql",
        "excel",
        "power_bi",
        "statistics",
        "python",
        "dax",
        "tableau",
        "looker",
        "data_visualization",
        "a_b_testing",
        "pandas",
    ],
    "ml": [
        "python",
        "machine_learning",
        "scikit_learn",
        "statistics",
        "sql",
        "pytorch",
        "deep_learning",
        "nlp",
        "llm",
        "mlops",
        "tensorflow",
        "computer_vision",
        "pandas",
    ],
    "data_eng": [
        "python",
        "sql",
        "spark",
        "airflow",
        "dbt",
        "kafka",
        "aws",
        "bigquery",
        "snowflake",
        "docker",
        "data_modeling",
    ],
    "backend": [
        "python",
        "java",
        "go",
        "node_js",
        "c_sharp",
        "django",
        "spring",
        "fastapi",
        "postgresql",
        "docker",
        "rest_api",
        "microservices",
        "redis",
    ],
    "frontend": ["javascript", "typescript", "react", "vue", "html", "css", "next_js", "tailwind"],
    "devops": ["docker", "kubernetes", "aws", "terraform", "ci_cd", "linux", "observability", "gcp"],
    "research": [
        "python",
        "statistics",
        "r",
        "scientific_research",
        "experimental_design",
        "causal_inference",
        "academic_writing",
    ],
    "business": ["sales", "crm", "negotiation", "account_management", "marketing", "project_management", "excel"],
}
TITLES = {
    "analytics": ["Analista de Dados", "Analista de BI", "Data Analyst"],
    "ml": ["Cientista de Dados", "ML Engineer", "Engenheiro de Machine Learning"],
    "data_eng": ["Engenheiro de Dados", "Data Engineer"],
    "backend": ["Desenvolvedor Backend", "Backend Engineer", "Desenvolvedor Python"],
    "frontend": ["Desenvolvedor Frontend", "Frontend Engineer"],
    "devops": ["Engenheiro DevOps", "Site Reliability Engineer"],
    "research": ["Pesquisador", "Research Scientist"],
    "business": ["Executivo de Vendas", "Gerente de Contas"],
}
LEVEL_WORD = {1: "Estagiário", 2: "Júnior", 3: "Pleno", 4: "Sênior", 5: "Staff"}
LEVEL_WEIGHTS = {1: 0.08, 2: 0.30, 3: 0.32, 4: 0.20, 5: 0.10}
COMP_BY_LEVEL = {1: 1800, 2: 4500, 3: 8000, 4: 13000, 5: 19000}
FIRST = [
    "Ana",
    "Bruno",
    "Camila",
    "Diego",
    "Eduarda",
    "Felipe",
    "Gabriela",
    "Henrique",
    "Isabela",
    "João",
    "Karen",
    "Lucas",
    "Mariana",
    "Nicolas",
    "Olívia",
    "Pedro",
    "Quésia",
    "Rafael",
    "Sofia",
    "Tiago",
    "Úrsula",
    "Vinícius",
    "Yasmin",
    "Zeca",
    "Larissa",
    "Murilo",
    "Natália",
    "Otávio",
    "Priscila",
    "Renan",
]
LAST = [
    "Souza",
    "Lima",
    "Pereira",
    "Costa",
    "Rocha",
    "Almeida",
    "Nunes",
    "Barbosa",
    "Teixeira",
    "Moraes",
    "Farias",
    "Cardoso",
    "Ramos",
    "Pires",
    "Vieira",
    "Machado",
    "Freitas",
    "Correia",
    "Dias",
    "Monteiro",
]
COMPANY_A = [
    "Garoupa",
    "Ilhota",
    "Butiá",
    "Marés",
    "Ventos",
    "Araucária",
    "Lagoinha",
    "Pinhão",
    "Manezinho",
    "Tainhas",
    "Costão",
    "Joaquina",
    "Pântano",
    "Serra Geral",
    "Itaguaçu",
]
COMPANY_B = [
    "Tech",
    "Dados",
    "Software",
    "Analytics",
    "Sistemas",
    "Digital",
    "Labs",
    "Soluções",
    "Fintech",
    "Logística",
]


@dataclass
class Taste:
    """Hidden preference of a simulated person (the oracle). Never seen by the ranking."""

    domains: dict[str, float]  # affinity per taxonomy domain
    noise: float = 0.08
    drift_day: int | None = None  # simulation day when the preference changes
    drift_domains: dict[str, float] | None = None


@dataclass
class Persona:
    profile: CandidateProfile
    primary: str
    secondary: str | None
    level: int
    taste: Taste
    revision_day: int | None = None  # a relevant revision happens on this simulation day
    revised_profile: CandidateProfile | None = None
    extra: dict = field(default_factory=dict)


def _pick(rng: random.Random, weights: dict) -> object:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def _city(rng: random.Random) -> str:
    geo = geo_mod.load()
    sc = [c.id for c in geo.cities.values() if c.state == "SC" and c.country == "BR"]
    br = [c.id for c in geo.cities.values() if c.country == "BR" and c.state != "SC"]
    world = [c.id for c in geo.cities.values() if c.country != "BR"]
    r = rng.random()
    if r < 0.6:
        # Grande Florianópolis concentrates most of the SC tech market
        return rng.choice(sc[:9]) if rng.random() < 0.6 else rng.choice(sc)
    return rng.choice(br) if r < 0.9 else rng.choice(world)


def _month(year: int, month: int) -> date:
    while month < 1:
        year, month = year - 1, month + 12
    while month > 12:
        year, month = year + 1, month - 12
    return date(year, month, 1)


def make_persona(rng: random.Random, today: date, i: int) -> Persona:
    primary = str(_pick(rng, DOMAIN_WEIGHTS))
    secondary = (
        str(_pick(rng, {d: w for d, w in DOMAIN_WEIGHTS.items() if d != primary})) if rng.random() < 0.45 else None
    )
    level = int(_pick(rng, LEVEL_WEIGHTS))  # type: ignore[arg-type]
    n_exp = max(1, min(4, level + rng.choice([-1, 0, 0, 1])))
    core = CORE[primary]
    # Experiences, most recent first, contiguous with small gaps
    exps: list[ExperienceIn] = []
    end: date | None = None  # current job
    cursor = _month(today.year, today.month)
    for k in range(n_exp):
        lvl = max(1, level - k)
        months = rng.randint(10, 30) if lvl > 1 else rng.randint(6, 12)
        start = _month(cursor.year, cursor.month - months)
        domain = primary if (k == 0 or secondary is None or rng.random() < 0.7) else secondary
        pool = CORE[domain]
        skills = rng.sample(pool, k=min(len(pool), rng.randint(3, 6)))
        title = f"{rng.choice(TITLES[domain])} {LEVEL_WORD[lvl]}"
        company = f"{rng.choice(COMPANY_A)} {rng.choice(COMPANY_B)}"
        exps.append(
            ExperienceIn(
                company=company,
                role=title,
                seniority=lvl,
                start=start,
                end=end,
                skills_used=skills,
                responsibilities=f"Trabalho com {', '.join(skills[:3])} em projetos de {domain}.",
            )
        )
        end = _month(start.year, start.month - rng.randint(0, 3))
        cursor = end
    listed = rng.sample(core, k=min(len(core), rng.randint(2, 5)))
    city_id = _city(rng)
    city = geo_mod.load().cities[city_id]
    langs = [LanguageLevel(language="pt", level="native")] if city.country == "BR" else []
    langs.append(LanguageLevel(language="en", level=rng.choice(["basic", "intermediate", "advanced", "fluent"])))
    comp = COMP_BY_LEVEL[level] * rng.uniform(0.8, 1.25)
    arrangements = ["remote"] + [a for a in ("hybrid", "onsite") if rng.random() < 0.7]
    profile = CandidateProfile(
        name=f"{rng.choice(FIRST)} {rng.choice(LAST)} (sintético {i})",
        contact=f"pessoa{i}@exemplo.invalid",
        headline=exps[0].role,
        city_id=city_id,
        experiences=exps,
        education=[
            EducationIn(
                degree=rng.choice(["Bacharelado", "Tecnólogo", "Mestrado"]),
                field=rng.choice(
                    ["Ciência da Computação", "Estatística", "Engenharia", "Administração", "Sistemas de Informação"]
                ),
                institution="Universidade Fictícia",
                start=_month(exps[-1].start.year - 4, 3),  # type: ignore[union-attr]
                end=_month(exps[-1].start.year, 12),
            )
        ],  # type: ignore[union-attr]
        skills_listed=listed,
        languages=langs,
        wants=Wants(
            comp_min=round(comp, -2),
            arrangements=arrangements,  # type: ignore[arg-type]
            max_distance_km=float(rng.choice([30, 60, 100, 200])),
        ),
    )
    domains = {d: 0.1 for d in DOMAIN_WEIGHTS}
    domains[primary] = 1.0
    if secondary:
        domains[secondary] = 0.6
    return Persona(profile, primary, secondary, level, Taste(domains))


def with_revision(rng: random.Random, persona: Persona, day: int, sim_start: date) -> Persona:
    """A relevant revision mid-history: a new dated experience in another domain, and the taste follows it."""
    from datetime import timedelta

    target = persona.secondary or str(_pick(rng, {d: w for d, w in DOMAIN_WEIGHTS.items() if d != persona.primary}))
    moment = sim_start + timedelta(days=day)
    when = date(moment.year, moment.month, 1)
    skills = rng.sample(CORE[target], k=min(4, len(CORE[target])))
    old = persona.profile
    current = old.experiences[0]
    if current.start is not None and when <= current.start:
        when = _month(current.start.year, current.start.month + 1)
    closed = current.model_copy(update={"end": when})
    new_exp = ExperienceIn(
        company=current.company,
        role=f"{rng.choice(TITLES[target])} {LEVEL_WORD[persona.level]}",
        seniority=persona.level,
        start=when,
        end=None,
        skills_used=skills,
        responsibilities=f"Transição para {target}: {', '.join(skills)}.",
    )
    revised = old.model_copy(update={"experiences": [new_exp, closed, *old.experiences[1:]], "headline": new_exp.role})
    persona.revision_day = day
    persona.revised_profile = revised
    # A real switch, same breadth: the new area takes the place of the old one (which drops to the floor).
    # Keeping the old area at a middle value would make the taste broader, not different, and every ranking
    # would look like it "recovers" instantly.
    drift = {d: 0.1 for d in DOMAIN_WEIGHTS}
    drift[target] = 1.0
    persona.taste.drift_day = day
    persona.taste.drift_domains = drift
    return persona


def make_personas(
    n: int, seed: int, today: date, sim_start: date, sim_days: int, revision_share: float = 0.10
) -> list[Persona]:
    rng = random.Random(seed)
    personas = [make_persona(rng, today, i + 1) for i in range(n)]
    k = max(1, round(n * revision_share)) if n >= 5 else 0
    for p in rng.sample(personas, k=k):
        with_revision(rng, p, rng.randint(sim_days // 3, 2 * sim_days // 3), sim_start)
    return personas
