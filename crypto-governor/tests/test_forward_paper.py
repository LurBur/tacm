"""No network, no live credentials: stateful forward-paper contract tests."""
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forward_paper import advance, initial_portfolio, paper_fill, save_step


def fixture(n=130, *, pair="BTCUSD", start=None):
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    price = 100.0
    for i in range(n):
        o = price
        c = o * (1 + .003 * math.sin(i / 6) + .0001)
        h = max(o, c) * 1.002
        l = min(o, c) * .998
        out.append([int((start + timedelta(hours=i)).timestamp()), o, h, l, c, 100])
        price = c
    last_open = start + timedelta(hours=n-1)
    at = last_open + timedelta(hours=1, minutes=15)
    snap = {"mode":"market", "paper_only":True,"symbol":pair,
            "generated_at":(at-timedelta(minutes=4)).isoformat(),
            "last_completed_candle":last_open.isoformat(),
            "candles":out}
    quote = {"observed_at":(at-timedelta(seconds=1)).isoformat(),
             "bid":price*.999, "ask":price*1.001}
    return snap, quote, at


class ForwardPaperTests(unittest.TestCase):
    def test_first_observation_is_genuine_forward_paper(self):
        snap, quote, now = fixture()
        state, event = advance(snap, quote, None, now=now, symbol="BTCUSD")
        self.assertEqual(state["events"], 1)
        self.assertEqual(state["last_hash"], event["hash"])
        self.assertEqual(event["prev_hash"], "GENESIS")
        self.assertEqual(len(event["decisions"]), 6)
        self.assertEqual(state["mode"], "FORWARD_PAPER_ONLY")
        self.assertTrue(all(0 <= d["allowed"] <= .100000001
                            for name, d in event["decisions"].items()
                            if name != "passive_10pct"))

    def test_duplicate_snapshot_does_not_repeat_trade(self):
        snap, quote, now = fixture()
        s1, _ = advance(snap, quote, None, now=now, symbol="BTCUSD")
        s2, event = advance(snap, quote, s1, now=now, symbol="BTCUSD")
        self.assertIsNone(event)
        self.assertEqual(s1, s2)

    def test_advance_governor_preserves_restart_state(self):
        snap, quote, now = fixture()
        s1, ev1 = advance(snap, quote, None, now=now, symbol="BTCUSD")
        s2snap, s2quote, later = fixture(131)
        s2, ev2 = advance(s2snap, s2quote,
                          json.loads(json.dumps(s1)), now=later, symbol="BTCUSD")
        self.assertEqual(s2["events"], 2)
        self.assertEqual(ev2["prev_hash"], ev1["hash"])
        self.assertEqual(s2["governors"]["tacm_full"]["bar_index"], 2)
        self.assertEqual(ev2["decisions"]["cash"]["equity"], 10000.0)

    def test_missing_hour_fails_closed(self):
        snap, quote, now = fixture()
        state, _ = advance(snap, quote, None, now=now, symbol="BTCUSD")
        missed, later_quote, later_now = fixture(132)
        with self.assertRaisesRegex(ValueError, "Missing or reordered"):
            advance(missed, later_quote, state, now=later_now, symbol="BTCUSD")

    def test_stale_and_unauthenticated_prices_rejected(self):
        snap, quote, now = fixture()
        stale = dict(quote, observed_at=(now-timedelta(minutes=8)).isoformat())
        with self.assertRaisesRegex(ValueError, "stale"):
            advance(snap, stale, None, now=now, symbol="BTCUSD")
        crossed = dict(quote, bid=quote["ask"]*1.001)
        with self.assertRaisesRegex(ValueError, "crossed"):
            advance(snap, crossed, None, now=now, symbol="BTCUSD")
        with self.assertRaisesRegex(ValueError, "synthetic"):
            advance(dict(snap, mode="synthetic_demo"), quote,
                    None, now=now, symbol="BTCUSD")

    def test_mutable_fee_assumptions_rejected(self):
        snap, quote, now = fixture()
        state, _ = advance(snap, quote, None, now=now, symbol="BTCUSD")
        snap2, quote2, now2 = fixture(131)
        with self.assertRaisesRegex(ValueError, "paper parameters"):
            advance(snap2, quote2, state, now=now2, symbol="BTCUSD", fee=.0025)

    def test_spread_and_fee_are_costs_not_profit(self):
        p = initial_portfolio(1000.0)
        entry = paper_fill(p, .10, "allowed", 99., 101., .008, .0005)
        self.assertEqual(entry["action"], "buy")
        exited = paper_fill(p, 0.0, "allowed", 99., 101., .008, .0005)
        self.assertEqual(exited["action"], "sell")
        self.assertAlmostEqual(p["units"], 0.0, places=9)
        self.assertLess(exited["equity"], 1000.)
        self.assertGreater(p["fees"], 0)

    def test_hash_journal_and_restarts(self):
        snap, quote, now = fixture()
        state, event = advance(snap, quote, None, now=now, symbol="BTCUSD")
        with tempfile.TemporaryDirectory() as d:
            path, journal = Path(d)/"state.json", Path(d)/"journal.jsonl"
            save_step(path, journal, state, event)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["last_hash"], json.loads(journal.read_text())["hash"])
            snap2, quote2, now2 = fixture(131)
            state2, event2 = advance(snap2, quote2, saved,
                                      now=now2, symbol="BTCUSD")
            save_step(path, journal, state2, event2)
            self.assertEqual(len(journal.read_text().splitlines()), 2)
            with self.assertRaisesRegex(ValueError, "hash chain"):
                save_step(path, journal, state2, event2)

    def test_quote_timestamp_must_be_causal(self):
        snap, quote, now = fixture()
        future = dict(quote, observed_at=(now+timedelta(minutes=1)).isoformat())
        with self.assertRaisesRegex(ValueError, "future"):
            advance(snap, future, None, now=now, symbol="BTCUSD")


if __name__ == "__main__":
    unittest.main()
