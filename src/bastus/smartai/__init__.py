"""Adapter for the in-house Smart AI api-test target (custom, non-OpenAI API)."""

from bastus.smartai.client import SmartAIClient, SmartAIError
from bastus.smartai.target import SmartAITarget

__all__ = ["SmartAIClient", "SmartAIError", "SmartAITarget"]
