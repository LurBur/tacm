"""Causal, next-open, fee-inclusive research backtest. Never sends live orders."""
from __future__ import annotations
import argparse, csv, json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from statistics import mean, pstdev
from governor import Proposal, Observation, TrigunaGovernor, PlainSelector, IndependentRiskGate

@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def read_bars(path: str) -> list[Bar]:
    out = []
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            t = row['timestamp'].replace('Z', '+00:00')
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                raise ValueError('Timestamps must be timezone-aware UTC')
            dt = dt.astimezone(timezone.utc)
            o,h,l,c,v = (float(row[k]) for k in ['open','high','low','close','volume'])
            if not all(isfinite(n) for n in [o,h,l,c,v]) or min(o,h,l,c) <= 0 or v < 0 or h < max(o,c,l) or l > min(o,c,h):
                raise ValueError(f'Invalid OHLCV candle: {dt}')
            if out and dt <= out[-1].timestamp:
                raise ValueError('Bars must be chronological without duplicates')
            out.append(Bar(dt,o,h,l,c,v))
    if len(out)<100: raise ValueError('Need >=100 candle rows for this demonstration')
    spacing=[(out[i].timestamp-out[i-1].timestamp).total_seconds() for i in range(1,len(out))]
    expected=sorted(spacing)[len(spacing)//2]
    if expected <= 0 or any(abs(step-expected) > 1 for step in spacing):
        raise ValueError('Missing or irregular bars detected; repair the dataset first')
    return out


def proposals_from_completed_bars(completed: list[Bar]) -> list[Proposal]:
    """Two transparent placeholders for future AI signals. No future candles."""
    closes=[x.close for x in completed]
    fast=mean(closes[-12:]); slow=mean(closes[-48:]); last=closes[-1]
    trend_gap=fast/slow-1
    momentum=Proposal('momentum', float(trend_gap > 0.001), min(1.0, 0.3 + abs(trend_gap)*25))
    center=mean(closes[-24:]); sd=max(1e-6,pstdev(closes[-24:]))
    z=(last-center)/sd
    reversion=Proposal('mean_revert', float(z < -.5), min(1.0,0.25 + abs(z)*.18))
    return [momentum,reversion]


def execute_rebalance(cash:float, units:float, open_price:float, target:float,
                      fee:float = 0.001, slip:float = 0.0005):
    """Return cash, units, and USD turnover for a market-style fill at current open.

    Fee and slippage are charged separately per execution direction. This is
    not a realistic fill simulator for market impact, spread, outages, or gaps.
    """
    equity=cash + units * open_price
    target_value=equity * target
    actual_value=units * open_price
    delta=target_value-actual_value
    if abs(delta)<equity*.005: return cash,units,0.0
    if delta > 0:
        max_delta=cash/(1+fee+slip)
        notional=min(delta,max_delta)
        new_units=notional/(open_price*(1+slip))
        cash-=notional*(1+fee)
        units+=new_units
        return cash,units,notional
    else:
        notional=min(-delta, actual_value)
        qty=notional/open_price
        cash+=qty*open_price*(1-slip)*(1-fee)
        units=max(0.0,units-qty)
        return cash,units,notional


def run(bars:list[Bar], variant:str='full', starting_cash:float=10000,
        fee:float=.001, slippage:float=.0005) -> tuple[dict,list[dict]]:
    if not 0 <= fee < .1 or not 0 <= slippage < .1: raise ValueError('Cost inputs out of range')
    governor= PlainSelector() if variant == 'baseline' else TrigunaGovernor(variant=variant)
    gate=IndependentRiskGate()
    cash=float(starting_cash); units=0.; peak=cash
    audit=[]; strategy_returns={'momentum':deque(maxlen=48),'mean_revert':deque(maxlen=48)}
    prev_proposals={}; prev_open=None; prev_targets={}; active_agent=None
    change_count=0; turnover_window=deque(maxlen=24)
    starting_time=bars[50].timestamp
    for t in range(50,len(bars)):
        bar=bars[t]; completed=bars[:t] # all indicators use strictly prior candles
        proposals=proposals_from_completed_bars(completed)
        pmap={p.agent:p for p in proposals}
        if prev_open is not None:
            r=bar.open/prev_open-1
            for name in strategy_returns:
                position=prev_proposals.get(name,0.0)
                # Shadow one-bar net-of-change-cost evidence; not an executable shadow portfolio.
                changed=abs(position-prev_targets.get(name,0.0))
                strategy_returns[name].append(position*r - changed*(fee+slippage))
        equity_before=cash+units*bar.open
        peak=max(peak,equity_before)
        obs=Observation(bar.timestamp,tuple(b.open for b in completed),
                        tuple(b.close for b in completed),equity_before,peak,
                        {k:list(v) for k,v in strategy_returns.items()},
                        mean(turnover_window) if turnover_window else 0.0)
        decision=governor.decide(obs,proposals)
        current_weight=units*bar.open/equity_before
        allowed,gate_reason=gate.allow(decision.target_weight,equity_before,peak,bar.timestamp,current_weight)
        before_units=units
        cash,units,notional=execute_rebalance(cash,units,bar.open,allowed,fee,slippage)
        turnover_window.append(notional/max(equity_before,1))
        if notional>0: change_count+=1
        equity_close=cash+units*bar.close
        peak=max(peak,equity_close)
        audit.append({
            'timestamp':bar.timestamp.isoformat(), 'price_open':bar.open, 'price_close':bar.close,
            'agent':decision.selected_agent, 'phase':decision.phase,
            'diagnostic_81':decision.diagnostic_81, 'sattva':decision.sattva,
            'rajas':decision.rajas, 'tamas':decision.tamas,
            'advantage_decay':decision.advantage_decay,'intervention':decision.intervention,
            'target_weight':round(decision.target_weight,6),'allowed_weight':round(allowed,6),
            'risk_gate':gate_reason,'dollar_turnover':round(notional,4),
            'units':round(units,8), 'equity':round(equity_close,4)
        })
        prev_targets=prev_proposals.copy()
        prev_proposals={p.agent:p.target for p in proposals}
        prev_open=bar.open
    last=bars[-1]
    final_equity=cash+units*last.close
    eq=[starting_cash]+[row['equity'] for row in audit]
    historical_peak=starting_cash; max_dd=0.0
    for e in eq:
        historical_peak=max(historical_peak,e)
        max_dd=max(max_dd,1-e/historical_peak)
    returns=[eq[i]/eq[i-1]-1 for i in range(1,len(eq))]
    std=pstdev(returns) if len(returns)>1 else 0
    # Per-candle Sharpe only; annualized requires verified bar frequency.
    sharpe=(mean(returns)/std) if std>0 else 0
    summary={
        'variant':variant,'starting_cash':starting_cash,'final_equity':round(final_equity,2),
        'net_return_pct':round(100*(final_equity/starting_cash-1),3),
        'max_drawdown_pct':round(100*max_dd,3), 'sharpe_per_bar':round(sharpe,4),
        'orders_executed':change_count,'total_notional_traded':round(sum(r['dollar_turnover'] for r in audit),2),
        'fees_assumed_bps':fee*10000,'slippage_assumed_bps':slippage*10000,
        'period_start':starting_time.isoformat(),'period_end':last.timestamp.isoformat(),
        'bars':len(audit),'risk_gate_blocks':sum(row['risk_gate']!='allowed' for row in audit),
        'source':'USER_SUPPLIED_CSV'}
    return summary,audit


def main():
    p=argparse.ArgumentParser(description='Research-only, no-live-trading Tri-Guna ablation backtest')
    p.add_argument('csv',help='Chronological timezone-aware OHLCV CSV')
    p.add_argument('--out',default='results')
    p.add_argument('--fee',type=float,default=.001)
    p.add_argument('--slippage',type=float,default=.0005)
    a=p.parse_args()
    data=read_bars(a.csv)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    all_rows=[]
    for v in ['baseline','full','no_sattva','no_rajas','no_tamas']:
        result,trace=run(data,v,fee=a.fee,slippage=a.slippage)
        all_rows.append(result)
        with (out/f'trace_{v}.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(trace[0]));w.writeheader();w.writerows(trace)
    (out/'comparison.json').write_text(json.dumps(all_rows,indent=2))
    for x in all_rows:print(f"{x['variant']:12} return={x['net_return_pct']:8.3f}% maxDD={x['max_drawdown_pct']:7.3f}% trades={x['orders_executed']}")
    print(f'Research output: {out.resolve()}')

if __name__=='__main__': main()