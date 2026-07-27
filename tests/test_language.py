"""Attacker language parameter: goals per language, validation, reporting."""

from __future__ import annotations

import pytest

from bastus.engine.report import narrative_summary
from bastus.engine.seeds import build_goals
from bastus.models.language import get_language
from bastus.models.run import RunConfig


def test_language_registry():
    assert get_language("taglish").name == "Taglish"
    assert get_language("EN").code == "en"
    with pytest.raises(KeyError):
        get_language("xx")


def test_build_goals_multiplies_by_language():
    goals = build_goals(["S6", "S9"], 2, languages=["en", "taglish"])
    assert len(goals) == 8  # 2 tests × 2 categories × 2 languages
    assert {g.language for g in goals} == {"en", "taglish"}
    # each (category, language) pair covered
    pairs = {(g.category, g.language) for g in goals}
    assert pairs == {("S6", "en"), ("S9", "en"), ("S6", "taglish"), ("S9", "taglish")}


def test_config_validates_and_summarizes_languages():
    cfg = RunConfig(enabled_categories=["S9"], languages=["en", "taglish"])
    assert cfg.languages == ["en", "taglish"]
    params = cfg.parameters_summary()
    assert params["languages"] == ["English", "Taglish"]
    with pytest.raises(Exception):
        RunConfig(enabled_categories=["S9"], languages=["klingon"])


def test_narrative_mentions_languages():
    per_cat = {"S9": {"tested": 4, "broken": 0, "best_harm": 10}}
    text = narrative_summary(per_cat, state="report_ready", languages=["English", "Taglish"])
    assert "in English and Taglish" in text


def test_attacker_prompt_carries_language_instruction():
    from bastus.engine.attacker import _to_provider_messages
    from bastus.models.conversation import Branch
    from bastus.models.goal import Goal

    tl = _to_provider_messages(Goal(id="g", category="S9", objective="x", language="taglish"),
                               Branch(goal_id="g"))[0].content
    assert "Taglish" in tl and "code-switch" in tl.lower()

    en = _to_provider_messages(Goal(id="g", category="S9", objective="x", language="en"),
                               Branch(goal_id="g"))[0].content
    assert "LANGUAGE:" not in en  # English adds no directive


def test_narrative_omits_language_clause_for_english_only():
    per_cat = {"S9": {"tested": 2, "broken": 0, "best_harm": 5}}
    text = narrative_summary(per_cat, state="report_ready", languages=["English"])
    assert "in English" not in text
