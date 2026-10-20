"""Generate app/seed/seed_jobs.json: 60 fictional jobs (PT and EN) for tests and offline mode.

Deterministic. Every company is fictional. Each job carries ``expected`` (the taxonomy ids of its
required skills, its arrangement and seniority) so tests can measure the heuristic extractor.

    python tools/gen_seed_jobs.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "seed" / "seed_jobs.json"

# (title, company, lang, location_text, arrangement, seniority, must[(phrase, id)], nice[phrases],
#  salary (min, max, currency, period) | None, extras)
M = {
    "sql": ("SQL", "sql"),
    "python": ("Python", "python"),
    "pbi": ("Power BI", "power_bi"),
    "dax": ("DAX", "dax"),
    "excel": ("Excel avançado", "excel"),
    "stats": ("estatística", "statistics"),
    "tableau": ("Tableau", "tableau"),
    "looker": ("Looker", "looker"),
    "pandas": ("pandas", "pandas"),
    "ab": ("testes A/B", "a_b_testing"),
    "dataviz": ("visualização de dados", "data_visualization"),
    "ml": ("machine learning", "machine_learning"),
    "dl": ("deep learning", "deep_learning"),
    "pytorch": ("PyTorch", "pytorch"),
    "tf": ("TensorFlow", "tensorflow"),
    "sklearn": ("scikit-learn", "scikit_learn"),
    "nlp": ("NLP", "nlp"),
    "cv": ("visão computacional", "computer_vision"),
    "llm": ("LLMs", "llm"),
    "rag": ("RAG", "rag"),
    "langchain": ("LangChain", "langchain"),
    "mlops": ("MLOps", "mlops"),
    "mlflow": ("MLflow", "mlflow"),
    "ts": ("séries temporais", "time_series"),
    "recsys": ("sistemas de recomendação", "recommender_systems"),
    "spark": ("Spark", "spark"),
    "airflow": ("Airflow", "airflow"),
    "dbt": ("dbt", "dbt"),
    "kafka": ("Kafka", "kafka"),
    "bigquery": ("BigQuery", "bigquery"),
    "snowflake": ("Snowflake", "snowflake"),
    "aws": ("AWS", "aws"),
    "gcp": ("GCP", "gcp"),
    "azure": ("Azure", "azure"),
    "docker": ("Docker", "docker"),
    "k8s": ("Kubernetes", "kubernetes"),
    "terraform": ("Terraform", "terraform"),
    "git": ("Git", "git"),
    "ci": ("CI/CD", "ci_cd"),
    "linux": ("Linux", "linux"),
    "java": ("Java", "java"),
    "spring": ("Spring Boot", "spring"),
    "go": ("Golang", "go"),
    "node": ("Node.js", "node_js"),
    "ts_lang": ("TypeScript", "typescript"),
    "react": ("React", "react"),
    "csharp": ("C#", "c_sharp"),
    "dotnet": (".NET", "dotnet"),
    "php": ("PHP", "php"),
    "laravel": ("Laravel", "laravel"),
    "ruby": ("Ruby", "ruby"),
    "rails": ("Rails", "rails"),
    "django": ("Django", "django"),
    "fastapi": ("FastAPI", "fastapi"),
    "rest": ("APIs REST", "rest_api"),
    "postgres": ("PostgreSQL", "postgresql"),
    "mongo": ("MongoDB", "mongodb"),
    "redis": ("Redis", "redis"),
    "micro": ("microsserviços", "microservices"),
    "sales": ("vendas B2B", "sales"),
    "crm": ("CRM", "crm"),
    "nego": ("negociação", "negotiation"),
    "salesforce": ("Salesforce", "salesforce"),
    "account": ("gestão de contas", "account_management"),
    "marketing": ("marketing digital", "marketing"),
    "people": ("gestão de pessoas", "people_management"),
    "pm": ("gestão de projetos", "project_management"),
    "fin": ("análise financeira", "financial_analysis"),
    "research": ("pesquisa científica", "scientific_research"),
    "causal": ("inferência causal", "causal_inference"),
    "bayes": ("métodos bayesianos", "bayesian_methods"),
    "writing": ("escrita acadêmica", "academic_writing"),
    "exp": ("desenho experimental", "experimental_design"),
    "r": ("linguagem R", "r"),
    "html": ("HTML", "html"),
    "css": ("CSS", "css"),
    "vue": ("Vue.js", "vue"),
    "observ": ("observabilidade", "observability"),
    "graphql": ("GraphQL", "graphql"),
}

E = {  # English phrases for the same ids
    "excel": "advanced Excel",
    "stats": "statistics",
    "ab": "A/B testing",
    "dataviz": "data visualization",
    "cv": "computer vision",
    "ts": "time series",
    "recsys": "recommender systems",
    "rest": "REST APIs",
    "micro": "microservices",
    "sales": "B2B sales",
    "nego": "negotiation",
    "account": "account management",
    "marketing": "digital marketing",
    "people": "people management",
    "pm": "project management",
    "fin": "financial analysis",
    "research": "scientific research",
    "causal": "causal inference",
    "bayes": "Bayesian methods",
    "writing": "academic writing",
    "exp": "experimental design",
    "r": "R language",
    "observ": "observability",
}

JOBS = [
    # ---------------------------------------------------------------- analytics (PT)
    (
        "Analista de Dados Júnior",
        "Tainha Analytics",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        2,
        ["sql", "python", "pbi"],
        ["dbt", "git"],
        (4500, 6000, "BRL", "month"),
        {"about": True},
    ),
    (
        "Analista de BI",
        "Garapuvu Sistemas",
        "pt",
        "São José, SC",
        "hybrid",
        3,
        ["sql", "pbi", "dax"],
        ["python", "excel"],
        (6000, 8000, "BRL", "month"),
        {"benefits": True},
    ),
    (
        "Analista de Dados Pleno",
        "Corvina Pagamentos",
        "pt",
        "Florianópolis, SC",
        "remote",
        3,
        ["sql", "python", "stats", "pbi"],
        ["airflow"],
        None,
        {"about_funding": True, "years": 3},
    ),
    (
        "Analista de Dados Sênior",
        "Atlântica Seguros",
        "pt",
        "Joinville, SC",
        "onsite",
        4,
        ["sql", "python", "stats", "tableau"],
        ["spark", "aws"],
        (11000, 14000, "BRL", "month"),
        {"years": 5},
    ),
    (
        "Estágio em Dados",
        "Ilha Dados",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        1,
        ["sql", "excel"],
        ["python", "pbi"],
        (1800, 1800, "BRL", "month"),
        {"bolsa": True},
    ),
    (
        "Analytics Engineer Pleno",
        "Lagoa Labs",
        "pt",
        "Remoto (Brasil)",
        "remote",
        3,
        ["sql", "dbt", "bigquery", "python"],
        ["airflow", "looker"],
        None,
        {},
    ),
    (
        "Analista de Business Intelligence Sênior",
        "Serra Azul Energia",
        "pt",
        "Lages, SC",
        "onsite",
        4,
        ["sql", "pbi", "dax", "dataviz"],
        ["python"],
        (9000, 12000, "BRL", "month"),
        {},
    ),
    (
        "Analista de Dados Júnior (Power BI)",
        "Blumenau Têxtil Digital",
        "pt",
        "Blumenau, SC",
        "onsite",
        2,
        ["pbi", "excel", "sql"],
        ["python"],
        (3500, 4200, "BRL", "month"),
        {},
    ),
    (
        "Analista de Dados de Marketing",
        "Mané Software",
        "pt",
        "Palhoça, SC",
        "hybrid",
        3,
        ["sql", "python", "ab"],
        ["looker", "marketing"],
        None,
        {"eeo": True},
    ),
    (
        "Analista de Dados Pleno",
        "Sampa Varejo Online",
        "pt",
        "São Paulo, SP",
        "onsite",
        3,
        ["sql", "python", "pbi"],
        ["spark"],
        (8000, 10000, "BRL", "month"),
        {},
    ),
    # ---------------------------------------------------------------- analytics (EN)
    (
        "Data Analyst",
        "Bluecrest Analytics Inc.",
        "en",
        "Remote - LATAM",
        "remote",
        3,
        ["sql", "python", "looker", "ab"],
        ["dbt"],
        (3000, 4000, "USD", "month"),
        {"tz": "Overlap with 9am-1pm ET", "english": "Fluent"},
    ),
    (
        "Product Analyst",
        "Polaris Commerce GmbH",
        "en",
        "Remote (Europe)",
        "remote",
        3,
        ["sql", "python", "ab", "stats"],
        ["tableau"],
        (55000, 70000, "EUR", "year"),
        {"tz": "CET business hours", "english": "Fluent"},
    ),
    # ---------------------------------------------------------------- ML / LLM
    (
        "Cientista de Dados Júnior",
        "Catarina Agro Inteligência",
        "pt",
        "Chapecó, SC",
        "hybrid",
        2,
        ["python", "sql", "ml", "stats"],
        ["sklearn", "ts"],
        (5000, 7000, "BRL", "month"),
        {},
    ),
    (
        "Cientista de Dados Pleno",
        "Corvina Pagamentos",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        3,
        ["python", "sql", "ml", "sklearn"],
        ["mlflow", "aws"],
        (9000, 12000, "BRL", "month"),
        {"years": 3},
    ),
    (
        "Cientista de Dados Sênior",
        "Butiá Saúde Digital",
        "pt",
        "Remoto (Brasil)",
        "remote",
        4,
        ["python", "ml", "stats", "causal"],
        ["pytorch", "spark"],
        None,
        {"years": 5, "english": "Avançado"},
    ),
    (
        "Machine Learning Engineer Pleno",
        "Lagoa Labs",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        3,
        ["python", "ml", "docker", "mlops"],
        ["k8s", "gcp"],
        (10000, 13000, "BRL", "month"),
        {},
    ),
    (
        "Engenheiro de LLM",
        "Mangue Labs",
        "pt",
        "Remoto (Brasil)",
        "remote",
        3,
        ["python", "llm", "rag", "langchain"],
        ["docker", "aws"],
        (12000, 16000, "BRL", "month"),
        {},
    ),
    (
        "Senior Machine Learning Engineer",
        "Kestrel AI Ltd.",
        "en",
        "Remote - US only",
        "remote",
        4,
        ["python", "pytorch", "dl", "mlops"],
        ["k8s", "aws"],
        (170000, 210000, "USD", "year"),
        {"us_citizen": True, "tz": "Overlap with 10am-4pm PT", "years": 5},
    ),
    (
        "NLP Engineer",
        "Andes Fintech S.A.",
        "en",
        "Remote - LATAM",
        "remote",
        3,
        ["python", "nlp", "llm", "pytorch"],
        ["rag"],
        (4000, 5500, "USD", "month"),
        {"english": "Fluent"},
    ),
    (
        "Engenheira(o) de Visão Computacional",
        "Joinvalle Mobilidade",
        "pt",
        "Joinville, SC",
        "onsite",
        3,
        ["python", "cv", "dl", "pytorch"],
        ["docker"],
        (9000, 11000, "BRL", "month"),
        {},
    ),
    (
        "MLOps Engineer",
        "Nimbus Remote Inc.",
        "en",
        "Remote, worldwide",
        "remote",
        4,
        ["python", "mlops", "k8s", "docker", "terraform"],
        ["mlflow"],
        None,
        {"about_funding_en": True},
    ),
    (
        "Cientista de Dados (Recomendação)",
        "Carioca Streaming",
        "pt",
        "Rio de Janeiro, RJ",
        "hybrid",
        3,
        ["python", "recsys", "ml", "spark"],
        ["aws"],
        None,
        {},
    ),
    (
        "Staff Machine Learning Scientist",
        "Kestrel AI Ltd.",
        "en",
        "Remote - US only",
        "remote",
        5,
        ["python", "ml", "dl", "research"],
        ["causal"],
        (230000, 280000, "USD", "year"),
        {"years": 9},
    ),
    # ---------------------------------------------------------------- data engineering
    (
        "Engenheiro de Dados Júnior",
        "Ilha Dados",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        2,
        ["python", "sql", "airflow"],
        ["spark", "docker"],
        (5000, 6500, "BRL", "month"),
        {},
    ),
    (
        "Engenheiro de Dados Pleno",
        "Pampa Logística",
        "pt",
        "Porto Alegre, RS",
        "onsite",
        3,
        ["python", "spark", "airflow", "sql"],
        ["aws", "kafka"],
        (10000, 12000, "BRL", "month"),
        {},
    ),
    (
        "Engenheira(o) de Dados Sênior",
        "Cerrado Agro",
        "pt",
        "Remoto (Brasil)",
        "remote",
        4,
        ["python", "spark", "kafka", "aws"],
        ["terraform"],
        (15000, 19000, "BRL", "month"),
        {"years": 5},
    ),
    (
        "Data Engineer",
        "Bluecrest Analytics Inc.",
        "en",
        "Remote - LATAM",
        "remote",
        3,
        ["python", "sql", "snowflake", "dbt", "airflow"],
        ["kafka"],
        (4500, 6000, "USD", "month"),
        {"tz": "Overlap with 9am-1pm ET", "english": "Fluent"},
    ),
    (
        "Big Data Engineer",
        "Minas Dados & Café",
        "pt",
        "Belo Horizonte, MG",
        "hybrid",
        3,
        ["spark", "python", "gcp", "bigquery"],
        ["airflow"],
        None,
        {},
    ),
    (
        "Analista de Engenharia de Dados",
        "Amazônia Bio Dados",
        "pt",
        "Manaus, AM",
        "onsite",
        3,
        ["sql", "python", "azure"],
        ["spark"],
        (7000, 9000, "BRL", "month"),
        {},
    ),
    # ---------------------------------------------------------------- research
    (
        "Pesquisador(a) em Inteligência Artificial",
        "Instituto Lagoa de Pesquisa (fictício)",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        3,
        ["python", "research", "ml", "writing"],
        ["pytorch"],
        (6500, 6500, "BRL", "month"),
        {"bolsa": True},
    ),
    (
        "Research Scientist, NLP",
        "Kestrel AI Ltd.",
        "en",
        "London, UK",
        "onsite",
        4,
        ["research", "nlp", "pytorch", "writing"],
        ["llm"],
        (80000, 100000, "GBP", "year"),
        {},
    ),
    (
        "Pesquisador(a) Estatístico(a)",
        "Atlântica Seguros",
        "pt",
        "Florianópolis, SC",
        "onsite",
        3,
        ["stats", "r", "exp", "bayes"],
        ["python"],
        (8000, 9500, "BRL", "month"),
        {},
    ),
    (
        "Cientista de Pesquisa em Inferência Causal",
        "Corvina Pagamentos",
        "pt",
        "Remoto (Brasil)",
        "remote",
        4,
        ["causal", "stats", "python", "exp"],
        ["ab"],
        None,
        {},
    ),
    # ---------------------------------------------------------------- backend
    (
        "Desenvolvedor Python Pleno",
        "Garapuvu Sistemas",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        3,
        ["python", "django", "postgres", "rest"],
        ["docker", "redis"],
        (8000, 10500, "BRL", "month"),
        {},
    ),
    (
        "Backend Engineer (Go)",
        "Nimbus Remote Inc.",
        "en",
        "Remote, worldwide",
        "remote",
        4,
        ["go", "micro", "postgres", "k8s"],
        ["kafka"],
        (6000, 8000, "USD", "month"),
        {"english": "Fluent"},
    ),
    (
        "Desenvolvedor Java Sênior",
        "Atlântica Seguros",
        "pt",
        "Joinville, SC",
        "hybrid",
        4,
        ["java", "spring", "micro", "postgres"],
        ["aws", "kafka"],
        (13000, 16000, "BRL", "month"),
        {},
    ),
    (
        "Desenvolvedora Node.js Pleno",
        "Sampa Varejo Online",
        "pt",
        "Remoto (Brasil)",
        "remote",
        3,
        ["node", "ts_lang", "rest", "mongo"],
        ["docker"],
        None,
        {},
    ),
    (
        "Desenvolvedor .NET Pleno",
        "Serra Azul Energia",
        "pt",
        "Criciúma, SC",
        "onsite",
        3,
        ["csharp", "dotnet", "sql", "rest"],
        ["azure"],
        (7000, 9000, "BRL", "month"),
        {},
    ),
    (
        "Desenvolvedor Backend Júnior (FastAPI)",
        "Mané Software",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        2,
        ["python", "fastapi", "postgres", "git"],
        ["docker"],
        (4000, 5500, "BRL", "month"),
        {},
    ),
    (
        "Desenvolvedor PHP/Laravel Pleno",
        "Orla Turismo Digital",
        "pt",
        "Balneário Camboriú, SC",
        "onsite",
        3,
        ["php", "laravel", "sql", "rest"],
        ["vue"],
        (6000, 7500, "BRL", "month"),
        {},
    ),
    (
        "Senior Ruby on Rails Engineer",
        "Polaris Commerce GmbH",
        "en",
        "Berlin, Germany",
        "onsite",
        4,
        ["ruby", "rails", "postgres", "redis"],
        ["graphql"],
        (75000, 90000, "EUR", "year"),
        {"english": "Fluent"},
    ),
    (
        "Staff Backend Engineer",
        "Andes Fintech S.A.",
        "en",
        "Remote - LATAM",
        "remote",
        5,
        ["java", "micro", "kafka", "aws"],
        ["k8s"],
        (9000, 11000, "USD", "month"),
        {"years": 10},
    ),
    (
        "Desenvolvedor(a) Backend Pleno",
        "Joinvalle Mobilidade",
        "pt",
        "Itajaí, SC",
        "hybrid",
        3,
        ["python", "rest", "postgres", "docker"],
        ["aws"],
        (2500, 3000, "BRL", "month"),
        {},
    ),
    # ---------------------------------------------------------------- frontend / devops
    (
        "Desenvolvedora Frontend React Pleno",
        "Tainha Analytics",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        3,
        ["react", "ts_lang", "html", "css"],
        ["graphql"],
        (7500, 9500, "BRL", "month"),
        {},
    ),
    (
        "DevOps Engineer Sênior",
        "Cerrado Agro",
        "pt",
        "Remoto (Brasil)",
        "remote",
        4,
        ["aws", "terraform", "k8s", "ci"],
        ["observ"],
        (14000, 17000, "BRL", "month"),
        {},
    ),
    (
        "Site Reliability Engineer",
        "Nimbus Remote Inc.",
        "en",
        "Remote, worldwide",
        "remote",
        4,
        ["k8s", "linux", "observ", "go"],
        ["terraform"],
        None,
        {"tz": "UTC-3 to UTC+1 overlap"},
    ),
    (
        "Engenheiro de Cloud AWS",
        "Pampa Logística",
        "pt",
        "Curitiba, PR",
        "hybrid",
        3,
        ["aws", "terraform", "docker", "linux"],
        ["python"],
        (9500, 12000, "BRL", "month"),
        {},
    ),
    (
        "Desenvolvedor Fullstack Júnior",
        "Ilha Dados",
        "pt",
        "São José, SC",
        "hybrid",
        2,
        ["react", "node", "sql", "git"],
        ["docker"],
        (4000, 5000, "BRL", "month"),
        {},
    ),
    (
        "Frontend Engineer (Vue)",
        "Bluecrest Analytics Inc.",
        "en",
        "Remote - LATAM",
        "remote",
        3,
        ["vue", "ts_lang", "css"],
        ["react"],
        (3500, 4500, "USD", "month"),
        {"english": "Fluent"},
    ),
    # ---------------------------------------------------------------- out of area (business)
    (
        "Sales Manager",
        "Polaris Commerce GmbH",
        "en",
        "Florianópolis, SC",
        "hybrid",
        4,
        ["sales", "crm", "nego", "account"],
        ["salesforce", "excel"],
        (12000, 15000, "BRL", "month"),
        {"years": 6},
    ),
    (
        "Executivo(a) de Vendas",
        "Corvina Pagamentos",
        "pt",
        "Florianópolis, SC",
        "hybrid",
        3,
        ["sales", "nego", "crm"],
        ["salesforce"],
        (5000, 7000, "BRL", "month"),
        {},
    ),
    (
        "Gerente Comercial",
        "Blumenau Têxtil Digital",
        "pt",
        "Blumenau, SC",
        "onsite",
        4,
        ["sales", "people", "nego"],
        ["crm"],
        (15000, 18000, "BRL", "month"),
        {},
    ),
    (
        "Customer Success Manager",
        "Lagoa Labs",
        "en",
        "Remote (Brazil)",
        "remote",
        None,
        ["account", "crm", "nego"],
        ["salesforce"],
        None,
        {},
    ),
    (
        "Gerente de Marketing",
        "Orla Turismo Digital",
        "pt",
        "Itajaí, SC",
        "onsite",
        4,
        ["marketing", "people", "pm"],
        ["excel"],
        (10000, 13000, "BRL", "month"),
        {},
    ),
    (
        "Analista Financeiro Pleno",
        "Atlântica Seguros",
        "pt",
        "Florianópolis, SC",
        "onsite",
        3,
        ["fin", "excel"],
        ["sql"],
        (6000, 7500, "BRL", "month"),
        {},
    ),
    # ---------------------------------------------------------------- misc to exercise filters
    (
        "Head of Data",
        "Sampa Varejo Online",
        "en",
        "São Paulo, Brazil",
        "onsite",
        5,
        ["sql", "python", "people", "ml"],
        ["aws"],
        (30000, 38000, "BRL", "month"),
        {"years": 12},
    ),
    (
        "Principal Data Scientist",
        "Kestrel AI Ltd.",
        "en",
        "New York, NY",
        "onsite",
        6,
        ["python", "ml", "causal", "stats"],
        ["research"],
        (260000, 320000, "USD", "year"),
        {"us_citizen": True, "years": 12},
    ),
    (
        "Analista de Dados Júnior",
        "Mangue Labs",
        "pt",
        "Recife, PE",
        "onsite",
        2,
        ["sql", "python", "pbi"],
        ["excel"],
        (3800, 4800, "BRL", "month"),
        {},
    ),
    (
        "Analista de Dados",
        "Minas Dados & Café",
        "pt",
        "Remoto (Brasil)",
        "remote",
        None,
        ["sql", "pbi", "python"],
        ["dbt"],
        (2000, 2600, "BRL", "month"),
        {},
    ),
    (
        "Data Scientist",
        "Kestrel AI Ltd.",
        "en",
        "Remote - US only",
        "remote",
        3,
        ["python", "sql", "ml", "stats"],
        ["pytorch"],
        (130000, 150000, "USD", "year"),
        {"us_citizen": True},
    ),
]


# Synthetic B side (spec 5.3): 5 fictional companies, one recruiter each, 1-3 platform jobs.
# Lumen Dados / Carla has no preloaded job: her "ML Engineer Jr" is app/seed/personas/lumen_ml_engineer_jr.txt.
RECRUITERS = [
    ("Lumen Dados", "Carla Menezes", []),
    (
        "Tainha Analytics",
        "Rafael Duarte",
        [
            (
                "Analista de Dados Pleno",
                "Tainha Analytics",
                "pt",
                "Florianópolis, SC",
                "hybrid",
                3,
                ["sql", "python", "pbi", "stats"],
                ["dbt"],
                (7000, 9000, "BRL", "month"),
                {},
            ),
            (
                "Cientista de Dados Júnior",
                "Tainha Analytics",
                "pt",
                "Florianópolis, SC",
                "hybrid",
                2,
                ["python", "sql", "ml"],
                ["sklearn"],
                (5500, 7000, "BRL", "month"),
                {},
            ),
        ],
    ),
    (
        "Vale Sul Energia",
        "Juliana Prado",
        [
            (
                "Engenheiro de Dados Pleno",
                "Vale Sul Energia",
                "pt",
                "Joinville, SC",
                "hybrid",
                3,
                ["python", "sql", "airflow", "spark"],
                ["aws"],
                (9000, 11500, "BRL", "month"),
                {},
            ),
            (
                "Analista de BI Júnior",
                "Vale Sul Energia",
                "pt",
                "Joinville, SC",
                "onsite",
                2,
                ["sql", "pbi", "excel"],
                ["dax"],
                (4000, 5000, "BRL", "month"),
                {},
            ),
        ],
    ),
    (
        "Ondina Saúde",
        "Marcos Teixeira",
        [
            (
                "Cientista de Dados Pleno",
                "Ondina Saúde",
                "pt",
                "Blumenau, SC",
                "remote",
                3,
                ["python", "ml", "stats", "sql"],
                ["nlp"],
                None,
                {},
            ),
        ],
    ),
    (
        "Farol Fintech",
        "Beatriz Nunes",
        [
            (
                "Desenvolvedor Python Sênior",
                "Farol Fintech",
                "pt",
                "Remoto (Brasil)",
                "remote",
                4,
                ["python", "fastapi", "postgres", "docker"],
                ["aws"],
                (14000, 17000, "BRL", "month"),
                {"years": 5},
            ),
            (
                "Analista de Dados Júnior",
                "Farol Fintech",
                "pt",
                "Remoto (Brasil)",
                "remote",
                2,
                ["sql", "python", "pbi"],
                ["dbt"],
                (4500, 5500, "BRL", "month"),
                {},
            ),
            (
                "Engenheiro de Machine Learning Pleno",
                "Farol Fintech",
                "pt",
                "Remoto (Brasil)",
                "remote",
                3,
                ["python", "ml", "mlops", "docker"],
                ["k8s"],
                (11000, 14000, "BRL", "month"),
                {},
            ),
        ],
    ),
]


def phrase(key: str, lang: str) -> str:
    return E.get(key, M[key][0]) if lang == "en" else M[key][0]


def money(lo: float, hi: float, cur: str, period: str, lang: str) -> str:
    sym = {"BRL": "R$ ", "USD": "$", "EUR": "€", "GBP": "£"}[cur]

    def fmt(x: float) -> str:
        if cur == "BRL":
            return f"{int(x):,}".replace(",", ".")
        return f"{int(x):,}"

    per = {
        ("pt", "month"): "por mês",
        ("pt", "year"): "por ano",
        ("en", "month"): "per month",
        ("en", "year"): "per year",
    }[(lang, period)]
    if lo == hi:
        return f"{sym}{fmt(lo)} {per}"
    sep = " a " if lang == "pt" else " - "
    return f"{sym}{fmt(lo)}{sep}{sym}{fmt(hi)} {per}"


def render(spec: tuple, rng: random.Random) -> str:
    title, company, lang, location, arrangement, seniority, must, nice, salary, extra = spec
    pt = lang == "pt"
    arr_pt = {"remote": "remoto", "hybrid": "híbrido", "onsite": "presencial"}[arrangement]
    arr_en = {"remote": "remote", "hybrid": "hybrid", "onsite": "on-site"}[arrangement]
    lines: list[str] = []
    if extra.get("about") or extra.get("about_funding") or extra.get("about_funding_en") or rng.random() < 0.35:
        lines.append("Sobre nós" if pt else "About us")
        if extra.get("about_funding"):
            lines.append(f"A {company} captou R$ 40 milhões em 2025 e atende 2 milhões de clientes no Sul do Brasil.")
        elif extra.get("about_funding_en"):
            lines.append(f"{company} raised $30M in a Series B and serves 100M customers worldwide.")
        elif pt:
            lines.append(
                f"A {company} é uma empresa fictícia que usa dados para resolver problemas reais, "
                "com times pequenos e autonomia. Usamos Python e IA em tudo o que fazemos."
            )
        else:
            lines.append(
                f"{company} is a fictional company building data products with small, autonomous teams. "
                "We love Python and AI."
            )
        lines.append("")
    lines.append("O que você vai fazer" if pt else "What you'll do")
    main = phrase(must[0], lang)
    second = phrase(must[1], lang) if len(must) > 1 else main
    if pt:
        lines += [
            f"• Trabalhar no dia a dia com {main} e {second} em problemas do negócio.",
            "• Colaborar com produto e engenharia para entregar com qualidade.",
            f"• Modelo de trabalho {arr_pt}.",
        ]
    else:
        lines += [
            f"• Work with {main} and {second} on real business problems.",
            "• Partner with product and engineering to ship high-quality work.",
            f"• This is a {arr_en} role.",
        ]
    lines.append("")
    lines.append("Requisitos" if pt else "Requirements")
    if extra.get("years"):
        n = extra["years"]
        lines.append(f"• {n}+ anos de experiência na área" if pt else f"• {n}+ years of professional experience")
    for k in must:
        lines.append(f"• {phrase(k, lang)}")
    if extra.get("english"):
        lines.append(f"• Inglês {extra['english'].lower()}" if pt else f"• {extra['english']} English")
    if extra.get("us_citizen"):
        lines.append("• Must be a U.S. citizen and authorized to work in the United States")
    lines.append("")
    if nice:
        lines.append("Diferenciais" if pt else "Nice to have")
        lines += [f"• {phrase(k, lang)}" for k in nice]
        lines.append("")
    if salary or extra.get("tz") or extra.get("bolsa"):
        lines.append("Remuneração e modelo" if pt else "Compensation and location")
        if salary:
            lo, hi, cur, period = salary
            if extra.get("bolsa"):
                lines.append(f"Bolsa de {money(lo, hi, cur, period, lang)}.")
            elif pt:
                lines.append(f"Salário: {money(lo, hi, cur, period, lang)}, CLT.")
            else:
                lines.append(f"Salary range: {money(lo, hi, cur, period, lang)}.")
        if extra.get("tz"):
            lines.append(extra["tz"] + ".")
        lines.append("")
    if extra.get("benefits") or rng.random() < 0.3:
        lines.append("Benefícios" if pt else "Benefits")
        lines.append(
            "Plano de saúde, vale-refeição e auxílio home office."
            if pt
            else "Health insurance, learning budget and home-office stipend."
        )
        lines.append("")
    if extra.get("eeo") or rng.random() < 0.3:
        lines.append(
            "Valorizamos a diversidade: todas as pessoas candidatas serão consideradas sem distinção de gênero, "
            "raça ou idade."
            if pt
            else "We are an equal opportunity employer and value diversity at our company."
        )
    return "\n".join(lines).strip()


_LEVEL_WORDS = (
    "júnior",
    "junior",
    "jr",
    "pleno",
    "sênior",
    "senior",
    "staff",
    "principal",
    "estágio",
    "head",
    "manager",
    "gerente",
)


def stated_seniority(title: str, seniority: int | None, extra: dict) -> int | None:
    """The level the TEXT states: a level word in the title, or years of experience; otherwise unknown."""
    words = title.lower().replace("(", " ").replace(")", " ").split()
    if any(w in _LEVEL_WORDS for w in words):
        return seniority
    return seniority if extra.get("years") else None


def expected_eligibility(location: str, extra: dict) -> str | None:
    """Country code or region key a job restricts candidates to."""
    if extra.get("us_citizen") or "US only" in location:
        return "US"
    if "LATAM" in location:
        return "LATAM"
    if "Europe" in location:
        return "EUROPE"
    if "Brasil" in location or "Brazil" in location and "Remote" in location:
        return "BR" if "Remot" in location else None
    return None


def main() -> None:
    rng = random.Random(42)
    out = []
    for i, spec in enumerate(JOBS, start=1):
        title, company, lang, location, arrangement, seniority, must, nice, salary, extra = spec
        out.append(
            {
                "id": f"seed-{i:03d}",
                "title": title,
                "company": company,
                "lang": lang,
                "location_text": location,
                "url": None,
                "description": render(spec, rng),
                "expected": {
                    "skills_must": [M[k][1] for k in must],
                    "arrangement": arrangement,
                    "seniority": stated_seniority(title, seniority, extra),
                    "has_salary": salary is not None,
                    "eligibility": expected_eligibility(location, extra),
                },
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} jobs to {OUT}")

    recruiters = []
    for company, name, jobs in RECRUITERS:
        recruiters.append(
            {
                "company": company,
                "recruiter": name,
                "jobs": [{"title": s[0], "location_text": s[3], "description": render(s, rng)} for s in jobs],
            }
        )
    rec_out = OUT.with_name("recruiters.json")
    rec_out.write_text(json.dumps(recruiters, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(recruiters)} recruiters to {rec_out}")


if __name__ == "__main__":
    main()
