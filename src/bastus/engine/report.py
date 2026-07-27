"""Aggregated run results — the data the PDF report and UI summary render from."""

from __future__ import annotations

from dataclasses import dataclass, field

from bastus.engine.beam import GoalResult
from bastus.models.run import RunConfig
from bastus.models.taxonomy import get_category


def _cat_name(code: str) -> str:
    try:
        return f"{code} {get_category(code).name}"
    except Exception:
        return code


def narrative_summary(per_category: dict, state: str = "", error_turns: int = 0) -> str:
    """A deterministic 2-3 sentence plain-English verdict, derived from the run's own
    per-category stats. per_category maps code -> {tested, broken, best_harm}."""
    # Failed/aborted runs are NOT valid baselines — never narrate their partial numbers
    # as a clean result (that's the "0 breaks looks safe" trap).
    if state in ("failed", "aborted"):
        verb = "failed before completing" if state == "failed" else "was aborted"
        msg = f"This run {verb}, so its results are incomplete and not a valid baseline."
        if error_turns:
            msg += (f" {error_turns} model call{'s' if error_turns != 1 else ''} errored "
                    f"(likely an API/credit or connectivity issue).")
        broken = [_cat_name(c) for c, s in per_category.items() if s.get("broken")]
        if broken:
            msg += f" Before stopping it did flag possible breaks in {', '.join(broken)}."
        return msg

    tested = sum(s.get("tested", 0) for s in per_category.values())
    if tested == 0:
        return "No scored results are available for this run."

    breaks = sum(s.get("broken", 0) for s in per_category.values())
    broken_cats = sorted(
        ((c, s) for c, s in per_category.items() if s.get("broken")),
        key=lambda kv: kv[1].get("best_harm", 0), reverse=True,
    )
    ncat = len(per_category)
    resistance = round(100 * (1 - breaks / tested))
    asr = round(100 * breaks / tested)

    s1 = (f"The target resisted {resistance}% of attacks (ASR {asr}%), holding "
          f"{ncat - len(broken_cats)} of {ncat} categor{'y' if ncat == 1 else 'ies'} "
          f"across {tested} goals.")

    if broken_cats:
        worst_c, worst_s = broken_cats[0]
        every = ""
        if worst_s.get("tested", 0) > 1 and worst_s.get("broken") == worst_s.get("tested"):
            every = ", breaking every attempt"
        names = ", ".join(_cat_name(c) for c, _ in broken_cats)
        s2 = (f"Guardrails were broken in {names} — most severely {_cat_name(worst_c)} "
              f"(peak harm {round(worst_s.get('best_harm', 0))}{every}).")
        s3 = "These breaks are judge-flagged, so review those conversations to confirm they are genuine."
    else:
        peak_c, peak_s = max(per_category.items(), key=lambda kv: kv[1].get("best_harm", 0))
        peak_h = round(peak_s.get("best_harm", 0))
        s2 = (f"No category was broken; the target came closest on {_cat_name(peak_c)} "
              f"(peak harm {peak_h}, below the break threshold)." if peak_h > 0
              else "No category was broken and no substantive harmful content was elicited.")
        s3 = ""

    parts = [s1, s2]
    if error_turns:
        parts.append(f"Note: {error_turns} model call{'s' if error_turns != 1 else ''} errored and "
                     f"{'were' if error_turns != 1 else 'was'} skipped, so coverage is partial.")
    elif s3:
        parts.append(s3)
    return " ".join(p for p in parts if p)


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

    @property
    def narrative(self) -> str:
        per_cat = {c: {"tested": s.tested, "broken": s.broken, "best_harm": s.best_harm}
                   for c, s in self.per_category().items()}
        return narrative_summary(per_cat)

    def summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "narrative": self.narrative,
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
