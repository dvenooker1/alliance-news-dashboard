"""
Build the dashboard data.

Runs the whole pipeline and writes the JSON the website reads:
  docs/data.json                  -> today's roundup (what the site loads by default)
  docs/archive/<YYYY-MM-DD>.json  -> a dated copy, so past days stay browsable
  docs/archive/index.json         -> list of available dates for the date picker

The static front-end (docs/index.html + app.js) fetches these files; there is no
server. GitHub Actions runs this script daily and publishes the docs/ folder.
"""

import json
import os
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback if tz database is unavailable
    EASTERN = timezone.utc

import classify
from fetch_news import fetch_news
from fetch_stocks import fetch_stocks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
ARCHIVE = os.path.join(DOCS, "archive")

PRIORITY_ORDER = ["high", "medium", "low"]


def _news_item_json(item):
    pub = item.get("published")
    return {
        "title": item["title"],
        "link": item["link"],
        "source": item.get("source", ""),
        "published": pub.isoformat() if pub else None,
        "companies": item.get("companies", []),
        "is_oncology": bool(item.get("is_oncology")),
        "is_press_release": bool(item.get("is_press_release")),
        "summary": item.get("summary_ai"),
    }


def _sort_within_priority(items):
    """High: oncology then press releases then recent. Others: most recent first."""
    def ts(it):
        p = it.get("published")
        return p.timestamp() if p else 0
    items.sort(key=lambda it: (
        it.get("is_oncology", False),
        it.get("is_press_release", False),
        ts(it),
    ), reverse=True)
    return items


def build():
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(EASTERN)
    date_str = now_et.strftime("%Y-%m-%d")

    # 1. News -> classify
    news = fetch_news()
    print("Classifying...")
    news = classify.classify(news)
    engine = "claude" if any(it.get("engine") == "claude" for it in news) else "keyword"

    buckets = {p: [] for p in PRIORITY_ORDER}
    for it in news:
        buckets.get(it.get("priority", "low"), buckets["low"]).append(it)
    for p in PRIORITY_ORDER:
        _sort_within_priority(buckets[p])

    news_json = {p: [_news_item_json(it) for it in buckets[p]] for p in PRIORITY_ORDER}
    counts = {p: len(news_json[p]) for p in PRIORITY_ORDER}
    counts["total"] = sum(counts[p] for p in PRIORITY_ORDER)

    # 2. Stocks
    stocks = fetch_stocks()

    data = {
        "generated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at_et": now_et.strftime("%Y-%m-%d %I:%M %p %Z"),
        "date": date_str,
        "classifier": engine,
        "model": classify.DEFAULT_MODEL if engine == "claude" else None,
        "counts": counts,
        "news": news_json,
        "stocks": stocks,
    }

    # 3. Write outputs
    os.makedirs(ARCHIVE, exist_ok=True)
    _write(os.path.join(DOCS, "data.json"), data)
    _write(os.path.join(ARCHIVE, "{}.json".format(date_str)), data)
    _update_index(date_str, counts)

    print("\nDone. {} news items ({} high / {} medium / {} low), engine={}.".format(
        counts["total"], counts["high"], counts["medium"], counts["low"], engine))
    return data


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    print("  wrote {}".format(os.path.relpath(path, ROOT)))


def _update_index(date_str, counts):
    path = os.path.join(ARCHIVE, "index.json")
    history = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                history = json.load(fh).get("dates", [])
        except Exception:  # noqa: BLE001
            history = []
    history = [h for h in history if h.get("date") != date_str]
    history.append({"date": date_str, "counts": counts})
    history.sort(key=lambda h: h["date"], reverse=True)
    _write(path, {"dates": history})


if __name__ == "__main__":
    build()
