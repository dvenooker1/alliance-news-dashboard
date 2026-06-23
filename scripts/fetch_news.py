"""
Gather news for the consortium companies.

Sources:
  1. Google News RSS, one query per company. Google News aggregates the major
     outlets the brief calls out (NYT, WSJ, Barron's, Reuters, Yahoo Finance) and
     industry trades (STAT, Endpoints, Fierce) plus the PR wires that carry
     official company press releases (Business Wire, PR Newswire, GlobeNewswire).
  2. A few industry RSS feeds read in full, then matched against company names —
     a backstop so trade coverage is caught even when Google News is thin.

Every item is tagged with the companies it mentions, de-duplicated, filtered to
the recent window, and flagged as a press release when it comes from a PR wire or
the company itself. Priority (high/medium/low) is assigned later by classify.py.
"""

import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import feedparser
import requests

from companies import COMPANIES, primary_query

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# How far back to keep items (hours). The job runs ~once a day; 30h gives a little
# slack so nothing is missed around the run time without pulling in stale news.
import os
HOURS_LOOKBACK = int(os.environ.get("HOURS_LOOKBACK", "30"))
# Cap items sent downstream, to bound classification cost/time. Press releases and
# industry-trade items are kept preferentially; the cap mostly trims general items.
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "240"))
GOOGLE_PER_COMPANY = int(os.environ.get("GOOGLE_PER_COMPANY", "18"))

# Publishers that indicate an official press release.
PR_WIRES = [
    "business wire", "businesswire", "pr newswire", "prnewswire", "globenewswire",
    "globe newswire", "newsfile", "access newswire", "accesswire", "eqs news",
    "eqs-news", "newmediawire", "prweb", "send2press",
]

INDUSTRY_FEEDS = [
    ("STAT News", "https://www.statnews.com/feed/"),
    ("Endpoints News", "https://endpts.com/feed/"),
    ("FierceBiotech", "https://www.fiercebiotech.com/rss/xml"),
    ("FiercePharma", "https://www.fiercepharma.com/rss/xml"),
    ("BioPharma Dive", "https://www.biopharmadive.com/feeds/news/"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compile_alias_patterns():
    """One case-insensitive, word-boundary regex per company, matching any alias."""
    patterns = {}
    for c in COMPANIES:
        parts = [re.escape(a) for a in c["aliases"]]
        patterns[c["key"]] = re.compile(r"(?<![\w])(?:%s)(?![\w])" % "|".join(parts), re.I)
    return patterns


ALIAS_PATTERNS = _compile_alias_patterns()
NAME_BY_KEY = {c["key"]: c["name"] for c in COMPANIES}


def companies_in(text):
    """Return display names of every company mentioned in the text."""
    found = []
    for key, pat in ALIAS_PATTERNS.items():
        if pat.search(text or ""):
            found.append(NAME_BY_KEY[key])
    return found


def _norm_title(title):
    """Normalized key for de-duplication (lowercased alphanumerics, first words)."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return " ".join(words[:12])


def _to_utc(entry):
    """Best-effort published datetime in UTC, or None."""
    for attr in ("published_parsed", "updated_parsed"):
        st = entry.get(attr)
        if st:
            return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
    return None


def _strip_source_suffix(title, source):
    """Google News titles look like 'Headline - Publisher'; drop the suffix."""
    if source and title.endswith(" - " + source):
        return title[: -(len(source) + 3)].strip()
    # Fall back: strip a trailing ' - Something' only if it's short (a publisher).
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        if head and len(tail) <= 40:
            return head.strip()
    return title.strip()


def _is_press_release(source, link):
    s = (source or "").lower()
    if any(w in s for w in PR_WIRES):
        return True
    # Source is the company itself (Google News sometimes credits the newsroom).
    for c in COMPANIES:
        if any(a.lower() == s for a in c["aliases"]):
            return True
    return False


def _fetch(url):
    """Fetch a feed URL and return a parsed feedparser object (or None on failure)."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        return feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001
        print("  ! feed failed: {} ({})".format(url, exc))
        return None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def google_news_for(company):
    """Recent Google News items for one company."""
    query = '"{}" when:2d'.format(primary_query(company))
    url = "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en".format(quote(query))
    feed = _fetch(url)
    if not feed:
        return []

    items = []
    for entry in feed.entries[:GOOGLE_PER_COMPANY]:
        source = ""
        if entry.get("source") and entry.source.get("title"):
            source = entry.source.title
        title = _strip_source_suffix(entry.get("title", ""), source)
        link = entry.get("link", "")
        if not title or not link:
            continue
        text = "{} {}".format(title, entry.get("summary", ""))
        tagged = companies_in(text)
        # Always include the company this query was for, even if the alias sat in
        # the (stripped) source rather than the title.
        if company["name"] not in tagged:
            tagged.append(company["name"])
        items.append({
            "title": title,
            "link": link,
            "source": source or "Google News",
            "published": _to_utc(entry),
            "summary": "",
            "companies": tagged,
            "is_press_release": _is_press_release(source, link),
            "origin": "google",
        })
    return items


def industry_feed(name, url):
    """Items from one industry feed that mention a tracked company."""
    feed = _fetch(url)
    if not feed:
        return []
    items = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = entry.get("link", "")
        if not title or not link:
            continue
        summary = re.sub(r"<[^>]+>", "", entry.get("summary", "") or "")[:400]
        tagged = companies_in("{} {}".format(title, summary))
        if not tagged:
            continue  # only keep trade items that actually mention our companies
        items.append({
            "title": title,
            "link": link,
            "source": name,
            "published": _to_utc(entry),
            "summary": summary,
            "companies": tagged,
            "is_press_release": False,
            "origin": "industry",
        })
    return items


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _recent_enough(item, cutoff):
    pub = item.get("published")
    return pub is None or pub >= cutoff


def fetch_news():
    cutoff = datetime.now(timezone.utc).timestamp() - HOURS_LOOKBACK * 3600
    cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)

    raw = []
    print("Fetching Google News per company...")
    for c in COMPANIES:
        got = google_news_for(c)
        print("  {:<28} {} items".format(c["name"], len(got)))
        raw.extend(got)

    print("Fetching industry feeds...")
    for name, url in INDUSTRY_FEEDS:
        got = industry_feed(name, url)
        print("  {:<28} {} matching items".format(name, len(got)))
        raw.extend(got)

    # Recency filter.
    raw = [it for it in raw if _recent_enough(it, cutoff_dt)]

    # De-duplicate by normalized title, merging company tags and keeping the most
    # informative copy (press release / industry item preferred).
    best = {}
    for it in raw:
        key = _norm_title(it["title"])
        if not key:
            continue
        if key not in best:
            best[key] = it
        else:
            kept = best[key]
            # merge company tags
            for name in it["companies"]:
                if name not in kept["companies"]:
                    kept["companies"].append(name)
            kept["is_press_release"] = kept["is_press_release"] or it["is_press_release"]
            # prefer an industry item's richer summary
            if not kept["summary"] and it["summary"]:
                kept["summary"] = it["summary"]

    items = list(best.values())

    # Rank so the cap keeps the most useful items: press releases first, then
    # industry-trade items, then most recent.
    def sort_key(it):
        pub = it.get("published")
        ts = pub.timestamp() if pub else 0
        return (it["is_press_release"], it["origin"] == "industry", ts)

    items.sort(key=sort_key, reverse=True)
    if len(items) > MAX_ITEMS:
        print("Capping {} items down to {}.".format(len(items), MAX_ITEMS))
        items = items[:MAX_ITEMS]

    print("Collected {} unique news items.".format(len(items)))
    return items


if __name__ == "__main__":
    out = fetch_news()
    for it in out[:25]:
        flag = "PR" if it["is_press_release"] else "  "
        print("[{}] {:<14} {} | {}".format(
            flag, it["source"][:14], ", ".join(it["companies"][:3]), it["title"][:80]))
