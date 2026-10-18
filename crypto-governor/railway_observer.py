"""Persistent read-only-public-market TACM observer for an always-on host.

- Uses real Kraken public 1-hour OHLC and public bid/ask ticker data.
- Only processes the *most recently completed* 1-hour candle, one event each.
- Reuses the exact frozen paper agents, governor, gates and fill-cost model.
- Never sends an order; no private Kraken credentials/API calls exist.
- Starts a NEW v1 ledger on durable /data storage. Legacy GitHub v0.3
  diagnostic ledgers are not imported, overwritten, or relabeled.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from forward_paper import advance, fetch_quote, save_step, utc

LOG = logging.getLogger("tacm.observer")
SYMBOLS = {"BTCUSD": "XBTUSD", "ETHUSD": "ETHUSD"}
ROOT = Path(os.environ.get("TACM_DATA_DIR", "/data/tacm-v1"))
POLL_SECONDS = 30
PRICE_TIMEOUT = 15
MIN_CANDLES = 120
FEE = 0.008
SLIPPAGE = 0.0005
CAPITAL = 10000.0
ALLOWED_ORIGIN = "https://lurbur.github.io"

# Lock prevents concurrent read/write of state and journals inside this process.
LOCK = threading.RLock()
LATEST = {"last_attempt_at": None, "last_success_at": {},
          "last_error": {}, "next_observation": {}}
SOURCE = "Kraken public OHLC + Ticker, forward PAPER only"


def fetch_kraken_ohlc(symbol: str, now: datetime) -> dict:
    """Return only COMPELTED contiguous 1h OHLCV bars (no current open bar)."""
    pair = SYMBOLS[symbol]
    request = Request(
        "https://api.kraken.com/0/public/OHLC?pair=" + pair + "&interval=60",
        headers={"User-Agent": "TACM-Research-Paper-Observer/1.0"}
    )
    with urlopen(request, timeout=PRICE_TIMEOUT) as response:
        body = json.load(response)
    if body.get("error") or not body.get("result"):
        raise ValueError("Public Kraken OHLC endpoint rejected the request")
    payload = body["result"]
    keys = [key for key in payload if key != "last"]
    if len(keys) != 1:
        raise ValueError("Unexpected public Kraken OHLC response")
    rows = payload[keys[0]]
    if len(rows) < MIN_CANDLES + 1:
        raise ValueError("Kraken returned insufficient hourly candles")
    # Kraken includes the current, *uncommitted* hourly bar as the final row.
    completed = rows[:-1]
    expected_open = int(now.timestamp() // 3600) * 3600 - 3600
    if int(completed[-1][0]) != expected_open:
        raise ValueError("Kraken last completed 1h candle not available yet")
    bars = [
        [int(row[0]), float(row[1]), float(row[2]), float(row[3]),
         float(row[4]), float(row[6])]
        for row in completed
    ]
    if len(bars) < MIN_CANDLES:
        raise ValueError("Not enough completed history")
    for left, right in zip(bars, bars[1:]):
        if right[0] - left[0] != 3600:
            raise ValueError("Gap in Kraken completed hourly OHLC; refuse interpolation")
    return {"symbol": symbol, "mode": "market",
            "paper_only": True,
            "generated_at": now.isoformat(),
            "last_completed_candle": datetime.fromtimestamp(
                expected_open, timezone.utc).isoformat(),
            "source": SOURCE,
            "candles": bars}


def files_for(symbol: str):
    return (ROOT / (symbol + ".state.json"),
            ROOT / (symbol + ".ledger.jsonl"),
            ROOT / (symbol + ".market.json"))


def _observed_candle(state):
    if not state:
        return None
    return utc(state["last_candle_open"])


def observe_symbol(symbol: str, now=None,
                   snapshot_fetcher=fetch_kraken_ohlc,
                   quote_fetcher=fetch_quote):
    """Perform at most one forward-paper decision per completed candle."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("UTC-aware now required")
    now = now.astimezone(timezone.utc)
    if not (5 <= now.minute <= 48):
        return "outside post-close observation window"
    expected = datetime.fromtimestamp(
        int(now.timestamp() // 3600) * 3600 - 3600, timezone.utc)
    state_path, journal_path, market_path = files_for(symbol)
    with LOCK:
        previous = json.loads(state_path.read_text()) if state_path.exists() else None
        observed = _observed_candle(previous)
        if observed is not None and observed >= expected:
            return "already observed completed 1-hour candle"
        snapshot = snapshot_fetcher(symbol, now)
        quote = quote_fetcher(symbol)
        actual = datetime.now(timezone.utc)
        updated, event = advance(snapshot, quote, previous, now=actual,
                                 symbol=symbol, fee=FEE,
                                 slippage=SLIPPAGE, capital=CAPITAL)
        if event is None:
            return "duplicate candle, no order"
        # Ledger/state append is validated, including the full hash chain.
        save_step(state_path, journal_path, updated, event)
        # Store market data for the same exact observation. The report API
        # may return the last completed market data, never invented bars.
        from forward_paper import atomic_text
        atomic_text(market_path, json.dumps(snapshot, allow_nan=False) + "\n")
        LATEST["last_success_at"][symbol] = event["timestamp"]
        LATEST["last_error"].pop(symbol, None)
        LOG.info("PAPER %s event=%s skipped=%s hash=%s",
                 symbol, event["number"], event["skipped_unobserved_hours"],
                 event["hash"][:16])
        return "appended paper event " + str(event["number"])


def run_once(now=None, snapshot_fetcher=fetch_kraken_ohlc,
             quote_fetcher=fetch_quote):
    now = now or datetime.now(timezone.utc)
    LATEST["last_attempt_at"] = now.isoformat()
    results = {}
    for symbol in SYMBOLS:
        try:
            results[symbol] = observe_symbol(
                symbol, now=now, snapshot_fetcher=snapshot_fetcher,
                quote_fetcher=quote_fetcher)
        except Exception as exc:
            message = type(exc).__name__ + ": " + str(exc)
            LATEST["last_error"][symbol] = message[:200]
            LOG.exception("PAPER %s observation rejected, no synthetic fill", symbol)
            results[symbol] = "REJECTED: " + message
    return results


def scheduler_loop():
    # Startup never converts old pilot records into new forward evidence.
    # Poll every 30s; only the first valid quote after :05 each hour wins.
    while True:
        try:
            now = datetime.now(timezone.utc)
            if 5 <= now.minute <= 48:
                run_once(now)
        except Exception:
            LOG.exception("PAPER worker fault; continue checking safely")
        time.sleep(POLL_SECONDS)


def health_payload():
    with LOCK:
        now = datetime.now(timezone.utc)
        symbols = {}
        for symbol in SYMBOLS:
            state_path, ledger_path, market_path = files_for(symbol)
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text())
                    ledger_lines = [
                        x for x in ledger_path.read_text().splitlines() if x
                    ] if ledger_path.exists() else []
                    if state["events"] != len(ledger_lines):
                        raise ValueError("Journal/checkpoint mismatch")
                    last = json.loads(ledger_lines[-1])
                    if last["hash"] != state["last_hash"]:
                        raise ValueError("Latest event hash mismatch")
                    missing = sum(
                        json.loads(x).get("skipped_unobserved_hours", 0)
                        for x in ledger_lines)
                    quote_age = (now - utc(state["last_quote_at"])).total_seconds()
                    symbols[symbol] = {
                        "observations": state["events"],
                        "missed_hours": missing,
                        "coverage": state["events"] / (state["events"] + missing),
                        "last_quote_at": state["last_quote_at"],
                        "last_candle_open": state["last_candle_open"],
                        "quote_age_seconds": round(quote_age),
                        "has_snapshot": market_path.exists(),
                        "status": "observing" if quote_age < 7200 else "stale",
                        "last_error": LATEST["last_error"].get(symbol)
                    }
                except Exception as exc:
                    symbols[symbol] = {
                        "status": "ledger_error",
                        "error": str(exc)[:180]}
            else:
                symbols[symbol] = {
                    "status": "initializing",
                    "last_error": LATEST["last_error"].get(symbol)}
        return {"service": "TACM independent paper observer v1",
                "mode": "FORWARD_PAPER_ONLY",
                "engine": "railway always-on observer",
                "source": SOURCE,
                "now": now.isoformat(),
                "last_attempt_at": LATEST["last_attempt_at"],
                "symbols": symbols}


class PublicHandler(BaseHTTPRequestHandler):
    server_version = "TACM-Paper/1.0"

    def _send(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            payload = json.dumps(health_payload(), allow_nan=False).encode()
            self._send(200, payload, "application/json; charset=utf-8")
            return
        pieces = path.strip("/").split("/")
        if len(pieces) != 3 or pieces[0] != "v1":
            self._send(404, b"not found", "text/plain")
            return
        _, kind, filename = pieces
        for symbol in SYMBOLS:
            state, ledger, market = files_for(symbol)
            mapping = {
                ("forward", symbol + ".state.json"): (state, "application/json"),
                ("forward", symbol + ".ledger.jsonl"): (ledger, "application/x-ndjson"),
                ("data", symbol + ".json"): (market, "application/json"),
            }
            hit = mapping.get((kind, filename))
            if hit is not None:
                location, mime = hit
                with LOCK:
                    if not location.is_file():
                        self._send(404, b"no forward observations yet", "text/plain")
                        return
                    data = location.read_bytes()
                if len(data) > 10_000_000:
                    self._send(503, b"export too large", "text/plain")
                    return
                self._send(200, data, mime + "; charset=utf-8")
                return
        self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):
        LOG.info("http %s - %s", self.address_string(), fmt % args)


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ROOT.mkdir(parents=True, exist_ok=True)
    task = threading.Thread(target=scheduler_loop, name="hourly-observer",
                            daemon=True)
    task.start()
    port = int(os.environ.get("PORT", "8080"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), PublicHandler)
    LOG.info("Paper-only observer HTTP listening on %s, ledger root %s", port, ROOT)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
