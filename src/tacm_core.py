"""Core TACM phase logic.

TACM starts simple here on purpose. The goal is not to encode the entire theory
in one heroic file. The goal is to create a small, testable adaptive controller
that can be compared against a static router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from statistics import mean


class Phase(str, Enum):
    """Triadic control phases."""

    CRYSTAL = "crystal"  # stabilize / exploit / preserve
    FLOWER = "flower"  # explore / test / diversify
    FLAME = "flame"  # escalate / perturb / intervene


@dataclass
class Observation:
    """Single routing observation.

    cost: observed or simulated cost for the route
    quality: observed or simulated quality score in [0, 1]
    confidence: router confidence in [0, 1]
    risk: task risk in [0, 1]
    """

    cost: float
    quality: float
    confidence: float
    risk: float

    @property
    def efficiency(self) -> float:
        """Quality per unit cost, guarded against divide-by-zero."""
        return self.quality / max(self.cost, 1e-9)


@dataclass
class TACMConfig:
    """Config for the lightweight TACM controller."""

    window_size: int = 8
    divergence_threshold: float = 0.18
    sustained_instability_threshold: int = 3
    low_confidence_threshold: float = 0.55
    high_risk_threshold: float = 0.75
    quality_floor: float = 0.82


@dataclass
class TACMController:
    """Minimal adaptive controller for routing experiments."""

    config: TACMConfig = field(default_factory=TACMConfig)
    observations: list[Observation] = field(default_factory=list)
    phase: Phase = Phase.CRYSTAL
    sustained_instability: int = 0

    def observe(self, observation: Observation) -> Phase:
        """Add an observation and update phase."""
        self.observations.append(observation)
        if len(self.observations) > self.config.window_size:
            self.observations.pop(0)

        divergence = self._efficiency_divergence(observation)
        unstable = divergence >= self.config.divergence_threshold
        quality_drop = observation.quality < self.config.quality_floor
        confidence_drop = observation.confidence < self.config.low_confidence_threshold
        high_risk = observation.risk >= self.config.high_risk_threshold

        if unstable or quality_drop:
            self.sustained_instability += 1
        else:
            self.sustained_instability = max(0, self.sustained_instability - 1)

        if high_risk and (confidence_drop or quality_drop):
            self.phase = Phase.FLAME
        elif self.sustained_instability >= self.config.sustained_instability_threshold:
            self.phase = Phase.FLAME
        elif unstable or confidence_drop:
            self.phase = Phase.FLOWER
        else:
            self.phase = Phase.CRYSTAL

        return self.phase

    def _efficiency_divergence(self, observation: Observation) -> float:
        """Return normalized efficiency divergence from recent mean."""
        if len(self.observations) < 2:
            return 0.0

        historical = self.observations[:-1]
        baseline = mean(obs.efficiency for obs in historical)
        if baseline <= 0:
            return 0.0

        return abs(observation.efficiency - baseline) / baseline
