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

import html
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


def _clean_text(raw):
    """Strip HTML tags, unescape entities, and collapse whitespace.

    Some feeds (notably FierceBiotech / FiercePharma) wrap the headline in an
    <a href="...">...</a> tag inside <title>, so the raw value is markup, not
    text. Cleaning it also lets these items de-duplicate against the plain-text
    copies the same stories arrive as via Google News.
    """
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", "", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_title(title):
    """Normalized key for de-duplication (lowercased alphanumerics, first words)."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return " ".join(words[:12])


# Common words that carry no signal when comparing two headlines.
_STOP = {
    "the", "and", "for", "with", "its", "from", "that", "this", "into", "amid",
    "over", "after", "new", "says", "has", "will", "but", "are", "was", "were",
    "first", "more", "than", "out", "off", "set", "get", "gets", "via",
}


def _sig_words(title):
    """Significant words in a title (lowercased, >=4 chars, minus stopwords)."""
    return {w for w in re.findall(r"[a-z0-9]+", (title or "").lower())
            if len(w) >= 4 and w not in _STOP}


# Cancer types and event types, used to recognize when two differently-worded
# headlines are about the same oncology event. Keyed by a canonical label so that,
# e.g., "NSCLC" and "lung cancer" count as the same indication. Tokens are matched
# on word boundaries (so "miss" doesn't match "Commission", "colon" not "colonial").
_INDICATIONS = {
    "lung": ("lung", "nsclc", "sclc"),
    "breast": ("breast",),
    "prostate": ("prostate",),
    "colorectal": ("colorectal", "colon", "rectal", "crc", "mcrc"),
    "pancreatic": ("pancreatic", "pancreas"),
    "ovarian": ("ovarian",),
    "bladder": ("bladder", "urothelial"),
    "gastric": ("gastric", "stomach"),
    "melanoma": ("melanoma",),
    "lymphoma": ("lymphoma",),
    "leukemia": ("leukemia", "leukaemia"),
    "myeloma": ("myeloma",),
    "liver": ("hepatocellular",),
    "kidney": ("renal",),
    "cervical": ("cervical",),
    "brain": ("glioma", "glioblastoma"),
}
_EVENTS = {
    "approval": ("approv", "approves", "authoris", "authoriz", "clearance"),
    "fail": ("fail", "fails", "failed", "miss", "misses", "missed", "falls short",
             "setback", "sours", "falters"),
    "start": ("initiat", "begins", "begin", "starts", "first patient", "doses first"),
    "positive": ("meets primary", "met primary", "succeeds", "survival benefit",
                 "hits primary", "positive results", "positive data"),
    "submission": ("filing", "submits", "submission", "priority review"),
}


def _compile_terms(groups):
    """Compile each label's tokens into one word-boundary regex (multiword tokens
    keep internal spaces; \\b avoids matching inside longer words)."""
    out = {}
    for label, toks in groups.items():
        out[label] = re.compile(r"\b(?:%s)" % "|".join(re.escape(t) for t in toks), re.I)
    return out


_IND_PATTERNS = _compile_terms(_INDICATIONS)
_EVENT_PATTERNS = _compile_terms(_EVENTS)

# Generic pharma/news words that are not distinctive enough to identify a story.
# What remains after removing these (and company names) is mostly drug / product /
# program names — a strong same-story signal when shared.
_GENERIC = {
    "approval", "approved", "approves", "european", "commission", "marketing",
    "authorisation", "authorization", "regulatory", "tracker", "expands", "label",
    "receives", "gains", "wins", "reports", "results", "result", "phase", "trial",
    "trials", "study", "data", "cancer", "tumor", "tumour", "drug", "drugs",
    "therapy", "therapies", "treatment", "agency", "late", "stage", "primary",
    "endpoint", "survival", "disease", "oncology", "pharma", "pharmaceutical",
    "pharmaceuticals", "company", "deal", "regimen", "mutant", "metastatic",
    "metast", "version", "first", "line", "patients", "patient", "adult",
    "combination", "laboratoires", "experimental", "global", "advanced", "press",
}
_COMPANY_WORDS = {
    w for c in COMPANIES for a in c["aliases"]
    for w in re.findall(r"[a-z0-9]+", a.lower()) if len(w) >= 4
}


def _onc_signature(title):
    """(cancer-type set, event-type set) recognized in a headline."""
    t = " {} ".format(title or "")
    inds = {k for k, pat in _IND_PATTERNS.items() if pat.search(t)}
    evs = {k for k, pat in _EVENT_PATTERNS.items() if pat.search(t)}
    return inds, evs


def _content_tokens(words):
    """Distinctive tokens (drug/product/program names) — significant words minus
    generic pharma terms and company names."""
    return {w for w in words if w not in _GENERIC and w not in _COMPANY_WORDS}


def _dedupe_near(items, threshold=0.6):
    """Merge near-duplicate stories that the exact-title key misses — e.g. one wire
    story reworded by several aggregators. Two items merge only if they share a
    company, do NOT conflict on cancer type or event type, AND match on one of:
      * heavy word overlap (Jaccard >= threshold);
      * same cancer type + same event (catches "NSCLC trial fails" vs "lung cancer
        drug misses goal");
      * a shared distinctive token (drug/product name) together with a shared event
        or cancer type (catches "EC approval for Braftovi" vs "EU approval for
        Braftovi regimen").
    The conflict guards keep genuinely different stories apart: a lung approval won't
    merge with a bladder approval, nor an approval with a trial failure. Items are
    assumed sorted best-first, so each cluster keeps its best-ranked copy."""
    kept = []
    sigs = []  # parallel to `kept`: dict(words, toks, comps, inds, evs)
    for it in items:
        words = _sig_words(it["title"])
        toks = _content_tokens(words)
        comps = set(it.get("companies", []))
        inds, evs = _onc_signature(it["title"])
        dup_of = None
        for i, s in enumerate(sigs):
            if not (comps & s["comps"]):
                continue
            # Hard blocks: named-but-different cancer type, or opposite event type.
            if inds and s["inds"] and not (inds & s["inds"]):
                continue
            if evs and s["evs"] and not (evs & s["evs"]):
                continue
            union = words | s["words"]
            jaccard = len(words & s["words"]) / len(union) if union else 0
            inds_shared = bool(inds & s["inds"])
            evs_shared = bool(evs & s["evs"])
            toks_shared = bool(toks & s["toks"])
            if (jaccard >= threshold
                    or (inds_shared and evs_shared)
                    or (toks_shared and (evs_shared or inds_shared))):
                dup_of = i
                break
        if dup_of is None:
            kept.append(it)
            sigs.append({"words": words, "toks": toks, "comps": comps,
                         "inds": inds, "evs": evs})
            continue
        keep = kept[dup_of]
        for name in it["companies"]:
            if name not in keep["companies"]:
                keep["companies"].append(name)
        keep["is_press_release"] = keep["is_press_release"] or it["is_press_release"]
        if not keep["summary"] and it["summary"]:
            keep["summary"] = it["summary"]
        s = sigs[dup_of]
        s["words"] |= words
        s["toks"] |= toks
        s["comps"] |= comps
        s["inds"] |= inds
        s["evs"] |= evs
    return kept


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
        title = _strip_source_suffix(_clean_text(entry.get("title", "")), source)
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
        title = _clean_text(entry.get("title"))
        link = entry.get("link", "")
        if not title or not link:
            continue
        summary = _clean_text(entry.get("summary", ""))[:400]
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

    # Collapse near-duplicate stories (same event, reworded by different outlets)
    # that slipped past the exact-title key. Done after the sort so each cluster
    # keeps its best-ranked copy.
    before = len(items)
    items = _dedupe_near(items)
    if len(items) < before:
        print("Merged {} near-duplicate items.".format(before - len(items)))

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
