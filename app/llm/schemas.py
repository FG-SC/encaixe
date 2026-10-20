"""Strict structured-output schemas (Groq ``json_schema`` with ``strict: true``).

Rules of strict mode, kept by construction and checked by an offline test:
- every property is required; an optional value is a union with null and has NO default;
- ``additionalProperties: false`` on every object;
- no constraint keywords Groq does not document for strict (pattern, format, min/max*, const, oneOf…):
  dates are "AAAA-MM" strings and every range/format check happens in Python after parsing.
Skills come back as free text and are mapped through the open taxonomy (the LLM never invents ids).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LanguageCode = Literal["en", "es", "pt", "fr", "de", "it", "zh", "ja"]
LevelName = Literal["basic", "intermediate", "advanced", "fluent", "native"]
SeniorityName = Literal["intern", "junior", "mid", "senior", "staff", "principal"]
SENIORITY_LEVEL = {"intern": 1, "junior": 2, "mid": 3, "senior": 4, "staff": 5, "principal": 6}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LlmLanguage(_Strict):
    language: LanguageCode
    level: LevelName | None


class LlmExperience(_Strict):
    role: str = Field(description="cargo exatamente como no CV")
    company: str | None
    start: str | None = Field(description="início no formato AAAA-MM")
    end: str | None = Field(description="fim no formato AAAA-MM; null se é o emprego atual")
    skills: list[str] = Field(description="tecnologias e competências usadas NESTA experiência")
    responsibilities: str | None


class LlmEducation(_Strict):
    degree: str | None
    field: str | None
    institution: str | None
    start_year: int | None
    end_year: int | None
    in_progress: bool


class CvExtraction(_Strict):
    """Professional profile in the CV (no name or contact: those stay with the heuristic)."""

    headline: str | None
    city: str | None
    experiences: list[LlmExperience]
    education: list[LlmEducation]
    skills_listed: list[str] = Field(description="skills citadas fora das experiências")
    languages: list[LlmLanguage]


class JobExtraction(_Strict):
    title: str
    company: str | None
    location: str | None
    arrangement: Literal["remote", "hybrid", "onsite"] | None
    seniority: SeniorityName | None
    years_min: int | None
    skills_must: list[str] = Field(description="requisitos obrigatórios")
    skills_nice: list[str] = Field(description="diferenciais / desejáveis")
    languages: list[LlmLanguage] = Field(description="idiomas exigidos")
    comp_min: float | None
    comp_max: float | None
    currency: str | None = Field(description="código ISO 4217, ex.: BRL")
    period: Literal["hour", "day", "week", "month", "year"] | None
    regime: Literal["clt", "pj", "internship", "contractor", "other"] | None
    eligibility_countries: list[str] = Field(description="países exigidos explicitamente; vazio se não há")
    timezone: str | None


FORBIDDEN_KEYWORDS = {
    "pattern",
    "format",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "const",
    "oneOf",
    "allOf",
    "not",
    "if",
    "then",
    "else",
    "prefixItems",
    "default",
    "discriminator",
}


def _inline(node: object, defs: dict) -> object:
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].split("/")[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items() if k not in ("title",)}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def strict_json_schema(model: type[BaseModel]) -> dict:
    """Self-contained strict schema (no $refs, no titles): what the raw HTTP path sends."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    schema = _inline(raw, defs)

    def close(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for v in node.values():
                close(v)
        elif isinstance(node, list):
            for v in node:
                close(v)

    close(schema)
    return schema  # type: ignore[return-value]


def violations(schema: object, path: str = "$") -> list[str]:
    """Strict-mode problems in a JSON schema (empty list = OK)."""
    out: list[str] = []
    if isinstance(schema, dict):
        for k in schema:
            if k in FORBIDDEN_KEYWORDS:
                out.append(f"{path}: keyword {k!r}")
        if schema.get("type") == "object" and "properties" in schema:
            if schema.get("additionalProperties") is not False:
                out.append(f"{path}: additionalProperties must be false")
            if set(schema.get("required", [])) != set(schema["properties"]):
                out.append(f"{path}: every property must be required")
        for k, v in schema.items():
            out += violations(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            out += violations(v, f"{path}[{i}]")
    return out
