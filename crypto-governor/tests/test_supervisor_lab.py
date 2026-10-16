"""Causal, reproducible paper-only experiment checks, no network required."""
import math
import json
import tempfile
import types
from unittest.mock import patch
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from supervisor_lab import Bar, standard_agents, RiskGate, fill_at_open, run, load_bars


def candles(n=160):
    dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out = []
    last = 100.
    for i in range(n):
        o = last
        c = o * (1 + .003 * math.sin(i / 6) + .00015)
        h = max(o, c) * 1.002
        l = min(o, c) * .998
        out.append(Bar(dt + timedelta(hours=i), o, h, l, c, 1000))
        last = c
    return out


class ContractTests(unittest.TestCase):
    def test_signals_have_clear_domain(self):
        signals = standard_agents(candles()[:50])
        self.assertEqual([s.agent for s in signals], ["momentum_12_48", "mean_revert_z24"])
        self.assertTrue(all(s.target in (0., 1.) and 0 <= s.confidence <= 1 for s in signals))

    def test_agents_only_see_completed_data(self):
        bars = candles(140)
        first = standard_agents(bars[:80])
        last = bars[-1]
        bars[-1] = Bar(last.timestamp, 9e8, 9e8+1, 9e8-1, 9e8, last.volume)
        self.assertEqual(first, standard_agents(bars[:80]))

    def test_no_tacm_reference_simulations_repeat(self):
        b = candles()
        a, ta = run(b, include_tacm=False)
        other, tb = run(b, include_tacm=False)
        self.assertEqual((a, ta), (other, tb))
        self.assertEqual(a["mode"], "HISTORICAL_BACKTEST_NOT_FORWARD")
        self.assertTrue(a["paper_only"])
        self.assertEqual(a["variants"]["cash"]["orders"], 0)
        self.assertEqual(a["variants"]["cash"]["net_return_pct"], 0.)
        self.assertEqual(a["variants"]["passive_10pct"]["orders"], 1)
        self.assertTrue(all(row["allowed"] <= .1 + 1e-9
                            for name in ta for row in ta[name]))

    def test_backtest_prefix_independent_of_future_candles(self):
        b = candles(160)
        a, ta = run(b[:120], include_tacm=False)
        _, tb = run(b, include_tacm=False)
        for name in ta:
            self.assertEqual(ta[name], tb[name][:len(ta[name])])

    def test_fees_make_buy_then_sell_costly(self):
        cash, units, size, direction = fill_at_open(1000., 0., 100., .10, .008, .0005)
        self.assertEqual(direction, "buy")
        cash, units, _, direction = fill_at_open(cash, units, 100., 0., .008, .0005)
        self.assertEqual(direction, "sell")
        self.assertAlmostEqual(units, 0., places=9)
        self.assertLess(cash, 1000.)

    def test_repo_governor_adapter_contract_with_test_double(self):
        # This tests the adapter wiring, not the actual v0.1 governor implementation.
        class FakeProposal:
            def __init__(self, agent, target, confidence):
                self.agent, self.target, self.confidence = agent, target, confidence
        class FakeObservation:
            def __init__(self, time, opens, closes, equity, peak, returns, turnover=0):
                assert len(opens) == len(closes) >= 50
                assert all(isinstance(x, float) for x in closes)
                self.turnover = turnover
        class FakeGovernor:
            def __init__(self, variant='full'):
                self.variant = variant
            def decide(self, obs, proposals):
                return types.SimpleNamespace(target_weight=.05 * proposals[0].target,
                    selected_agent=proposals[0].agent, intervention='test_stub')
        fake = types.ModuleType('governor')
        fake.Proposal, fake.Observation, fake.TrigunaGovernor = FakeProposal, FakeObservation, FakeGovernor
        with patch.dict(sys.modules, {'governor': fake}):
            summary, traces = run(candles(), include_tacm=True)
        self.assertIn('tacm_full', traces)
        self.assertIn('tacm_no_tamas', traces)
        self.assertTrue(all(row['allowed'] <= .1 for row in traces['tacm_full']))
        self.assertEqual(summary['mode'], 'HISTORICAL_BACKTEST_NOT_FORWARD')

    def test_existing_snapshot_loader_and_demo_guard(self):
        b = candles(125)
        payload = {'paper_only': True, 'mode': 'market', 'candles': [
            [int(x.timestamp.timestamp()), x.open, x.high, x.low, x.close, x.volume] for x in b]}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'example.json'
            path.write_text(json.dumps(payload))
            self.assertEqual(len(load_bars(str(path))), 125)
            payload['mode'] = 'synthetic_demo'
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                load_bars(str(path))

    def test_hard_gate_cannot_be_bypassed(self):
        gate = RiskGate()
        self.assertRaises(ValueError, gate.allow, .5, 100., 100., candles()[0].timestamp, 0.)
        target, reason = gate.allow(.1, 94., 100., candles()[0].timestamp, 0.)
        self.assertEqual((target, reason), (0., "permanent_drawdown_halt"))
        target2, reason2 = gate.allow(.1, 102., 102., candles()[1].timestamp, 0.)
        self.assertEqual((target2, reason2), (0., "permanent_drawdown_halt"))


if __name__ == "__main__":
    unittest.main()
