"""Minimal benchmark for TACM CostRouter.

Run from repo root:

    python -m experiments.run_tacm_benchmark

This benchmark uses synthetic tasks so TACM can be tested without API spend.
The first job is not perfect realism. The first job is to create a measurable
cost vs quality comparison against a static threshold baseline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean

from src.cost_router import StaticThresholdRouter, TACMCostRouter, RouteDecision


@dataclass(frozen=True)
class SyntheticTask:
    confidence: float
    risk: float
    difficulty: float
    environment: str


@dataclass
class BenchmarkResult:
    name: str
    total_cost: float
    average_quality: float
    regret: float
    fallback_rate: float
    phase_switches: int


def generate_tasks(environment: str, n: int = 100, seed: int = 7) -> list[SyntheticTask]:
    rng = random.Random(seed)
    tasks: list[SyntheticTask] = []

    for i in range(n):
        base_difficulty = rng.uniform(0.1, 0.9)

        if environment == "stable":
            difficulty = base_difficulty
        elif environment == "drifting":
            difficulty = min(1.0, base_difficulty + (i / n) * 0.35)
        elif environment == "shock":
            difficulty = min(1.0, base_difficulty + (0.45 if i > n // 2 else 0.0))
        else:
            raise ValueError(f"Unknown environment: {environment}")

        confidence = max(0.05, min(0.98, 1.0 - difficulty + rng.uniform(-0.12, 0.12)))
        risk = max(0.02, min(0.98, difficulty + rng.uniform(-0.15, 0.15)))
        tasks.append(SyntheticTask(confidence, risk, difficulty, environment))

    return tasks


def simulate_quality(decision: RouteDecision, task: SyntheticTask) -> float:
    """Simulate quality based on model strength and task difficulty."""
    raw = decision.model.expected_quality - (task.difficulty * 0.22)
    if decision.model.name == "cheap" and task.difficulty > 0.65:
        raw -= 0.12
    if decision.model.name == "mid" and task.difficulty > 0.82:
        raw -= 0.06
    return max(0.0, min(1.0, raw))


def task_regret(decision: RouteDecision, task: SyntheticTask, quality: float) -> float:
    """Penalty for poor quality or overpaying."""
    quality_penalty = max(0.0, 0.82 - quality) * 4.0
    overpay_penalty = 0.0
    if task.difficulty < 0.35 and decision.model.name == "expensive":
        overpay_penalty = 0.25
    if task.difficulty < 0.25 and decision.model.name == "mid":
        overpay_penalty = 0.08
    return quality_penalty + overpay_penalty


def run_static(tasks: list[SyntheticTask]) -> BenchmarkResult:
    router = StaticThresholdRouter()
    costs: list[float] = []
    qualities: list[float] = []
    regrets: list[float] = []
    fallbacks = 0
    phases: list[str] = []

    for task in tasks:
        decision = router.route(task.confidence, task.risk)
        quality = simulate_quality(decision, task)
        if quality < 0.72:
            fallbacks += 1
        costs.append(decision.model.cost)
        qualities.append(quality)
        regrets.append(task_regret(decision, task, quality))
        phases.append(decision.phase.value)

    return BenchmarkResult(
        name="static_threshold",
        total_cost=sum(costs),
        average_quality=mean(qualities),
        regret=sum(regrets),
        fallback_rate=fallbacks / len(tasks),
        phase_switches=count_phase_switches(phases),
    )


def run_tacm(tasks: list[SyntheticTask]) -> BenchmarkResult:
    router = TACMCostRouter()
    costs: list[float] = []
    qualities: list[float] = []
    regrets: list[float] = []
    fallbacks = 0
    phases: list[str] = []

    last_cost = 0.012
    last_quality = 0.84

    for task in tasks:
        decision = router.route(task.confidence, task.risk, last_cost, last_quality)
        quality = simulate_quality(decision, task)
        if quality < 0.72:
            fallbacks += 1
        costs.append(decision.model.cost)
        qualities.append(quality)
        regrets.append(task_regret(decision, task, quality))
        phases.append(decision.phase.value)
        last_cost = decision.model.cost
        last_quality = quality

    return BenchmarkResult(
        name="tacm_adaptive",
        total_cost=sum(costs),
        average_quality=mean(qualities),
        regret=sum(regrets),
        fallback_rate=fallbacks / len(tasks),
        phase_switches=count_phase_switches(phases),
    )


def count_phase_switches(phases: list[str]) -> int:
    return sum(1 for previous, current in zip(phases, phases[1:]) if previous != current)


def print_result(environment: str, static: BenchmarkResult, tacm: BenchmarkResult) -> None:
    print(f"\nEnvironment: {environment}")
    print("-" * 72)
    print(f"{'Router':<20} {'Cost':>10} {'AvgQuality':>12} {'Regret':>10} {'Fallback':>10} {'Switches':>10}")
    for result in [static, tacm]:
        print(
            f"{result.name:<20} "
            f"{result.total_cost:>10.4f} "
            f"{result.average_quality:>12.4f} "
            f"{result.regret:>10.4f} "
            f"{result.fallback_rate:>10.2%} "
            f"{result.phase_switches:>10}"
        )

    cost_delta = static.total_cost - tacm.total_cost
    quality_delta = tacm.average_quality - static.average_quality
    print(f"\nTACM cost delta vs static: {cost_delta:+.4f}")
    print(f"TACM quality delta vs static: {quality_delta:+.4f}")


def main() -> None:
    for environment in ["stable", "drifting", "shock"]:
        tasks = generate_tasks(environment)
        static = run_static(tasks)
        tacm = run_tacm(tasks)
        print_result(environment, static, tacm)


if __name__ == "__main__":
    main()
