"""Offline tests for the independently hosted PAPER-only hourly observer."""
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import railway_observer as observer


def fixture(symbol, now):
    now = now.astimezone(timezone.utc)
    hour = now.replace(minute=0, second=0, microsecond=0)
    start = hour - timedelta(hours=132)
    rows = []
    p = 100.0
    for i in range(132):
        opened = start + timedelta(hours=i)
        o = p
        c = o * (1 + .001*math.sin(i/4))
        h, l = max(o, c)*1.002, min(o, c)*.998
        rows.append([int(opened.timestamp()), o, h, l, c, 14.0])
        p = c
    rows = rows[1:]
    snap = {"mode": "market", "paper_only": True, "symbol": symbol,
            "generated_at": now.isoformat(),
            "last_completed_candle": (hour-timedelta(hours=1)).isoformat(),
            "candles": rows}
    return snap, p


class RailwayObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = observer.ROOT
        observer.ROOT = self.root
        observer.LATEST["last_error"].clear()

    def tearDown(self):
        observer.ROOT = self.old
        self.tmp.cleanup()

    def test_one_event_and_duplicate_does_not_trade_twice(self):
        now = datetime.now(timezone.utc).replace(minute=14, second=0, microsecond=0)
        snap, price = fixture("BTCUSD", now)
        quote = {"bid": price*.999, "ask": price*1.001,
                 "observed_at": datetime.now(timezone.utc).isoformat()}
        result = observer.observe_symbol(
            "BTCUSD", now, lambda s,t:snap, lambda s:quote)
        self.assertIn("appended",result)
        again = observer.observe_symbol("BTCUSD", now, lambda s,t:None, lambda s:None)
        self.assertIn("already observed",again)
        state, journal, market = observer.files_for("BTCUSD")
        self.assertEqual(json.loads(state.read_text())["events"], 1)
        self.assertEqual(len(journal.read_text().splitlines()), 1)
        self.assertTrue(market.exists())
        self.assertEqual(json.loads(journal.read_text())["prev_hash"], "GENESIS")

    def test_an_error_cannot_fake_results(self):
        now = datetime.now(timezone.utc).replace(minute=14)
        results = observer.run_once(
            now,
            snapshot_fetcher=lambda s,t: (_ for _ in ()).throw(ValueError("offline")),
            quote_fetcher=lambda s:None)
        self.assertTrue(all(value.startswith("REJECTED") for value in results.values()))
        for sym in observer.SYMBOLS:
            state, journal, _ = observer.files_for(sym)
            self.assertFalse(state.exists())
            self.assertFalse(journal.exists())

    def test_health_before_first_hour_is_initializing(self):
        health = observer.health_payload()
        self.assertEqual(health["mode"], "FORWARD_PAPER_ONLY")
        self.assertEqual(health["symbols"]["BTCUSD"]["status"], "initializing")

    def test_http_route_does_not_allow_private_paths(self):
        self.assertNotIn("private",observer.PublicHandler.__dict__)
        self.assertEqual(observer.ALLOWED_ORIGIN,"https://lurbur.github.io")

    def test_kraken_ohlc_column_mapping_and_completed_bar(self):
        now = datetime.now(timezone.utc).replace(minute=14,second=0,microsecond=0)
        hour = now.replace(minute=0)
        t0 = hour - timedelta(hours=131)
        raw = []
        for i in range(132):
            ts = int((t0+timedelta(hours=i)).timestamp())
            raw.append([ts,"100","102","99","101","100.5","42.75","17"])
        payload = {"error":[],"result":{"XXBTZUSD":raw,"last":123456}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,*_):return json.dumps(payload).encode()
        with patch.object(observer,"urlopen",return_value=Response()):
            snap = observer.fetch_kraken_ohlc("BTCUSD",now)
        self.assertEqual(len(snap["candles"]),131)
        self.assertEqual(snap["candles"][-1][0],int((hour-timedelta(hours=1)).timestamp()))
        self.assertEqual(snap["candles"][-1][5],42.75)
        self.assertEqual(snap["candles"][-1][4],101.)

    def test_outside_decision_window_is_noop(self):
        now = datetime.now(timezone.utc).replace(minute=3,second=0,microsecond=0)
        self.assertIn("outside",observer.observe_symbol(
            "ETHUSD",now,lambda s,t:None,lambda s:None))


if __name__ == "__main__":
    unittest.main()
