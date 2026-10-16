# TACM Supervisor Lab v0.2 (proposal, isolated / paper only)

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

Eight local unit tests pass for the strategy signals, replay determinism, future-bar isolation, paper fee accounting, independent risk-gate behavior, snapshot loading and governor adapter using a test double. **The real existing governor has not yet been integration-tested in this isolated copy; that requires running these new tests and a replay within the actual GitHub repository.**

## What this does *not* prove

- Historical replays are **not** live or forward paper-account performance. This lab does not create a persistent paper account or schedule a second system.
- Three or more agents are *not* automatically better than two. More signals mean more degrees of freedom and higher overfitting risk.
- Equal maximum exposure is not **equal realized exposure**. Report both and use later paired, risk-matched evaluations to decide whether gains came from selection, timing, or mostly holding cash.
- The current 2026 v0.1 governor's shadow returns are approximate; they need an independently validated, correctly timestamped shadow portfolio before publication.
- A frozen out-of-sample and later forward-only test are required. New experiments must be versioned before inspecting the results. Do not optimize against the final holdout.
- This lab does **not** include Muse's separate `tacm_bot.py` source, which must be audited before an exact comparison.

## Decision criteria

**CONTINUE** only if full TACM beats (i) plain, (ii) simple volatility guard, (iii) no-Tamas, and (iv) risk-matched passive/cash references on *incremental, after-cost risk-adjusted metrics* in held-out and forward-only periods. Otherwise prefer the simpler effective controller.

## Intended integration order

This is a **sidecar experiment**, not a replacement for `backtest.py`, `update_market.py`, or GitHub Pages. After code review: add a single-run replay CI check, then a separate append-only forward paper ledger. Do not introduce exchange API keys or a real order endpoint in this project.
