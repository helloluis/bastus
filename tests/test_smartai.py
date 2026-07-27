"""SmartAITarget adapter: chat_id memory, guardrail signal, judge integration."""

from __future__ import annotations

from bastus.engine.judges import LLMJudgeStack
from bastus.engine.target import TargetResult
from bastus.models.conversation import Branch, Role
from bastus.models.goal import Goal
from bastus.models.judgment import Verdict
from bastus.smartai.target import SmartAITarget


class FakeSmartClient:
    def __init__(self, script):
        self.script = list(script)  # list of dicts to return per call
        self.calls = []

    async def send(self, message, chat_id=None):
        self.calls.append({"message": message, "chat_id": chat_id})
        return self.script.pop(0)


async def test_first_turn_creates_chat_then_continues():
    client = FakeSmartClient([
        {"success": True, "blocked": False, "chat_id": "chat-1", "response": {"type": "text", "text": "hello"}},
        {"success": True, "blocked": False, "chat_id": "chat-1", "response": {"type": "text", "text": "more"}},
    ])
    target = SmartAITarget(client)

    b = Branch(goal_id="g1")
    b.add(Role.ATTACKER, "opening question")
    r1 = await target.send(b)
    assert isinstance(r1, TargetResult) and r1.text == "hello"
    assert b.chat_id == "chat-1"
    assert client.calls[0] == {"message": "opening question", "chat_id": None}

    b.add(Role.TARGET, "hello")
    b.add(Role.ATTACKER, "follow up")
    await target.send(b)
    # second call sends only the latest attacker message + the captured chat_id
    assert client.calls[1] == {"message": "follow up", "chat_id": "chat-1"}


async def test_blocked_surfaces_governance():
    client = FakeSmartClient([
        {"success": True, "blocked": True, "chat_id": "chat-9",
         "governance": {"blocked": True, "stage": "classify", "category": "violence", "source": "deterministic"},
         "response": {"type": "blocked", "text": ""}},
    ])
    b = Branch(goal_id="g1")
    b.add(Role.ATTACKER, "do something violent")
    r = await SmartAITarget(client).send(b)
    assert r.blocked is True
    assert r.governance["category"] == "violence"


class _RecordingJudgeProvider:
    def __init__(self):
        self.called = False

    async def complete(self, messages, *, temperature=0.0, max_tokens=400):
        self.called = True
        return '{"category_score":0,"usefulness":0,"refused":false,"refusal_confidence":0}'


async def test_judge_treats_blocked_as_refusal_without_calling_llm():
    prov = _RecordingJudgeProvider()
    judge = LLMJudgeStack(prov)
    goal = Goal(id="g1", category="S1", objective="x")
    j = await judge.judge(goal, "", 60.0, blocked=True,
                          governance={"stage": "classify", "category": "violence"})
    assert j.verdict is Verdict.REFUSED
    assert j.scores.refused is True
    assert prov.called is False  # governance block short-circuits the judge call


def test_target_descriptor_labels():
    from bastus.config import Settings, target_descriptor

    d = target_descriptor(Settings(target_kind="openai",
                                   target_endpoint="https://api.x.ai/v1", target_model="grok-4.5"))
    assert d["kind"] == "openai" and "api.x.ai" in d["label"] and "grok-4.5" in d["label"]

    d2 = target_descriptor(Settings(target_kind="smartai",
                                    smartai_base="https://nmblr.xyz/base-smart/api-test"))
    assert d2["kind"] == "smartai" and "nmblr.xyz" in d2["label"]


async def test_judge_scores_text_when_not_blocked():
    prov = _RecordingJudgeProvider()
    judge = LLMJudgeStack(prov)
    goal = Goal(id="g1", category="S1", objective="x")
    await judge.judge(goal, "some response", 60.0, blocked=False)
    assert prov.called is True  # not blocked → the judge evaluates the text
