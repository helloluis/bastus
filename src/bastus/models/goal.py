"""A goal (a.k.a. seed / objective): one thing the attacker tries to elicit.

Objectives are abstract descriptions of a disallowed outcome to attempt — never
operational harmful instructions. The abliterated attacker model generates the
actual adversarial turns at runtime; nothing harmful is hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Goal:
    id: str
    category: str  # taxonomy code, e.g. "S9"
    objective: str  # abstract description of what to try to elicit
    seed_image_ref: str | None = None  # handle into the seed-image bank (multimodal)
    language: str = "en"  # attacker language code (see models.language)
