# TACM Supervisor Research Lab v0.3 (historical + forward paper, never real orders)

This lab separates three responsibilities:

1. **Signal agents:** two completely transparent and deterministic agents, `momentum_12_48` and `mean_revert_z24`, emit only `FLAT` / `LONG` proposals plus confidence and explanation. They never place orders, set risk, or alter TACM.
2. **Supervisors:** `plain` (highest-confidence selection), `simple_vol_guard` (plain with a 2× volatility pause), the existing unmodified `tacm_full`, and `tacm_no_tamas` (the previously informative ablation). These all receive the **same** proposals at the **same** decision times.
3. **Paper venue plus independent hard risk gate:** idealized next-open fills, explicit taker fee and slippage, 10% maximum requested exposure, daily 2% loss stop, permanent 5% drawdown halt, no more than three new entries per day. No live exchange SDK, credentials or order methods.

Two reference portfolios are included: always-cash and 10%-initial-capital passive buy-and-hold. The passive reference is deliberately **not** rebalanced or constrained by the active strategy's stop rules. Every policy gets independent virtual cash, holdings, peak and log.

## Run

From the repo root, for a **historical research replay** using an existing contiguous UTC OHLCV CSV or our repository's existing Kraken market snapshot:

```sh
python crypto-governor/supervisor_lab.py docs/crypto-governor/data/BTCUSD.json --out supervisor_lab_results --fee 0.008 --slippage 0.0005
python -m unittest discover -s crypto-governor/tests -v
```

CSV input columns are `timestamp,open,high,low,close,volume`. Alternatively, pass an already downloaded `docs/crypto-governor/data/BTCUSD.json` or `ETHUSD.json`; the lab rejects synthetic-demo snapshots. All candles **must be completed**. `--fee 0.008` means an assumed 0.80% taker fee **per side**; it must be checked against the actual exchange/account before any financial interpretation. Slippage is separately assumed at 0.05% per side, with no claim to model spread, market impact or fill delays.

Outputs: `summary.json` and one trace CSV per variant with timestamps, identical raw agent signals, supervised request, independent allowed target, order type, estimated turnover, balance, inventory, portfolio equity and average exposure. No trade is sent to Kraken or elsewhere.

## Test status

GitHub CI runs existing project tests and lab tests against the actual repository governor, plus BTC and ETH historical replays. A passing software test does not demonstrate profitable strategy performance.

## What this does *not* prove

- Historical replays are **not** live or forward paper-account performance. Historical replays do not create persistent accounts. The separate forward-paper component below maintains simulated state when activated.
- Three or more agents are *not* automatically better than two. More signals mean more degrees of freedom and higher overfitting risk.
- Equal maximum exposure is not **equal realized exposure**. Report both and use later paired, risk-matched evaluations to decide whether gains came from selection, timing, or mostly holding cash.
- The current 2026 v0.1 governor's shadow returns are approximate; they need an independently validated, correctly timestamped shadow portfolio before publication.
- A frozen out-of-sample and later forward-only test are required. New experiments must be versioned before inspecting the results. Do not optimize against the final holdout.
- This lab does **not** include Muse's separate `tacm_bot.py` source, which must be audited before an exact comparison.

## Decision criteria

**CONTINUE** only if full TACM beats (i) plain, (ii) simple volatility guard, (iii) no-Tamas, and (iv) risk-matched passive/cash references on *incremental, after-cost risk-adjusted metrics* in held-out and forward-only periods. Otherwise prefer the simpler effective controller.

## Intended integration order

This is a **sidecar experiment**, not a replacement for `backtest.py`, `update_market.py`, or GitHub Pages. The append-only forward-paper component has been implemented separately. It is subject to PR review and CI before activation. Do not introduce exchange API keys or a real order endpoint in this project.


## Forward-paper study v0.3

Historical replays and the forward study are DISTINCT evidence tracks. The new Python program crypto-governor/forward_paper.py reads the latest COMPLETED public Kraken 1-hour OHLC observations and a freshly fetched PUBLIC Kraken bid/ask quote. It creates simulated buys and sells at that quote time, never actual orders. No private exchange endpoints, account credentials, leverage, order submissions, or wallet functions exist.

Eight independently funded virtual $10,000 portfolios: plain highest-confidence agent at 10% maximum allocation, plain at 3%, basic volatility guard, TACM full, TACM no-Tamas, cash, and 10%-initial and 3%-initial buy-and-hold. The same momentum and mean-reversion deterministic agents supply signals to every supervisor. The five active strategies share a hard 10% allocation ceiling (the low-exposure plain control voluntarily caps itself at 3%), 5% peak drawdown halt, 2% daily loss stop, and 3-new-entry daily cap. Realized exposures can differ and require normalization in any fair comparison.

Assumed per-side spot taker fee is 0.80% (entry tier) plus modeled 0.05% slippage. Simulated buying uses public ask; simulated selling uses public bid, incorporating the spread. Execution latency, order-book depth, market impact, unavailable liquidity, taxes, and exchange-specific order restrictions are not modeled. Verify account-specific fees independently.

### Evidence integrity

- The very FIRST event uses the first observed quote and current completed candle. Historical replays are never mislabeled as forward evidence.
- State checkpoints preserve cash, units, fee totals, governance memory, risk-gate state, and shadow estimates. Each append-only journal event includes the previous event hash and its own digest; the complete chain is verified before appending.
- Identical completed-candle input is a no-op and cannot create duplicate simulated trades.
- A stale/invalid quote, stale/incomplete candle, symbol mismatch, conflicting capital/fee settings, out-of-order data or modified journal fails closed.
- If GitHub Actions misses one or more hourly observations, the missing hours are explicitly counted. Existing active paper holdings are liquidated only at the NEXT observed public quote. There are no imaginary executions or claimed intrahour stops.
- Safety limits operate at observation time and cannot protect against between-observation market moves or gaps. GitHub Actions is not a continuously running execution service.
- All numbers are simulated estimates. The original governor's synthetic shadow return mechanism is still approximate.

### How scheduled observation works

The separate workflow in .github/workflows/tacm-forward-paper.yml will become active ONLY after the reviewed code reaches the default branch. It is triggered by successful completion of the existing market snapshot updater. It checks the full test suite, obtains fresh public quotes, observes BTCUSD and ETHUSD separately, and commits any new journal events and state snapshots under docs/crypto-governor/forward/. If one symbol fails, the other successful event is still committed and the job reports a failure.

The ledger is NOT initialized from historical data. It will only exist after the first successful scheduled forward observation after deployment. There is no live exchange connection or real trading account.

Developer test command from repository root:

    python -m unittest discover -s crypto-governor/tests -v

Manual quote-based forward observation requires a genuinely fresh repo snapshot (do not use synthetic fixtures as real results):

    python crypto-governor/forward_paper.py --symbol BTCUSD --snapshot docs/crypto-governor/data/BTCUSD.json --state docs/crypto-governor/forward/BTCUSD.state.json --journal docs/crypto-governor/forward/BTCUSD.ledger.jsonl --fee 0.008 --slippage 0.0005

### Predeclared research objective

Collect at least 60-90 days of non-backfilled observations across varied conditions. Report capital return, exposure-normalized performance, max drawdown, turnover, fees, observed spread/slippage, missed-hour incidence, and supervisor ablations. Compare against plain agents at 10% and 3%, simple volatility rules, no-Tamas, cash, and 10% and 3% passive references. These are closer risk controls, but not perfectly exposure-matched to dynamically changing TACM exposure. Do NOT declare TACM value on a single favorable return series.
