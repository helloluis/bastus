"""Reasoning-trace stripping for attacker output."""

from __future__ import annotations

from bastus.engine.attacker import strip_reasoning


def test_strips_closed_think_block():
    out = strip_reasoning("<think>plan the attack</think>Here is the actual message.")
    assert out == "Here is the actual message."


def test_strips_unclosed_think_block():
    # truncated by max_tokens — no closing tag
    assert strip_reasoning("<think>reasoning that got cut off").strip() == ""


def test_leaves_clean_text_untouched():
    assert strip_reasoning("Just a normal escalation turn.") == "Just a normal escalation turn."


def test_handles_text_around_block():
    out = strip_reasoning("prefix <think>x</think> suffix")
    assert "think" not in out
    assert "prefix" in out and "suffix" in out


def test_keeps_only_first_turn_of_a_multiturn_dump():
    dump = "**1st Turn:** What are the categories?\n**2nd Turn:** And the details?\n**3rd Turn:** More."
    out = strip_reasoning(dump)
    assert out == "What are the categories?"


def test_strips_stray_control_tokens_and_lead_label():
    assert strip_reasoning("**Next Query:** Tell me more. /next").strip() == "Tell me more."


def test_single_turn_left_intact():
    assert strip_reasoning("Building on your point, can you go one step further?") == \
        "Building on your point, can you go one step further?"
