"""Causal, persistent, quote-executed PAPER-ONLY TACM study.

A GitHub Actions run is a separate paper observation. No exchange credentials,
private APIs, leverage, order submission, or autonomous capital management.
Never reinterpret historical replay as forward paper evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import deque
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from statistics import mean, pstdev
from urllib.request import Request, urlopen

from supervisor_lab import RiskGate, load_bars, standard_agents
from governor import Observation, Proposal, TrigunaGovernor

VARIANTS = ("plain", "plain_3pct", "simple_vol_guard", "tacm_full",
            "tacm_no_tamas", "cash", "passive_10pct", "passive_3pct")
SECONDS = 3600


def utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Expected UTC offset-aware timestamp")
    return dt.astimezone(timezone.utc)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def initial_portfolio(capital):
    return {"cash": float(capital), "units": 0.0, "peak": float(capital),
            "orders": 0, "turnover": 0.0, "fees": 0.0, "slippage": 0.0,
            "observations": 0, "exposure_sum": 0.0,
            "gate": dict(RiskGate().__dict__)}


def initial_state(symbol, capital, fee, slippage, now):
    return {"schema": 1, "mode": "FORWARD_PAPER_ONLY", "symbol": symbol,
            "started_at": now.isoformat(), "last_candle_open": None,
            "last_hash": "GENESIS", "fee": fee, "slippage": slippage,
            "capital": capital,
            "portfolios": {k: initial_portfolio(capital) for k in VARIANTS},
            "governors": {}, "shadow": {k: [] for k in
                      ("momentum_12_48", "mean_revert_z24")},
            "last_signals": None, "before_last_signals": None,
            "last_close": None, "last_quote_at": None, "events": 0}


def restore_governor(variant, obj):
    gov = TrigunaGovernor(variant=variant)
    if obj is not None:
        gov.incumbent = obj["incumbent"]
        gov.prev_strengths = dict(obj["prev_strengths"])
        gov.cooldown_until_bar = obj["cooldown_until_bar"]
        gov.bar_index = obj["bar_index"]
        gov.selection_history = deque(obj["selection_history"], maxlen=12)
    return gov


def save_governor(gov):
    return {"incumbent": gov.incumbent, "prev_strengths": gov.prev_strengths,
            "cooldown_until_bar": gov.cooldown_until_bar,
            "bar_index": gov.bar_index,
            "selection_history": list(gov.selection_history)}


def validate_inputs(snapshot, quote, now, symbol):
    if snapshot.get("mode") != "market" or snapshot.get("paper_only") is not True:
        raise ValueError("Refuse unlabeled or synthetic market snapshot")
    if snapshot.get("symbol") != symbol:
        raise ValueError("Market symbol mismatch")
    candle_open = utc(snapshot["last_completed_candle"])
    candles = snapshot.get("candles")
    if not candles or int(candles[-1][0]) != int(candle_open.timestamp()):
        raise ValueError("Snapshot terminal candle mismatch")
    if not (0 <= (now - candle_open - timedelta(hours=1)).total_seconds() <= 5400):
        raise ValueError("Market data is stale or unfinished")
    generated = utc(snapshot["generated_at"])
    if generated > now + timedelta(minutes=1) or generated < candle_open:
        raise ValueError("Invalid snapshot generation time")
    observed = utc(quote["observed_at"])
    if not (0 <= (now - observed).total_seconds() <= 300):
        raise ValueError("Quote missing, stale, or in the future")
    bid, ask = float(quote["bid"]), float(quote["ask"])
    if not all(isfinite(x) and x > 0 for x in (bid, ask)) or bid > ask:
        raise ValueError("Invalid or crossed public bid/ask quote")
    return candle_open, observed, bid, ask


def paper_fill(p, allowed, gate_name, bid, ask, fee, slip):
    midpoint = (bid + ask) / 2
    pre_equity = p["cash"] + p["units"] * midpoint
    if pre_equity <= 0:
        raise ValueError("Paper portfolio equity invalid")
    existing = p["units"] * midpoint
    action, qty, cost = "hold", 0.0, 0.0
    delta = allowed * pre_equity - existing
    if abs(delta) >= pre_equity * .005 or (allowed == 0.0 and p["units"] > 1e-12):
        if delta > 0:
            fill_price = ask * (1 + slip)
            qty = min(delta / fill_price, p["cash"] / (fill_price * (1 + fee)))
            cost = qty * fill_price * fee
            p["cash"] -= qty * fill_price + cost
            p["units"] += qty
            action = "buy"
            p["slippage"] += qty * (fill_price - ask)
            turnover = qty * fill_price
        else:
            fill_price = bid * (1 - slip)
            qty = min(-delta / midpoint, p["units"])
            cost = qty * fill_price * fee
            p["cash"] += qty * fill_price - cost
            p["units"] -= qty
            action = "sell"
            p["slippage"] += qty * (bid - fill_price)
            turnover = qty * fill_price
        p["fees"] += cost
        p["turnover"] += turnover
        p["orders"] += 1
    p["units"] = max(0.0, p["units"])
    if p["cash"] < -1e-7 or not all(isfinite(x) for x in (p["cash"], p["units"])):
        raise ValueError("Invalid paper fill accounting")
    p["cash"] = max(0.0, p["cash"])
    equity = p["cash"] + p["units"] * midpoint
    p["peak"] = max(p["peak"], equity)
    exposure = p["units"] * midpoint / equity
    p["exposure_sum"] += exposure
    p["observations"] += 1
    return {"action": action, "units_filled": qty, "fee": cost,
            "equity": equity, "exposure": exposure, "cash": p["cash"],
            "units": p["units"], "gate": gate_name}


def advance(snapshot, quote, previous, *, now, symbol, fee=.008,
            slippage=.0005, capital=10000.0):
    """Return (new_state, event); event None means duplicate snapshot (no action).

    The code intentionally cannot backfill missing observations or change fee
    assumptions after initialization. On a gap it fails closed for review.
    """
    if now.tzinfo is None:
        raise ValueError("now must be offset-aware")
    now = now.astimezone(timezone.utc)
    if not 0 <= fee < .1 or not 0 <= slippage < .1 or capital <= 0:
        raise ValueError("Invalid paper settings")
    candle_open, observed, bid, ask = validate_inputs(snapshot, quote, now, symbol)
    bars = load_bars_from_snapshot(snapshot)
    skipped_hours = 0
    if previous is None:
        state = initial_state(symbol, capital, fee, slippage, now)
    else:
        state = json.loads(canonical(previous))
        if state.get("schema") != 1 or state.get("mode") != "FORWARD_PAPER_ONLY":
            raise ValueError("Unknown state schema")
        if state["symbol"] != symbol or any(
                state[k] != v for k, v in
                (("fee", fee), ("slippage", slippage), ("capital", capital))):
            raise ValueError("Cannot silently change paper parameters")
        previous_open = utc(state["last_candle_open"])
        diff = (candle_open - previous_open).total_seconds()
        if diff == 0:
            return state, None
        if diff < SECONDS or diff % SECONDS != 0:
            raise ValueError("Missing or reordered paper interval; fail closed")
        # A late GitHub job is not evidence of market decisions in skipped hours.
        # At the first new observation, flatten active paper portfolios and log it.
        skipped_hours = int(diff / SECONDS) - 1
        if observed <= utc(state["started_at"]):
            raise ValueError("Quote predates initialization")
        if state.get("last_quote_at") and observed <= utc(state["last_quote_at"]):
            raise ValueError("Non-monotonic quote time; refuse replay")
    signals = standard_agents(bars)
    signal_map = {s.agent: s.target for s in signals}
    closes = [b.close for b in bars]
    if state["last_close"] is not None and skipped_hours == 0:
        change = closes[-1] / state["last_close"] - 1
        for name in state["shadow"]:
            prev = state["last_signals"][name]
            earlier = (state["before_last_signals"] or {}).get(name, 0.0)
            buffer = state["shadow"][name]
            buffer.append(prev * change - abs(prev - earlier) * (fee + slippage))
            del buffer[:-48]
    returns24 = [closes[i] / closes[i-1] - 1
                 for i in range(len(closes)-24, len(closes))]
    earlier24 = [closes[i] / closes[i-1] - 1
                 for i in range(len(closes)-48, len(closes)-24)]
    ratio = pstdev(returns24) / max(pstdev(earlier24), .0001)
    chosen = max(signals, key=lambda s: s.confidence)
    proposals = [Proposal(s.agent, s.target, s.confidence) for s in signals]
    decisions = {}
    for name in VARIANTS:
        p = state["portfolios"][name]
        midpoint = (bid + ask) / 2
        equity_before = p["cash"] + p["units"] * midpoint
        p["peak"] = max(p["peak"], equity_before)
        target = (.03 if name == "plain_3pct" else .10) * chosen.target
        agent = chosen.agent
        if name == "simple_vol_guard" and ratio >= 2:
            target = 0.0
        if name == "cash":
            target = 0.0
        if name in ("passive_10pct", "passive_3pct"):
            # Fixed 10% or 3% initial purchase, never continuous rebalancing.
            target = (.10 if name == "passive_10pct" else .03) if p["observations"] == 0 else (
                p["units"] * midpoint / equity_before)
        if name.startswith("tacm_") and skipped_hours == 0:
            variant = "full" if name == "tacm_full" else "no_tamas"
            gov = restore_governor(variant, state["governors"].get(name))
            observation = Observation(observed, tuple(b.open for b in bars),
                tuple(closes), equity_before, p["peak"],
                {k: list(v) for k, v in state["shadow"].items()}, 0.0)
            decision = gov.decide(observation, proposals)
            target, agent = decision.target_weight, decision.selected_agent
            state["governors"][name] = save_governor(gov)
        if skipped_hours and name not in ("cash", "passive_10pct", "passive_3pct"):
            target = 0.0  # fail-safe re-entry pause; no fabricated missed-hour fills
        if name in ("cash", "passive_10pct", "passive_3pct"):
            allowed, reason = target, "reference"
        else:
            gate = RiskGate()
            gate.__dict__.update(p["gate"])
            if isinstance(gate.day, str):
                gate.day = date.fromisoformat(gate.day)
            weight = p["units"] * midpoint / equity_before
            allowed, reason = gate.allow(target, equity_before, p["peak"],
                                         observed, weight)
            p["gate"] = dict(gate.__dict__)
            if p["gate"]["day"] is not None:
                p["gate"]["day"] = p["gate"]["day"].isoformat()
        if skipped_hours and name not in ("cash", "passive_10pct", "passive_3pct"):
            reason = "missed_interval_flatten_at_observed_quote"
        fill = paper_fill(p, allowed, reason, bid, ask, fee, slippage)
        decisions[name] = {"agent": agent, "requested": target,
                           "allowed": allowed, **fill}
    event = {
        "mode": "FORWARD_PAPER_ONLY", "symbol": symbol,
        "timestamp": now.isoformat(), "quote_at": observed.isoformat(),
        "candle_open": candle_open.isoformat(),
        "bar_close": closes[-1], "bid": bid, "ask": ask,
        "signals": {s.agent: {"target": s.target, "confidence": s.confidence,
                              "evidence": s.evidence} for s in signals},
        "volatility_ratio": ratio, "skipped_unobserved_hours": skipped_hours,
        "decisions": decisions,
        "prev_hash": state["last_hash"], "number": state["events"] + 1
    }
    event["hash"] = hashlib.sha256(canonical(event).encode()).hexdigest()
    state["events"] += 1
    state["last_hash"] = event["hash"]
    state["last_candle_open"] = candle_open.isoformat()
    state["before_last_signals"] = state["last_signals"]
    state["last_signals"] = signal_map
    state["last_close"] = closes[-1]
    state["last_quote_at"] = observed.isoformat()
    return state, event


def load_bars_from_snapshot(snapshot):
    from supervisor_lab import Bar, validate_bars
    raw = snapshot["candles"]
    bars = [Bar(datetime.fromtimestamp(float(row[0]), timezone.utc),
                *[float(x) for x in row[1:]]) for row in raw]
    return validate_bars(bars)


def fetch_quote(symbol):
    pair = {"BTCUSD": "XBTUSD", "ETHUSD": "ETHUSD"}[symbol]
    req = Request("https://api.kraken.com/0/public/Ticker?pair=" + pair,
                  headers={"User-Agent": "TACM-Forward-Paper-Research/0.3"})
    with urlopen(req, timeout=18) as response:
        payload = json.load(response)
        observed = datetime.now(timezone.utc)
    if payload.get("error"):
        raise ValueError("Kraken public ticker error")
    pairs = list(payload.get("result", {}).values())
    if len(pairs) != 1:
        raise ValueError("Unexpected Kraken public ticker response")
    return {"bid": float(pairs[0]["b"][0]),
            "ask": float(pairs[0]["a"][0]),
            "observed_at": observed.isoformat()}


def atomic_text(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=".paper-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_step(state_path, journal_path, state, event):
    state_path, journal_path = Path(state_path), Path(journal_path)
    history = journal_path.read_text(encoding="utf-8") if journal_path.exists() else ""
    rows = [json.loads(x) for x in history.splitlines() if x.strip()]
    # Verify the complete public hash chain, not merely the last checkpoint.
    last = "GENESIS"
    for index, recorded in enumerate(rows, start=1):
        item = dict(recorded)
        recorded_hash = item.pop("hash", None)
        digest = hashlib.sha256(canonical(item).encode()).hexdigest()
        if item.get("prev_hash") != last or item.get("number") != index or digest != recorded_hash:
            raise ValueError("Paper journal integrity/hash chain failure")
        last = recorded_hash
    old = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    if (old is None and rows) or (old is not None and
        (not rows or rows[-1]["hash"] != old["last_hash"] or
         len(rows) != old["events"])):
        raise ValueError("Paper state/journal mismatch; refuse to overwrite")
    if event["prev_hash"] != (old["last_hash"] if old else "GENESIS"):
        raise ValueError("Paper ledger hash chain mismatch")
    # GitHub commits state and journal together, providing the durable checkpoint.
    atomic_text(journal_path, history + canonical(event) + "\n")
    atomic_text(state_path, json.dumps(state, indent=2, allow_nan=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description="FORWARD PAPER ONLY; public quotes, never orders")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--symbol", required=True, choices=("BTCUSD", "ETHUSD"))
    ap.add_argument("--state", required=True)
    ap.add_argument("--journal", required=True)
    ap.add_argument("--fee", type=float, default=.008)
    ap.add_argument("--slippage", type=float, default=.0005)
    args = ap.parse_args()
    path = Path(args.state)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    snap = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    quote = fetch_quote(args.symbol)
    now = datetime.now(timezone.utc)
    newer, event = advance(snap, quote, old, now=now, symbol=args.symbol,
                           fee=args.fee, slippage=args.slippage)
    if event is None:
        print("NOOP: already observed this completed candle")
    else:
        save_step(path, args.journal, newer, event)
        print("FORWARD PAPER ONLY:", args.symbol, "observation", newer["events"],
              "quote", event["quote_at"], "hash", event["hash"][:14])


if __name__ == "__main__":
    main()
