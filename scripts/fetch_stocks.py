"""
Fetch closing price and daily % change for each publicly-traded company.

The brief asks for the previous day's closing price and that day's % change, with
a link to Yahoo Finance. We read the most recent two completed daily closes and
report the latest close plus its change vs the prior close — so running before the
market opens shows yesterday's close, exactly as intended.

Sources, tried in order per ticker (markets sometimes rate-limit one of them):
  1. Yahoo Finance chart API  (query1, then query2 host)
  2. Stooq daily CSV          (no key, independent of Yahoo)

If every source fails for a ticker, that row shows "—" and the rest of the board
still renders — one flaky symbol never breaks the page.
"""

import time

import requests

from companies import COMPANIES, link_for

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"}


def _last_two(values):
    """Last two non-null numbers from a list, oldest-first: (prev, last)."""
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(nums) >= 2:
        return nums[-2], nums[-1]
    return None


def parse_yahoo(payload):
    """Extract (prev_close, last_close, currency) from a Yahoo chart JSON dict."""
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    r0 = result[0]
    meta = r0.get("meta") or {}
    currency = meta.get("currency", "USD")
    try:
        closes = r0["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        closes = []
    pair = _last_two(closes or [])
    if pair:
        return pair[0], pair[1], currency
    # Fall back to meta fields if the close series is unusable.
    last = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if isinstance(last, (int, float)) and isinstance(prev, (int, float)):
        return prev, last, currency
    return None


def get_via_yahoo(ticker):
    for host in ("query1", "query2"):
        url = (
            "https://{}.finance.yahoo.com/v8/finance/chart/{}"
            "?range=7d&interval=1d".format(host, ticker)
        )
        for attempt in range(2):
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                if resp.status_code == 200:
                    parsed = parse_yahoo(resp.json())
                    if parsed:
                        return parsed + ("Yahoo Finance",)
                elif resp.status_code in (429, 999):
                    time.sleep(1.0 + attempt)  # backoff on rate-limit
                    continue
                break
            except Exception:  # noqa: BLE001 - try the next host/source
                time.sleep(0.5)
    return None


def parse_stooq(text):
    """Extract (prev_close, last_close, 'USD') from Stooq daily CSV text."""
    lines = [ln for ln in text.strip().splitlines() if ln]
    if not lines or not lines[0].lower().startswith("date,"):
        return None  # anti-bot page or error, not CSV
    closes = []
    for row in lines[1:]:
        cols = row.split(",")
        if len(cols) >= 5:
            try:
                closes.append(float(cols[4]))
            except ValueError:
                pass
    pair = _last_two(closes)
    if pair:
        return pair[0], pair[1], "USD"
    return None


def get_via_stooq(ticker):
    url = "https://stooq.com/q/d/l/?s={}.us&i=d".format(ticker.lower())
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            parsed = parse_stooq(resp.text)
            if parsed:
                return parsed + ("Stooq",)
    except Exception:  # noqa: BLE001
        pass
    return None


def fetch_one(ticker):
    """Return dict with price/change for a ticker, or None values on failure."""
    data = get_via_yahoo(ticker) or get_via_stooq(ticker)
    if not data:
        return {"price": None, "change_pct": None, "prev_close": None,
                "currency": "USD", "source": None}
    prev_close, last_close, currency, source = data
    change_pct = None
    if prev_close:
        change_pct = round((last_close - prev_close) / prev_close * 100, 2)
    return {
        "price": round(last_close, 2),
        "change_pct": change_pct,
        "prev_close": round(prev_close, 2),
        "currency": currency,
        "source": source,
    }


def fetch_stocks():
    """Build a row for every company (traded rows priced; others labeled)."""
    rows = []
    print("Fetching stock quotes...")
    for c in COMPANIES:
        row = {
            "key": c["key"],
            "name": c["name"],
            "ticker": c.get("ticker"),
            "ticker_note": c.get("ticker_note"),
            "status": c["status"],
            "note": c.get("note"),
            "link": link_for(c),
        }
        if c.get("ticker"):
            quote = fetch_one(c["ticker"])
            row.update(quote)
            arrow = "" if quote["change_pct"] is None else \
                ("+" if quote["change_pct"] >= 0 else "")
            shown = "n/a" if quote["price"] is None else "${} ({}{}%)".format(
                quote["price"], arrow, quote["change_pct"])
            print("  {:<28} {:<7} {}".format(c["name"], c["ticker"], shown))
            time.sleep(0.3)  # be polite between requests
        else:
            row.update({"price": None, "change_pct": None, "prev_close": None,
                        "currency": "USD", "source": None})
            print("  {:<28} {:<7} {}".format(c["name"], "-", c.get("note", "")))
        rows.append(row)
    priced = sum(1 for r in rows if r["price"] is not None)
    print("Priced {}/{} tickers.".format(priced, sum(1 for r in rows if r["ticker"])))
    return rows


def _selftest():
    """Validate parsing logic on sample payloads (no network)."""
    sample_yahoo = {
        "chart": {"result": [{
            "meta": {"currency": "USD", "regularMarketPrice": 102.0,
                     "chartPreviousClose": 99.0},
            "indicators": {"quote": [{"close": [97.5, 98.0, None, 100.0, 101.0]}]},
        }], "error": None}
    }
    assert parse_yahoo(sample_yahoo) == (100.0, 101.0, "USD"), parse_yahoo(sample_yahoo)
    sample_csv = ("Date,Open,High,Low,Close,Volume\n"
                  "2026-06-19,10,11,9,10.5,1000\n"
                  "2026-06-20,10.5,12,10,11.2,1200\n")
    assert parse_stooq(sample_csv) == (10.5, 11.2, "USD"), parse_stooq(sample_csv)
    assert parse_stooq("<html>blocked</html>") is None
    # change calc
    prev, last = 10.5, 11.2
    assert round((last - prev) / prev * 100, 2) == 6.67
    print("fetch_stocks self-test passed.")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        for r in fetch_stocks():
            print(r)
