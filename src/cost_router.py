"""Cost-aware router built on TACM phase decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .tacm_core import Phase, TACMController, Observation


@dataclass(frozen=True)
class ModelOption:
    """A model tier available to the router."""

    name: str
    cost: float
    expected_quality: float


CHEAP_MODEL = ModelOption("cheap", cost=0.002, expected_quality=0.72)
MID_MODEL = ModelOption("mid", cost=0.012, expected_quality=0.84)
EXPENSIVE_MODEL = ModelOption("expensive", cost=0.080, expected_quality=0.94)


@dataclass
class RouteDecision:
    """Router output."""

    model: ModelOption
    phase: Phase
    reason: str


class StaticThresholdRouter:
    """Simple baseline router.

    This is intentionally basic. It routes by confidence and risk only.
    """

    def route(self, confidence: float, risk: float) -> RouteDecision:
        if risk >= 0.75 or confidence < 0.45:
            return RouteDecision(EXPENSIVE_MODEL, Phase.FLAME, "high risk or very low confidence")
        if risk >= 0.45 or confidence < 0.7:
            return RouteDecision(MID_MODEL, Phase.FLOWER, "medium risk or moderate confidence")
        return RouteDecision(CHEAP_MODEL, Phase.CRYSTAL, "low risk and high confidence")


class TACMCostRouter:
    """Adaptive TACM router."""

    def __init__(self, controller: TACMController | None = None) -> None:
        self.controller = controller or TACMController()

    def route(self, confidence: float, risk: float, last_cost: float, last_quality: float) -> RouteDecision:
        observation = Observation(
            cost=last_cost,
            quality=last_quality,
            confidence=confidence,
            risk=risk,
        )
        phase = self.controller.observe(observation)

        if phase == Phase.FLAME:
            return RouteDecision(EXPENSIVE_MODEL, phase, "TACM detected high instability or high-risk failure")
        if phase == Phase.FLOWER:
            return RouteDecision(MID_MODEL, phase, "TACM detected uncertainty or divergence")
        return RouteDecision(CHEAP_MODEL, phase, "TACM stable enough for cheap route")
