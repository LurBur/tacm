"""Research-only Tri-Guna supervisory governor for externally supplied trading-agent proposals.

No networking, API keys or live order submission are implemented.
Every decision is an exposure target, never a direct exchange order.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from math import sqrt, isfinite
from statistics import mean, pstdev
from typing import Dict, Mapping, Sequence, Optional


def clip(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, x))


@dataclass(frozen=True)
class Proposal:
    agent: str
    target: float  # 0 = flat, 1 = long; never short or leverage in this prototype
    confidence: float

    def __post_init__(self):
        if not self.agent or not (isfinite(self.target) and isfinite(self.confidence)):
            raise ValueError('Proposal must have finite fields and a nonempty agent')
        if self.target not in (0.0, 1.0) or not 0 <= self.confidence <= 1:
            raise ValueError('Only target=0/1 and confidence in [0,1] are allowed')


@dataclass(frozen=True)
class Observation:
    time: datetime
    opens: Sequence[float]    # bars strictly BEFORE the current execution open
    closes: Sequence[float]   # bars strictly BEFORE the current execution open
    equity: float
    peak_equity: float
    strategy_returns: Mapping[str, Sequence[float]]
    turnover_recent: float = 0.0


@dataclass(frozen=True)
class Decision:
    selected_agent: str
    target_weight: float
    sattva: float
    rajas: float
    tamas: float
    phase: str
    diagnostic_81: str
    advantage_decay: float
    intervention: str
    explanation: str

    def to_json(self) -> dict:
        return asdict(self)


class TrigunaGovernor:
    """Continuous quality fields, plus an explanatory 81-state *label*.

    The label does not govern decisions and is not an empirically validated taxonomy.
    Governance is causal if supplied input contains only previously completed bars.
    """
    def __init__(self, variant: str = 'full', max_weight: float = 0.10):
        if variant not in ('full','no_sattva','no_rajas','no_tamas'):
            raise ValueError('invalid ablation variant')
        self.variant = variant
        self.max_weight = max_weight
        self.incumbent: Optional[str] = None
        self.prev_strengths: Dict[str, float] = {}
        self.cooldown_until_bar = -1
        self.bar_index = 0
        self.selection_history = deque(maxlen=12)

    @staticmethod
    def _quality(mean_return: float, count: int) -> float:
        # Positive/negative shadow returns are evidence, not profit guarantees.
        return clip(0.5 + 100 * mean_return, 0.0, 1.0) * clip(count / 30)

    @staticmethod
    def _decay(returns: Sequence[float]) -> float:
        if len(returns) < 24:
            return 0.0
        older = mean(returns[-24:-12]); recent = mean(returns[-12:])
        # 'Stale success': older performance positive while more recent advantage erodes.
        return clip((older - recent) * 150) if older > 0 else 0.0

    def decide(self, observation: Observation, proposals: Sequence[Proposal]) -> Decision:
        if not proposals or len(observation.closes) < 50 or len(observation.opens) != len(observation.closes):
            raise ValueError('Need >=50 completed, synchronized bars and at least one agent')
        if observation.equity <= 0 or observation.peak_equity <= 0:
            raise ValueError('Equity must be positive')
        if any((not isfinite(x) or x <= 0) for x in observation.opens[-50:] + observation.closes[-50:]):
            raise ValueError('Nonpositive/missing market data')
        if len({p.agent for p in proposals}) != len(proposals):
            raise ValueError('Agent names must be unique')
        by_name = {p.agent: p for p in proposals}
        self.bar_index += 1
        closes = observation.closes
        rets = [closes[i] / closes[i-1] - 1 for i in range(len(closes)-36, len(closes))]
        volatility = pstdev(rets[-24:])
        previous_vol = max(0.0001, pstdev(rets[-36:-24]))
        regime_change = clip(abs(volatility / previous_vol - 1) / 2)
        shock = clip(abs(rets[-1]) / max(volatility * 4, 0.015))
        drawdown = clip(1.0 - observation.equity / observation.peak_equity)
        performance: dict[str, float] = {}
        credibility: dict[str, float] = {}
        decays: dict[str, float] = {}
        for p in proposals:
            sample = list(observation.strategy_returns.get(p.agent, []))[-48:]
            performance[p.agent] = mean(sample[-24:]) if sample else 0.0
            credibility[p.agent] = self._quality(performance[p.agent], len(sample))
            decays[p.agent] = self._decay(sample)

        # Heuristic operationalization, not a claim of canonical mathematical equivalence.
        sample_size = min((len(observation.strategy_returns.get(p.agent, [])) for p in proposals), default=0)
        evidence = clip(sample_size / 48)
        confidence = max(p.confidence for p in proposals)
        sattva = clip(0.10 + 0.50 * evidence + 0.20 * confidence +
                      0.20 * mean(credibility.values()))
        rajas = clip(0.10 + 0.50 * regime_change + 0.25 * shock +
                     0.15 * max(decays.values()))
        tamas = clip(0.15 + 0.45 * (1 - evidence) +
                     0.30 * clip(observation.turnover_recent) +
                     0.10 * clip(volatility / .025))
        if self.variant == 'no_sattva': sattva = 0.5
        if self.variant == 'no_rajas': rajas = 0.5
        if self.variant == 'no_tamas': tamas = 0.5

        if self.incumbent not in by_name:
            self.incumbent = proposals[0].agent
        # All qualities remain simultaneous. No hard 'mode switch' among the three.
        utility: Dict[str, float] = {}
        for p in proposals:
            shadow_edge = clip(performance[p.agent] * 180, -.4, .4)
            proposed_cost = 0.05 * (1 - p.confidence)
            change_cost = 0.0
            if p.agent != self.incumbent:
                change_cost = 0.05 + 0.22 * tamas - 0.16 * rajas
            if self.variant == 'no_sattva': shadow_edge *= 0.0
            if self.variant == 'no_rajas': change_cost += 0.12
            if self.variant == 'no_tamas': change_cost = max(0.0, change_cost - 0.07)
            utility[p.agent] = 0.20 * p.confidence + shadow_edge - proposed_cost - change_cost
        selected = max(proposals, key=lambda p: utility[p.agent]); name = selected.agent
        self.selection_history.append(name)
        switched = name != self.incumbent
        self.incumbent = name
        decay = decays[name]
        # Exposure is a confidence-limited budget, not 'risk per trade'.
        scaling = clip((0.3 + 0.7 * sattva) * (1 - 0.5 * tamas) /
                       max(1, volatility / 0.025))
        weight = self.max_weight * scaling * selected.target
        intervention = 'maintain' if not switched else 'explore_agent'
        reason = 'Evidence-weighted, friction-aware proposal review'
        if decay > 0.55:
            weight *= 0.5
            intervention = 'advantage_decay_reduce'
            reason = 'Past-positive shadow performance has recently deteriorated'
        if drawdown >= 0.035 or shock > 0.80:
            weight = 0.0
            self.cooldown_until_bar = self.bar_index + 3
            intervention = 'flame_reset'
            reason = 'Sharp observed shock or account drawdown: flatten and cooldown'
        if self.bar_index <= self.cooldown_until_bar:
            weight = 0.0
            intervention = 'cooldown'
            reason = 'Post-reset cooldown'

        # Canonical diagnostic family: 3 phases x 3 qualities x 3 intensities x 3 trends = 81.
        # Selecting a dominant *label* does not imply that only one force is active.
        strengths = {'Crystal': clip((1 - regime_change - shock * .5) * (.6 + .4 * evidence)),
                     'Flower': clip(.25 + regime_change + .2 * (len({p.target for p in proposals}) > 1)),
                     'Flame': clip(decay + drawdown * 7 + shock * .4)}
        phase = max(strengths, key=strengths.get)
        quality = max({'Sattvic':sattva, 'Rajasic':rajas, 'Tamasic':tamas},
                      key={'Sattvic':sattva, 'Rajasic':rajas, 'Tamasic':tamas}.get)
        level = 'Low' if strengths[phase] < 1/3 else ('Mid' if strengths[phase] < 2/3 else 'High')
        change = strengths[phase] - self.prev_strengths.get(phase, strengths[phase])
        trend = 'Rising' if change > .03 else ('Decaying' if change < -.03 else 'Stable')
        self.prev_strengths = strengths
        return Decision(name, round(clip(weight, 0.0, self.max_weight), 6),
                        round(sattva, 4), round(rajas, 4), round(tamas, 4),
                        phase, f'{phase}/{quality}/{level}/{trend}',
                        round(decay, 5), intervention, reason)


class PlainSelector:
    """Unsupervised baseline: same proposals and same hard risk envelope."""
    def __init__(self, max_weight: float = .10):
        self.max_weight = max_weight

    def decide(self, obs: Observation, proposals: Sequence[Proposal]) -> Decision:
        chosen = max(proposals, key=lambda p: p.confidence)
        return Decision(chosen.agent, self.max_weight * chosen.target,
                        0.0, 0.0, 0.0, 'Baseline', 'n/a', 0.0,
                        'plain_signal', 'Highest-confidence proposal; no Tri-Guna')


class IndependentRiskGate:
    """Non-negotiable account-level limits; governor cannot bypass this layer."""
    def __init__(self, max_weight=.10, max_drawdown=.05, daily_loss=.02,
                 max_new_entries_per_day=3):
        self.max_weight = max_weight
        self.max_drawdown = max_drawdown
        self.daily_loss = daily_loss
        self.max_new_entries_per_day = max_new_entries_per_day
        self.day = None
        self.day_start_equity = None
        self.entries_today = 0
        self.halted = False
        self.daily_halted = False

    def allow(self, target_weight: float, equity: float, peak: float,
              timestamp: datetime, current_weight: float) -> tuple[float, str]:
        if self.day != timestamp.date():
            self.day = timestamp.date()
            self.day_start_equity = equity
            self.entries_today = 0
            self.daily_halted = False
        if equity <= 0 or peak <= 0 or not isfinite(equity):
            self.halted = True
        if equity < peak * (1 - self.max_drawdown):
            self.halted = True
        if self.halted:
            return 0.0, 'permanent_drawdown_halt'
        if equity < self.day_start_equity * (1 - self.daily_loss):
            self.daily_halted = True
        if self.daily_halted:
            return 0.0, 'daily_loss_limit'
        target = clip(target_weight, 0, self.max_weight)
        if target > current_weight + 0.01:
            if self.entries_today >= self.max_new_entries_per_day:
                return min(target, current_weight), 'daily_entry_cap'
            self.entries_today += 1
        return target, 'allowed'