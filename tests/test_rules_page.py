"""The rules page is generated from app/config.py (spec 9.1): no hidden rule, no hand-written number."""

from __future__ import annotations

import dataclasses

from app.config import RULES, rules_hash
from app.rules import RULES_MD_PATH, render_html, render_markdown, worked_example


def test_committed_rules_md_matches_the_config() -> None:
    """docs/RULES.md is `encaixe rules export` of the current config (run it after changing a rule)."""
    assert RULES_MD_PATH.read_text(encoding="utf-8") == render_markdown()


def test_changing_a_rule_changes_the_page_and_the_example() -> None:
    base = render_markdown()
    changed = dataclasses.replace(
        RULES,
        feedback=dataclasses.replace(RULES.feedback, half_life_days=30, k_min=8),
        good_fit=dataclasses.replace(RULES.good_fit, must_share=0.75),
        exploration=dataclasses.replace(RULES.exploration, every=7),
    )
    md = render_markdown(changed)
    assert md != base
    assert "Meia-vida de 30 dias" in md and "Meia-vida de 21 dias" in base
    assert "depois de\n**8 julgamentos**" in md
    assert "pelo menos 75%" in md and "pelo menos 80%" in base
    assert "A cada **7** cartas" in md
    assert rules_hash(changed) in md and rules_hash() in base
    # the worked example is computed by the engine with the rules it is given
    rrf = dataclasses.replace(RULES, aggregation=dataclasses.replace(RULES.aggregation, aggregator="rrf"))
    assert "Agregador em uso: `rrf`" in render_markdown(rrf)


def test_worked_example_is_consistent() -> None:
    ex = worked_example()
    assert [r["order"] for r in sorted(ex["rows"], key=lambda r: r["order"])] == [1, 2, 3]
    assert "empatam na soma" in ex["narrative"]  # the example shows the published tie-break at work


def test_page_states_the_salary_side_effect_and_sessions() -> None:
    md = render_markdown()
    assert "transparência salarial é recompensada" in md
    assert f"{RULES.events.session_idle_minutes} minutos sem atividade" in md
    assert "inclusive as de cartas sorteadas" in md
    assert "O que vai para a IA" in md and "O que o recrutador vê e o que não vê" in md


def test_rules_api(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/rules").json()
    assert body["hash"] == rules_hash() and body["markdown"].startswith("# Como o Encaixe decide")
    assert "<table>" in body["html"] and body["rules"]["good_fit"]["must_share"] == RULES.good_fit.must_share
    assert render_html("| a |\n|---|\n| 1 |").count("<td>") == 1
