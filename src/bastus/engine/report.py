"""Aggregated run results — the data the PDF report and UI summary render from."""

from __future__ import annotations

from dataclasses import dataclass, field

from bastus.engine.beam import GoalResult
from bastus.models.run import RunConfig


@dataclass
class CategoryStat:
    category: str
    tested: int = 0
    broken: int = 0
    best_harm: float = 0.0

    @property
    def asr(self) -> float:
        return self.broken / self.tested if self.tested else 0.0


@dataclass
class RunReport:
    run_id: int
    config: RunConfig
    results: list[GoalResult] = field(default_factory=list)

    @property
    def total_goals(self) -> int:
        return len(self.results)

    @property
    def total_breaks(self) -> int:
        return sum(1 for r in self.results if r.broken)

    @property
    def attack_success_rate(self) -> float:
        return self.total_breaks / self.total_goals if self.total_goals else 0.0

    @property
    def resistance(self) -> float:
        """1 - ASR. Higher = safer (the intuitive "how well did the target hold")."""
        return 1.0 - self.attack_success_rate

    def per_category(self) -> dict[str, CategoryStat]:
        stats: dict[str, CategoryStat] = {}
        for r in self.results:
            s = stats.setdefault(r.goal.category, CategoryStat(category=r.goal.category))
            s.tested += 1
            s.broken += int(r.broken)
            s.best_harm = max(s.best_harm, r.best_harm)
        return stats

    def summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "parameters": self.config.parameters_summary(),
            "total_goals": self.total_goals,
            "total_breaks": self.total_breaks,
            "attack_success_rate": self.attack_success_rate,
            "resistance": self.resistance,
            "per_category": {
                c: {"tested": s.tested, "broken": s.broken, "asr": s.asr, "best_harm": s.best_harm}
                for c, s in self.per_category().items()
            },
        }
