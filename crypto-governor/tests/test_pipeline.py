import sys
from pathlib import Path
import unittest
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from update_market import parse_candles,snapshot
from backtest import Bar,run

class MarketIngestTest(unittest.TestCase):
    def candles(self,n=130):
        return [[1700000000+i*3600,'100','103','97','101','100','2'] for i in range(n)]
    def test_drops_unclosed_future_hour(self):
        rows=self.candles()
        result=parse_candles(rows,now=rows[-2][0]+3600+60)
        self.assertEqual(len(result),129)
    def test_rejects_gap(self):
        rows=self.candles();rows[95][0]+=3600
        with self.assertRaises(ValueError):parse_candles(rows,now=rows[-1][0]+3601)
    def test_rejects_duplicate(self):
        rows=self.candles();rows[20][0]=rows[19][0]
        with self.assertRaises(ValueError):parse_candles(rows,now=rows[-1][0]+3601)
    def test_rejects_broken_ohlc(self):
        rows=self.candles();rows[20][2]='-1'
        with self.assertRaises(ValueError):parse_candles(rows,now=rows[-1][0]+3601)
    def test_original_engine_repeatable(self):
        dt=datetime.fromtimestamp(1700000000,timezone.utc)
        rows=[Bar(datetime.fromtimestamp(1700000000+i*3600,timezone.utc),100+i*.2,102+i*.2,99+i*.2,101+i*.2,1) for i in range(130)]
        a,b=run(rows,'full');a2,b2=run(rows,'full')
        self.assertEqual((a,b),(a2,b2))
        self.assertEqual(a['orders_executed'],len([x for x in b if x['dollar_turnover']>0]))
    def test_all_variants_present(self):
        rows=[Bar(datetime.fromtimestamp(1700000000+i*3600,timezone.utc),100+i*.2,102+i*.2,99+i*.2,101+i*.2,1) for i in range(110)]
        d=snapshot(rows,'DEMO','synthetic_demo')
        self.assertEqual(len(d['variants']),5)
        self.assertEqual(len(d['variants']['full']['trace']),60)
if __name__=='__main__':unittest.main()