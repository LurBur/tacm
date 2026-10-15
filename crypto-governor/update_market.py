"""Generate public-market snapshots for the static TACM research dashboard.

Read-only, no exchange credentials. Python 3.10+, stdlib only.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from math import isfinite

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest import Bar, run, read_bars

PAIRS = {"BTCUSD": "XBTUSD", "ETHUSD": "ETHUSD"}
VARIANTS = ["baseline", "full", "no_sattva", "no_rajas", "no_tamas"]
INTERVAL = 3600

def parse_candles(raw, now=None):
    """Kraken timestamp is OPEN in UTC seconds; omit unfinished bars."""
    now = now or datetime.now(timezone.utc).timestamp()
    if not isinstance(raw, list):
        raise ValueError("OHLC result not an array")
    bars = []
    for row in raw:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError("Malformed Kraken OHLC row")
        t = int(row[0]); o,h,l,c,v = map(float, (row[1],row[2],row[3],row[4],row[6]))
        if t + INTERVAL > now:  # this interval has not finished
            continue
        if not all(isfinite(x) for x in [o,h,l,c,v]) or min(o,h,l,c) <= 0 or v < 0:
            raise ValueError("Invalid OHLCV numeric value")
        if h < max(o,c,l) or l > min(o,c,h):
            raise ValueError("Invalid high/low ordering")
        if bars and (t - int(bars[-1].timestamp.timestamp()) != INTERVAL):
            raise ValueError("Duplicate or missing hourly candle (strictly contiguous required)")
        bars.append(Bar(datetime.fromtimestamp(t, timezone.utc), o,h,l,c,v))
    if len(bars) < 100:
        raise ValueError(f"Insufficient completed hourly bars: {len(bars)}")
    if (now - bars[-1].timestamp.timestamp()) > 3 * INTERVAL:
        raise ValueError("Stale market bars: newest opening timestamp >3h old")
    return bars[-500:]


def fetch_pair(pair):
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=60"
    req = Request(url, headers={"User-Agent": "TACM-Research-PaperDashboard/0.2"})
    with urlopen(req, timeout=18) as f:
        if f.status != 200:
            raise ValueError(f"Kraken HTTP {f.status}")
        data = json.loads(f.read())
    if data.get('error'):
        raise ValueError("Kraken API error: " + ", ".join(map(str, data['error'])))
    keys = [k for k in data.get('result', {}) if k != 'last']
    if len(keys) != 1:
        raise ValueError("Unexpected Kraken response keys")
    return parse_candles(data['result'][keys[0]])


def snapshot(bars, symbol, mode):
    cases = {}
    for variant in VARIANTS:
        summary, audit = run(bars, variant, fee=.001, slippage=.0005)
        cases[variant] = {
            'summary': summary,
            'trace': [[row[key] for key in (
                'timestamp','price_open','price_close','agent','phase','diagnostic_81',
                'sattva','rajas','tamas','advantage_decay','intervention',
                'target_weight','allowed_weight','risk_gate','dollar_turnover',
                'units','equity'
            )] for row in audit],
        }
    # Compact column-indexed trace so hosted snapshot is practical to fetch.
    return {
        'symbol':symbol, 'mode':mode, 'generated_at':datetime.now(timezone.utc).isoformat(),
        'last_completed_candle':bars[-1].timestamp.isoformat(),
        'source': 'Kraken public OHLC (completed 1h)' if mode=='market' else 'SYNTHETIC RESEARCH DATA - NOT MARKET',
        'fee_bps_per_side':10, 'slippage_bps_per_side':5,
        'trace_columns':['timestamp','price_open','price_close','agent','phase','diagnostic_81','sattva','rajas','tamas','advantage_decay','intervention','target_weight','allowed_weight','risk_gate','dollar_turnover','units','equity'],
        'candles':[[int(b.timestamp.timestamp()),round(b.open,6),round(b.high,6),round(b.low,6),round(b.close,6),round(b.volume,7)] for b in bars],
        'variants':cases,
        'paper_only':True,
        'risk_limits':{'max_exposure':.1,'drawdown_halt':.05,'daily_loss_pause':.02,'new_entries_per_utc_day':3},
    }


def make_demo(input_csv, output):
    bars = read_bars(input_csv)[-260:]
    payload = snapshot(bars, 'DEMO', 'synthetic_demo')
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(payload, separators=(',', ':')), encoding='utf-8')
    print('Demo snapshot:',len(bars),'bars')


def make_market(out_dir):
    out = Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    results=[];failures={}
    for name,pair in PAIRS.items():
        try:
            bars = fetch_pair(pair)
            payload = snapshot(bars, name, 'market')
            (out/f'{name}.json').write_text(json.dumps(payload,separators=(',',':')),encoding='utf-8')
            results.append(name)
            print('wrote',name,len(bars),'bars')
        except Exception as exc:
            failures[name] = str(exc)
            print(f'FAIL {name}: {exc}',file=sys.stderr)
    if not results:
        # Do not overwrite existing valid market data with synthetic fallback or fake status.
        raise RuntimeError('No market feeds refreshed; previous file(s), if any, remain unchanged')
    manifest = {'updated_at':datetime.now(timezone.utc).isoformat(),'assets':results,'errors':failures,'mode':'market','refresh_interval_seconds':3600}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default='docs/crypto-governor/data')
    ap.add_argument('--demo-from')
    args=ap.parse_args()
    if args.demo_from:make_demo(args.demo_from,str(Path(args.out)/'demo.json'))
    else:make_market(args.out)