"""
Fetch closing price and daily % change for each publicly-traded company.

The brief asks for the previous day's closing price and that day's % change, with
a link to Yahoo Finance. The job runs before the US market opens, so the latest
quote is yesterday's close; we report that close plus its move vs the prior close.

Sources, tried in order (each is free, no API key):
  1. CNBC quote API   - one batched call for every ticker; covers NYSE/Nasdaq AND
                        the OTC-traded ADRs (Bayer, Roche). This is the workhorse.
  2. Nasdaq quote API - per-ticker fallback for exchange-listed names.
  3. Yahoo Finance / Stooq - last-resort fallbacks.

Yahoo and Stooq rate-limit/anti-bot datacenter IPs (incl. GitHub Actions), which
is why they're no longer primary. If every source fails for a ticker, that row
shows "—" and the rest of the board still renders.
"""

import time

import requests

from companies import COMPANIES, link_for

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"}


def _num(value):
    """Parse a price-ish string ('$1,211.84', '+5.09%', '13.74') to float or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = (str(value).strip()
               .replace(",", "").replace("$", "").replace("%", "").replace("+", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _last_two(values):
    """Last two non-null numbers from a list, oldest-first: (prev, last)."""
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(nums) >= 2:
        return nums[-2], nums[-1]
    return None


# ---------------------------------------------------------------------------
# 1. CNBC — primary, batched, no key. Covers exchange-listed and OTC ADRs.
# ---------------------------------------------------------------------------

def get_via_cnbc(tickers):
    """Return {TICKER: (prev_close, last_close, currency, 'CNBC')} for all the
    tickers CNBC can price, in a single request."""
    out = {}
    if not tickers:
        return out
    url = (
        "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
        "?symbols={}&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=0&output=json"
    ).format("|".join(tickers))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return out
        quotes = (((resp.json() or {}).get("FormattedQuoteResult") or {})
                  .get("FormattedQuote")) or []
        if isinstance(quotes, dict):  # single-symbol responses aren't wrapped in a list
            quotes = [quotes]
        for q in quotes:
            sym = (q.get("symbol") or "").upper()
            last = _num(q.get("last"))
            prev = _num(q.get("previous_day_closing"))
            currency = q.get("currencyCode") or "USD"
            if sym and last is not None and prev is not None:
                out[sym] = (prev, last, currency, "CNBC")
    except Exception:  # noqa: BLE001 - fall back to per-ticker sources
        pass
    return out


# ---------------------------------------------------------------------------
# 2. Nasdaq — per-ticker fallback, no key (exchange-listed only).
# ---------------------------------------------------------------------------

def get_via_nasdaq(ticker):
    url = "https://api.nasdaq.com/api/quote/{}/info?assetclass=stocks".format(ticker)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        data = (resp.json() or {}).get("data")
        if not data:
            return None
        p = data.get("primaryData") or {}
        last = _num(p.get("lastSalePrice"))
        change = _num(p.get("netChange"))
        if last is not None and change is not None:
            return last - change, last, p.get("currency") or "USD", "Nasdaq"
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# 3. Yahoo Finance / Stooq — last-resort fallbacks.
# ---------------------------------------------------------------------------

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
                    time.sleep(1.0 + attempt)
                    continue
                break
            except Exception:  # noqa: BLE001
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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _quote_row(prev_close, last_close, currency, source):
    change_pct = None
    if prev_close:
        change_pct = round((last_close - prev_close) / prev_close * 100, 2)
    return {
        "price": round(last_close, 2),
        "change_pct": change_pct,
        "prev_close": round(prev_close, 2),
        "currency": currency or "USD",
        "source": source,
    }


def _empty_quote():
    return {"price": None, "change_pct": None, "prev_close": None,
            "currency": "USD", "source": None}


def fetch_stocks():
    """Build a row for every company (traded rows priced; others labeled)."""
    rows = []
    tickers = sorted({c["ticker"] for c in COMPANIES if c.get("ticker")})
    print("Fetching stock quotes...")
    cnbc = get_via_cnbc(tickers)
    print("  CNBC batch priced {}/{} tickers.".format(len(cnbc), len(tickers)))

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
        ticker = c.get("ticker")
        if ticker:
            data = cnbc.get(ticker.upper())
            if not data:  # per-ticker fallbacks only for what CNBC missed
                data = (get_via_nasdaq(ticker) or get_via_yahoo(ticker)
                        or get_via_stooq(ticker))
                time.sleep(0.3)
            row.update(_quote_row(*data) if data else _empty_quote())
            shown = "n/a" if row["price"] is None else "${} ({}%)".format(
                row["price"], row["change_pct"])
            print("  {:<28} {:<7} {}".format(c["name"], ticker, shown))
        else:
            row.update(_empty_quote())
            print("  {:<28} {:<7} {}".format(c["name"], "-", c.get("note", "")))
        rows.append(row)

    priced = sum(1 for r in rows if r["price"] is not None)
    print("Priced {}/{} tickers.".format(priced, sum(1 for r in rows if r["ticker"])))
    return rows


def _selftest():
    """Validate parsing logic on sample payloads (no network)."""
    assert _num("$1,211.84") == 1211.84, _num("$1,211.84")
    assert _num("+5.09%") == 5.09
    assert _num("n/a") is None
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
    assert round((11.2 - 10.5) / 10.5 * 100, 2) == 6.67
    print("fetch_stocks self-test passed.")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        for r in fetch_stocks():
            print(r)
