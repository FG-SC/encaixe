"""Every pt-BR sentence the user sees, in one place.

Tone (spec 9.7): direct, respectful, always with a next step. Never "reprovado"; always "não avançou".
Numbers always come in as parameters (they come from the data and from ``RULES``), never typed here.
"""

from __future__ import annotations

from app.config import RULES

# --------------------------------------------------------------------------- labels

REASON_LABELS_CANDIDATE: dict[str, str] = {
    "role_area": "área/cargo",
    "company": "empresa",
    "salary": "salário",
    "arrangement": "modalidade",
    "seniority": "senioridade",
}

REASON_LABELS_RECRUITER: dict[str, str] = {
    "skills": "skills",
    "seniority": "senioridade",
    "salary": "salário",
    "location": "local/modalidade",
    "language": "idioma",
    "job_filled": "vaga preenchida ou pausada",
}

ARRANGEMENT_LABELS: dict[str, str] = {"remote": "remota", "hybrid": "híbrida", "onsite": "presencial"}

REGIME_LABELS: dict[str, str] = {
    "clt": "CLT",
    "pj": "PJ",
    "internship": "estágio",
    "contractor": "contrato",
    "other": "outro",
}

PERIOD_LABELS: dict[str, str] = {"hour": "hora", "day": "dia", "week": "semana", "month": "mês", "year": "ano"}

LANGUAGE_LEVEL_LABELS: dict[str, str] = {
    "basic": "básico",
    "intermediate": "intermediário",
    "advanced": "avançado",
    "fluent": "fluente",
    "native": "nativo",
}

LANGUAGE_LABELS: dict[str, str] = {
    "en": "inglês",
    "es": "espanhol",
    "pt": "português",
    "fr": "francês",
    "de": "alemão",
    "it": "italiano",
}

BLIND_HIDDEN_LABELS: dict[str, str] = {
    "name": "nome",
    "contact": "contato",
    "photo": "foto",
    "age": "idade",
    "company_names": "nomes das empresas",
    "institution_names": "nomes das instituições de ensino",
}

CRITERION_LABELS: dict[str, str] = {
    "requirements": "Requisitos",
    "semantic": "Aderência semântica",
    "title": "Aderência de cargo",
    "seniority": "Senioridade",
    "salary": "Salário",
    "distance": "Modalidade e distância",
    "timezone": "Fuso",
    "history": "Histórico",
}

PILLAR_LABELS: dict[str, str] = {"atende": "Atende", "interessa": "Interessa", "historico": "Histórico"}

STATUS_LABELS: dict[str, str] = {
    "sent": "enviada",
    "seen": "vista pela empresa",
    "not_advanced": "não avançou",
    "matched": "encaixe",
}

BADGE_LABELS: dict[str, str] = {
    "good_fit": "bom encaixe",
    "explore": "sorteada para ampliar seu horizonte",
    "job_updated": "vaga atualizada",
    "profile_changed_since_rejection": "seu perfil mudou desde a recusa",
    "profile_updated_since_last_review": "perfil atualizado desde sua última avaliação",
    "applicant": "interessado(a)",
    "platform": "vaga da plataforma",
    "market": "vaga de mercado",
}

SOURCE_LABELS: dict[str, str] = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "github": "GitHub",
    "seed": "dados de exemplo",
    "platform": "Encaixe",
}


def seniority_label(level: int | None) -> str:
    if level is None:
        return "não informada"
    return RULES.seniority.ladder.get(level, f"L{level}")


def ordinal(n: int | float) -> str:
    """Portuguese ordinal for positions ("2ª"); half positions (ties) keep one decimal ("2,5ª")."""
    if float(n).is_integer():
        return f"{int(n)}ª"
    return f"{n:.1f}".replace(".", ",") + "ª"


def fmt_number(x: float, decimals: int = 0) -> str:
    """Brazilian number format: 12.345,6."""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_credit(x: float) -> str:
    """Requirement credits: 4 → "4", 4.5 → "4,5"."""
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}".replace(".", ",")


def fmt_money(amount: float, currency: str, period: str | None = "month") -> str:
    symbol = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}.get(currency, currency + " ")
    per = f"/{PERIOD_LABELS[period]}" if period else ""
    return f"{symbol} {fmt_number(amount)}{per}".replace("  ", " ")


def below_k_label() -> str:
    return f"<{RULES.privacy.k_anon}"


def k_anon_count(n: int) -> str:
    """Aggregates below k render as "<k" (spec 10)."""
    return below_k_label() if n < RULES.privacy.k_anon else str(n)


# --------------------------------------------------------------------------- filters

FILTER_TITLES: dict[str, str] = {
    "closed": "vagas fechadas",
    "not_visible": "perfis não visíveis para recrutadores",
    "arrangement_not_accepted": "modalidade que você não aceita",
    "beyond_distance": "presenciais ou híbridas fora da distância que você aceita",
    "country_eligibility": "exigem elegibilidade de país que você não tem",
    "salary_below_min": "salário abaixo do seu mínimo",
    "seniority_gap": "senioridade muito distante da sua",
    "out_of_area": "fora da sua área",
}

FILTER_ADJUST_HINTS: dict[str, str] = {
    "closed": "Nada a ajustar: a vaga não recebe mais candidaturas.",
    "not_visible": "O candidato escolheu não aparecer para recrutadores.",
    "arrangement_not_accepted": "Se quiser ver essas vagas, aceite essa modalidade nas suas preferências.",
    "beyond_distance": "Se quiser ver essas vagas, aumente a distância máxima nas suas preferências.",
    "country_eligibility": "A elegibilidade é definida pela empresa; não há ajuste no seu perfil.",
    "salary_below_min": "Se quiser ver essas vagas, reduza o salário mínimo nas suas preferências.",
    "seniority_gap": "A distância de senioridade só diminui com experiência registrada no perfil.",
    "out_of_area": "Se você tem experiência nessa área, registre-a numa experiência com datas.",
}


def filter_detail(code: str, **p: object) -> str:
    """One line explaining why one item was filtered, with the value and the threshold."""
    if code == "closed":
        return "A vaga foi fechada pela fonte."
    if code == "not_visible":
        return "Perfil não visível para recrutadores."
    if code == "arrangement_not_accepted":
        arrangement = ARRANGEMENT_LABELS.get(str(p.get("arrangement")), str(p.get("arrangement")))
        return f"A vaga é {arrangement}, modalidade que você não marcou como aceita."
    if code == "beyond_distance":
        distance, limit = fmt_number(float(p["distance_km"])), fmt_number(float(p["max_distance_km"]))  # type: ignore[arg-type]
        return f"A vaga fica a {distance} km; você aceita até {limit} km."
    if code == "country_eligibility":
        countries = ", ".join(str(c) for c in p.get("countries", []))  # type: ignore[union-attr]
        return f"A vaga aceita apenas pessoas elegíveis em: {countries}."
    if code == "salary_below_min":
        return (
            f"O teto da vaga ({p['job_comp']}) fica abaixo de {int(round(float(p['ratio']) * 100))}% "
            f"do seu mínimo ({p['candidate_comp']})."
        )
    if code == "seniority_gap":
        return (
            f"A vaga pede {seniority_label(p.get('job_level'))} e seu perfil está em "  # type: ignore[arg-type]
            f"{seniority_label(p.get('candidate_level'))}: distância de {p['gap']} níveis "  # type: ignore[arg-type]
            f"(o limite é menos de {p['threshold']})."
        )
    if code == "out_of_area":
        return (
            "Você não comprova nenhum requisito obrigatório desta vaga e ela é de outra área "
            f"({', '.join(str(d) for d in p.get('job_domains', []))})."  # type: ignore[union-attr]
        )
    return str(code)


def filtered_summary(total: int, groups: list[tuple[str, int]]) -> str:
    """ "Não te mostramos 12 vagas: 8 presenciais fora da distância…, 3 com salário abaixo…" """
    if total == 0:
        return "Todas as vagas abertas passaram pelos seus filtros."
    parts = [f"{n} {FILTER_TITLES.get(code, code)}" for code, n in groups if n]
    noun = "vaga" if total == 1 else "vagas"
    return f"Não te mostramos {total} {noun}: " + ", ".join(parts) + "."


# --------------------------------------------------------------------------- explanations

POSITION_NOTE = "A posição compara esta vaga com as outras da sua lista; bom encaixe é uma régua fixa."
POSITION_NOTE_RECRUITER = (
    "A posição compara este perfil com os outros da lista desta vaga; bom encaixe é uma régua fixa."
)
EXPLORE_SLOT_TEXT = (
    "Esta vaga foi sorteada para ampliar seu horizonte; ela não está entre as que mais combinam com você hoje."
)
EXPLORE_SLOT_TEXT_RECRUITER = (
    "Este perfil foi sorteado para ampliar seu horizonte; ele não está entre os que mais combinam com a vaga hoje."
)
APPLICANTS_FIRST_TEXT = "Quem se candidatou aparece primeiro, na ordem da fórmula."
UNKNOWN_TEXT = "não informado"
NOT_APPLICABLE_TEXT = "não se aplica"
FX_FLAG = "câmbio aproximado"
SALARY_UNKNOWN_FLAG = "salário não informado"

RECRUITER_TRANSPARENCY_NOTICE = "Quem se candidatou verá o motivo da recusa e o que faltou."

VISIBILITY_TOGGLE_TEXT = "Visível para recrutadores, anônimo até o encaixe"
LLM_CONSENT_TEXT = "Usar IA para ler meu CV (o texto é enviado ao provedor de LLM)"

PRIVACY_TEXTS: dict[str, str] = {
    "visibility_toggle": VISIBILITY_TOGGLE_TEXT,
    "llm_consent": LLM_CONSENT_TEXT,
    "blind_card": "Até o encaixe, recrutadores não veem seu nome, contato, foto, idade, nem os nomes "
    "das empresas e instituições do seu perfil.",
    "contact_released": "Contato liberado: os dois lados deram swipe à direita.",
    "recruiter_transparency": RECRUITER_TRANSPARENCY_NOTICE,
}

MATCH_TITLE = "É um encaixe!"
