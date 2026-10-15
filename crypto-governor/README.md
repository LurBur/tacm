# TACM Crypto Control Center (research)

This is a **working, no-Lovable, no-paid-backend dashboard** paired with the original Python TACM crypto supervisory research prototype. It is intentionally incapable of live trading.

## Key distinction

- **Engine:** `governor.py` and `backtest.py` are the original v0.1 Python research source. The Python job runs historical simulations of a baseline agent and four supervisory variants, plus explicit paper fill/risk checks.
- **Viewer:** `docs/crypto-governor/index.html` is a zero-dependency HTML/JS UI. It reads the generated results, replays events, charts simulations, shows Sattva/Rajas/Tamas, agents, independent risk gate, ablations, and exports audit CSV. It **does not** run an autonomous trading engine in the browser.
- **Market updates:** `.github/workflows/crypto-governor-hourly.yml` fetches Kraken public completed 1-hour OHLC and recomputes all variants roughly hourly on GitHub-hosted infrastructure. The dashboard checks for a new JSON snapshot every 60 seconds while open. GitHub scheduled actions can run late or pause. The dashboard shows stale data clearly.
- **Safety:** no trading secrets or exchange order endpoints; all account values are simulated. Controls do not change live accounts or order behavior. Pausing only stops visual replay.
- **Not yet validated:** no out-of-sample crypto profitability demonstrated. The 81-state diagnostic is descriptive metadata, not empirical market prediction. Shadow agent returns are approximations.

## Zero-cost quick start / open offline

Download `docs/crypto-governor/index.html`, open it in Chrome or another browser. It includes an embedded **SYNTHETIC DEMO** so all six interactive tabs and replay controls function even offline. Market data requires a hosted snapshot from GitHub Actions. Never interpret demo numbers as real markets.

## GitHub Pages publishing

This subproject lives in a separate folder of the existing `tacm` repository. This intentionally leaves the main TACM CostRouter README and files unchanged.

1. Repository **Settings → Pages**: choose **Deploy from a branch**, **main**, and **/docs**, Save.
2. Repository **Actions**: allow the `TACM public crypto research snapshots` workflow if prompted, then choose **Run workflow** once. It refreshes public data hourly thereafter, subject to GitHub scheduling/limits.
3. Navigate to `https://lurbur.github.io/tacm/crypto-governor/` (this URL will not work until Pages is enabled and deployed). Refresh the dashboard and verify it says `REAL MARKET SNAPSHOT`, names Kraken, and includes a recent UTC last-completed hour.
4. Optional: download `index.html` any time for an interactive fully offline **synthetic** demo.

The workflow commits public market observations and derived simulator results to the repository for transparent auditing. It does not use user account data. The repository is public; do not add secrets to the data folder.

## Local offline demo and tests

Python 3.10+; no pip dependencies:

```sh
python crypto-governor/update_market.py --demo-from /path/to/synthetic_DO_NOT_TRADE.csv --out docs/crypto-governor/data
python -m unittest discover -s crypto-governor/tests -v
python -m http.server 8000 -d docs
# Then open http://localhost:8000/crypto-governor/
```

For a real update while online:

```sh
python crypto-governor/update_market.py --out docs/crypto-governor/data
```

## Model assumptions and limitations

- Only BTC/USD and ETH/USD, Kraken public hourly OHLCV, up to 500 completed contiguous bars, rejects duplicates, malformed rows, and missing hourly data.
- Simulations commence after 50 warmup bars. At the beginning of a candle, the agents see only **strictly previous** completed bars. A frictionless decision is then filled at that candle's open using simplified 10 bps fee and 5 bps slippage per side. Execution latency/spread are omitted. This is a research idealization, not a deployable live trading system.
- Risk gate: at most 10% long exposure; permanent drawdown halt 5%; daily loss 2%; max 3 new entries per UTC day. Applies to virtual executions on hourly opens, not intrabar. A gap can defeat the limits before a check.
- Momentum and mean reversion are **deterministic placeholder agents**, not LLMs or proven profitable strategies. `baseline` uses highest-confidence selection; `full` uses original v0.1 governor; ablations neutralize one quality heuristically.
- Passive references: cash $10,000; 10%-initial-capital buy-and-hold with paper entry costs, mark-to-market thereafter. Not a full risk-matched comparison.
- Audit exported from the dashboard is the completed simulated trace, not an exchange execution log. Fees in UI estimated from paper turnover, slippage included in simulated fills. Synthetic mode contains no real market information.
- Historical Kraken OHLC queries have limited history. For proper scientific validation require independent holdout data, walk-forward evaluation, risk matched baselines, and forward paper trials.

## Next scientific decision

Continue only if the full governor improves **after-cost, out-of-sample risk-adjusted** performance consistently against the unguided version and ablations. Otherwise pivot or kill the control hypothesis in this use case. Nothing here should be connected to exchange keys for real orders.