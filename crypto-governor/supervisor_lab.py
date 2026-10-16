"""TACM supervisor experiment v0.2 (PAPER ONLY).

Pure, transparent strategy signals are evaluated under identical historical bars,
fees, independent risk limits, and execution assumptions. This program has no
networking, credentials, or real exchange-order capability.

Historical backtests are development evidence, NOT forward-trading results.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from statistics import mean, pstdev
from typing import Sequence


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    agent: str
    target: float  # exactly 0 (flat) or 1 (long); no shorting, leverage, or orders
    confidence: float
    evidence: str

    def __post_init__(self):
        if self.target not in (0.0, 1.0):
            raise ValueError("A signal must target 0 (flat) or 1 (long)")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be finite and between 0 and 1")


def read_bars(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                raise ValueError("Require timezone-aware timestamps")
            ts = ts.astimezone(timezone.utc)
            o, h, l, c, v = (float(row[x]) for x in ("open", "high", "low", "close", "volume"))
            if not all(isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0:
                raise ValueError("Bad price or volume")
            if h < max(o, l, c) or l > min(o, h, c):
                raise ValueError("Invalid candle high/low")
            if bars and ts <= bars[-1].timestamp:
                raise ValueError("Non-increasing/duplicate candle timestamps")
            bars.append(Bar(ts, o, h, l, c, v))
    return validate_bars(bars)


def validate_bars(bars: list[Bar]) -> list[Bar]:
    if len(bars) < 100:
        raise ValueError("At least 100 completed OHLCV candles required")
    gaps = [(b.timestamp - a.timestamp).total_seconds() for a, b in zip(bars, bars[1:])]
    normal = sorted(gaps)[len(gaps) // 2]
    if normal <= 0 or any(abs(x - normal) > 1 for x in gaps):
        raise ValueError("Irregular or missing candles: reject rather than interpolate")
    for i, b in enumerate(bars):
        if not all(isfinite(x) for x in (b.open, b.high, b.low, b.close, b.volume)) or min(b.open, b.high, b.low, b.close) <= 0 or b.volume < 0:
            raise ValueError("Invalid OHLCV bar")
        if b.high < max(b.open, b.close, b.low) or b.low > min(b.open, b.close, b.high):
            raise ValueError("Inconsistent OHLCV bar")
    return bars


def load_bars(path: str) -> list[Bar]:
    """Read user CSV or the existing paper-only Kraken JSON snapshot (not a live feed)."""
    if not path.endswith(".json"):
        return read_bars(path)
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if obj.get("mode") != "market" or obj.get("paper_only") is not True:
        raise ValueError("Only labeled historical market snapshots accepted; never synthetic demo")
    raw = obj.get("candles", [])
    bars = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 6:
            raise ValueError("Unexpected snapshot candle shape")
        t, o, h, l, c, v = item
        bars.append(Bar(datetime.fromtimestamp(float(t), timezone.utc),
                        *map(float, (o, h, l, c, v))))
    if any(a.timestamp >= b.timestamp for a, b in zip(bars, bars[1:])):
        raise ValueError("Snapshot not strictly chronological")
    return validate_bars(bars)


def standard_agents(completed: Sequence[Bar]) -> list[Signal]:
    """Identical, deterministic proposals for every supervisor; never uses current/future bar."""
    if len(completed) < 50:
        raise ValueError("50 completed candles required")
    closes = [x.close for x in completed]
    fast, slow = mean(closes[-12:]), mean(closes[-48:])
    gap = fast / slow - 1
    trend = Signal("momentum_12_48", float(gap > .001),
                   min(1., .3 + abs(gap) * 25), f"SMA12/SMA48-1={gap:.6f}")
    center = mean(closes[-24:])
    sd = max(1e-6, pstdev(closes[-24:]))
    z = (closes[-1] - center) / sd
    revert = Signal("mean_revert_z24", float(z < -.5),
                    min(1., .25 + abs(z) * .18), f"z24={z:.4f}")
    return [trend, revert]


def clamp(x: float, low: float, high: float) -> float:
    return min(high, max(low, x))


class RiskGate:
    """Independent, identical hard restrictions for all active strategies."""
    def __init__(self, max_weight: float = .10, dd_halt: float = .05,
                 daily_halt: float = .02, entry_cap: int = 3):
        self.max_weight, self.dd_halt = max_weight, dd_halt
        self.daily_halt, self.entry_cap = daily_halt, entry_cap
        self.day = None
        self.day_start_equity = None
        self.daily_stopped = False
        self.permanent_stopped = False
        self.entries = 0

    def allow(self, requested: float, equity: float, peak: float,
              now: datetime, current_weight: float) -> tuple[float, str]:
        if not isfinite(requested) or requested < 0 or requested > self.max_weight + 1e-9:
            raise ValueError("Governor exceeded its allowed exposure")
        if self.day != now.date():
            self.day = now.date()
            self.day_start_equity = equity
            self.daily_stopped = False
            self.entries = 0
        if equity <= 0 or peak <= 0 or equity < peak * (1 - self.dd_halt):
            self.permanent_stopped = True
        if self.permanent_stopped:
            return 0., "permanent_drawdown_halt"
        if equity < self.day_start_equity * (1 - self.daily_halt):
            self.daily_stopped = True
        if self.daily_stopped:
            return 0., "daily_loss_halt"
        if requested > current_weight + .01:
            if self.entries >= self.entry_cap:
                return min(requested, current_weight), "new_entry_cap"
            self.entries += 1
        return requested, "allowed"


def fill_at_open(cash: float, units: float, price: float, target: float,
                 fee: float, slippage: float, threshold: float = .005):
    """Simplified fee/slippage-inclusive paper fill. No spread, latency or order-book model."""
    equity = cash + units * price
    desired = target * equity
    delta = desired - units * price
    if abs(delta) < threshold * equity:
        return cash, units, 0., "hold"
    if delta > 0:
        notional = min(delta, cash / (1 + fee + slippage))
        units += notional / (price * (1 + slippage))
        cash -= notional * (1 + fee)
        return cash, units, notional, "buy"
    notional = min(-delta, units * price)
    qty = notional / price
    cash += qty * price * (1 - slippage) * (1 - fee)
    units = max(0., units - qty)
    return cash, units, notional, "sell"


class PaperPortfolio:
    def __init__(self, capital: float, fee: float, slippage: float):
        self.cash, self.units, self.capital = capital, 0., capital
        self.fee, self.slippage = fee, slippage
        self.peak = capital
        self.orders, self.turnover, self.exposures = 0, 0., []
        self.equity_history = [capital]
        self.gate = RiskGate()

    def step(self, bar: Bar, target: float, *, use_risk_gate: bool = True,
             execute: bool = True):
        equity = self.cash + self.units * bar.open
        self.peak = max(self.peak, equity)
        current = self.units * bar.open / equity
        if use_risk_gate:
            allowed, reason = self.gate.allow(target, equity, self.peak, bar.timestamp, current)
        else:
            allowed, reason = target, "passive_reference"
        if execute:
            self.cash, self.units, turnover, action = fill_at_open(
                self.cash, self.units, bar.open, allowed, self.fee, self.slippage)
        else:
            turnover, action = 0., "hold"
        if turnover > 0:
            self.orders += 1
            self.turnover += turnover
        close_equity = self.cash + self.units * bar.close
        self.peak = max(self.peak, close_equity)
        self.equity_history.append(close_equity)
        exposure = self.units * bar.close / close_equity
        self.exposures.append(exposure)
        return {"requested": target, "allowed": allowed, "gate": reason,
                "action": action, "turnover": turnover, "equity": close_equity,
                "exposure": exposure, "cash": self.cash, "units": self.units}

    def summary(self):
        peak, dd = self.capital, 0.
        for equity in self.equity_history:
            peak = max(peak, equity)
            dd = max(dd, 1 - equity / peak)
        finish = self.equity_history[-1]
        return {"start": self.capital, "finish": round(finish, 4),
                "net_return_pct": round(100 * (finish / self.capital - 1), 4),
                "max_drawdown_pct": round(dd * 100, 4),
                "avg_exposure_pct": round(mean(self.exposures) * 100, 4),
                "orders": self.orders, "notional_turnover": round(self.turnover, 4),
                "fees_estimated": round(self.turnover * self.fee, 4)}


def run(bars: Sequence[Bar], *, fee: float = .008, slippage: float = .0005,
        capital: float = 10000., include_tacm: bool = True):
    """Replay historical completed candles. Do not reuse output as forward-test evidence."""
    if len(bars) < 100 or not (0 <= fee < .1 and 0 <= slippage < .1) or capital <= 0:
        raise ValueError("Bad run parameters")
    variants = ["plain", "simple_vol_guard", "cash", "passive_10pct"]
    if include_tacm:
        # Existing v0.1 controller is imported unmodified from this repository.
        from governor import Proposal, Observation, TrigunaGovernor
        govs = {"tacm_full": TrigunaGovernor(),
                "tacm_no_tamas": TrigunaGovernor(variant="no_tamas")}
        variants += list(govs)
    else:
        govs = {}
    ledgers = {name: PaperPortfolio(capital, fee, slippage) for name in variants}
    traces = {name: [] for name in variants}
    turnover_windows = {name: deque(maxlen=24) for name in variants}
    returns = {name: deque(maxlen=48) for name in ("momentum_12_48", "mean_revert_z24")}
    last_open = None
    last_signals = None
    previous_signals = None
    for t in range(50, len(bars)):
        bar = bars[t]
        completed = bars[:t]
        signals = standard_agents(completed)
        if last_open is not None:
            delta = bar.open / last_open - 1
            for name, buff in returns.items():
                old = last_signals[name]
                earlier = previous_signals[name] if previous_signals else 0.
                buff.append(old * delta - abs(old - earlier) * (fee + slippage))
        previous_signals, last_signals = last_signals, {s.agent: s.target for s in signals}
        last_open = bar.open
        chosen = max(signals, key=lambda s: s.confidence)
        simple_target = .1 * chosen.target
        closes = [b.close for b in completed]
        r24 = [closes[i] / closes[i-1] - 1 for i in range(len(closes)-24, len(closes))]
        r48 = [closes[i] / closes[i-1] - 1 for i in range(len(closes)-48, len(closes)-24)]
        vol_ratio = pstdev(r24) / max(pstdev(r48), .0001)
        for name in variants:
            ledger = ledgers[name]
            pre_equity = ledger.cash + ledger.units * bar.open
            agent = chosen.agent
            reason = "unmodified highest-confidence agent"
            if name == "cash":
                target, reason = 0., "cash reference"
            elif name == "passive_10pct":
                # Passive buys once at 10% and then remains unchanged: no continuous rebalancing.
                target, reason = .10, "10% buy-and-hold reference"
            elif name == "simple_vol_guard":
                target = 0. if vol_ratio >= 2 else simple_target
                reason = "simple 2x-volatility filter"
            elif name in govs:
                gov = govs[name]
                obs = Observation(bar.timestamp, tuple(b.open for b in completed),
                                  tuple(b.close for b in completed), pre_equity,
                                  max(ledger.peak, pre_equity),
                                  {k: list(v) for k, v in returns.items()},
                                  mean(turnover_windows[name]) if turnover_windows[name] else 0.)
                proposals = [Proposal(s.agent, s.target, s.confidence) for s in signals]
                decision = gov.decide(obs, proposals)
                target, agent, reason = decision.target_weight, decision.selected_agent, decision.intervention
            else:
                target = simple_target
            is_passive = name == "passive_10pct"
            first_step = (t == 50)
            outcome = ledger.step(bar, target, use_risk_gate=not is_passive,
                                  execute=(not is_passive or first_step))
            turnover_windows[name].append(outcome["turnover"] / max(pre_equity, 1.))
            traces[name].append({"timestamp": bar.timestamp.isoformat(),
                "agent": agent, "supervisor": name, "reason": reason,
                "trend_signal": last_signals["momentum_12_48"],
                "reversion_signal": last_signals["mean_revert_z24"],
                "vol_ratio": round(vol_ratio, 6),
                **{k: (round(v, 8) if isinstance(v, float) else v)
                   for k, v in outcome.items()}})
    summary = {"mode": "HISTORICAL_BACKTEST_NOT_FORWARD", "paper_only": True,
               "first_decision": bars[50].timestamp.isoformat(),
               "last_decision": bars[-1].timestamp.isoformat(),
               "bars": len(bars) - 50, "capital": capital,
               "fee_per_side": fee, "slippage_per_side": slippage,
               "notes": "Same deterministic proposals and bars; fixed 10% maximum exposure. Average exposure remains unequal; account for it in comparisons. Open-only idealized execution; no venue orders.",
               "variants": {name: ledgers[name].summary() for name in variants}}
    return summary, traces


def main():
    ap = argparse.ArgumentParser(description="PAPER ONLY: compare boring bots with TACM supervisory variants")
    ap.add_argument("csv", help="Completed UTC OHLCV CSV or existing paper-only market snapshot JSON")
    ap.add_argument("--out", default="supervisor_lab_results")
    ap.add_argument("--fee", type=float, default=.008, help="Assumed taker fee per side (default 0.8%%)")
    ap.add_argument("--slippage", type=float, default=.0005)
    ap.add_argument("--no-tacm", action="store_true", help="Run reference policies without existing governor")
    args = ap.parse_args()
    summary, traces = run(load_bars(args.csv), fee=args.fee, slippage=args.slippage,
                          include_tacm=not args.no_tacm)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for name, rows in traces.items():
        with (out / (name + ".csv")).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    for name, v in summary["variants"].items():
        print(f"{name:17} return={v['net_return_pct']:8.3f}%  dd={v['max_drawdown_pct']:7.3f}%  exposure={v['avg_exposure_pct']:6.3f}%")
    print("PAPER ONLY; files:", out.resolve())


if __name__ == "__main__":
    main()
