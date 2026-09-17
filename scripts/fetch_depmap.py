"""
DepMap literature watch.

Pulls recent academic articles — journal papers and preprints — that reference the
Cancer Dependency Map (DepMap) from Europe PMC. Europe PMC full-text-searches
PubMed/MEDLINE plus preprint servers (bioRxiv/medRxiv) and more, so this catches
papers that cite DepMap or are built on DepMap data/targets even when "DepMap"
appears only in the methods, not the title.

Tunable via env vars:
  DEPMAP_QUERY  - the Europe PMC search (default: DepMap / Cancer Dependency Map)
  DEPMAP_DAYS   - how far back to include papers (default 120)
  DEPMAP_MAX    - max papers to show (default 25)
"""

import os

import requests

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
QUERY = os.environ.get("DEPMAP_QUERY", '("DepMap" OR "Cancer Dependency Map")')
LOOKBACK_DAYS = int(os.environ.get("DEPMAP_DAYS", "120"))
MAX_PAPERS = int(os.environ.get("DEPMAP_MAX", "25"))

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _short_authors(author_string, n=3):
    """'Watkins-Yoon J, Lu WC, Petrunak EM, ...' -> 'Watkins-Yoon J, Lu WC, et al.'"""
    if not author_string:
        return ""
    parts = [p.strip() for p in author_string.split(",") if p.strip()]
    if len(parts) <= n:
        return ", ".join(parts)
    return ", ".join(parts[:n]) + ", et al."


def _link(r):
    """Best available link for a Europe PMC record: DOI, then the EPMC/PubMed page."""
    doi = r.get("doi")
    if doi:
        return "https://doi.org/" + doi
    src, pid = r.get("source"), r.get("id")
    if src and pid:
        return "https://europepmc.org/article/{}/{}".format(src, pid)
    if r.get("pmid"):
        return "https://pubmed.ncbi.nlm.nih.gov/" + r["pmid"]
    return "https://europepmc.org/"


def fetch_depmap_papers():
    """Recent DepMap-referencing papers & preprints, newest first."""
    from datetime import date, timedelta
    today = date.today()
    since = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    query = "{} AND (FIRST_PDATE:[{} TO {}])".format(QUERY, since, today.isoformat())
    params = {
        "query": query,
        "format": "json",
        "pageSize": 100,
        "sort": "FIRST_PDATE_D desc",
        "resultType": "lite",
    }
    try:
        resp = requests.get(EUROPE_PMC, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=25)
        resp.raise_for_status()
        results = (resp.json().get("resultList") or {}).get("result") or []
    except Exception as exc:  # noqa: BLE001 - a source hiccup shouldn't break the build
        print("  ! DepMap fetch failed ({})".format(exc))
        return []

    seen = set()
    items = []
    for r in results:
        title = (r.get("title") or "").strip().rstrip(".")
        if not title:
            continue
        key = title.lower()[:90]
        if key in seen:
            continue
        seen.add(key)
        is_preprint = r.get("source") == "PPR"
        # Journal name when known; for preprints the "Preprint" badge carries the
        # label, so leave it blank rather than repeating the word.
        journal = r.get("journalTitle") or ("" if is_preprint else (r.get("source") or ""))
        items.append({
            "title": title,
            "authors": _short_authors(r.get("authorString")),
            "journal": journal,
            "date": r.get("firstPublicationDate"),
            "link": _link(r),
            "is_preprint": is_preprint,
        })

    # Sort newest-first client-side too (don't rely solely on the server sort).
    items.sort(key=lambda it: it.get("date") or "", reverse=True)
    return items[:MAX_PAPERS]


def fetch_depmap():
    print("Fetching DepMap literature (Europe PMC)...")
    papers = fetch_depmap_papers()
    n_pre = sum(1 for p in papers if p["is_preprint"])
    print("  {} recent DepMap papers/preprints ({} preprints).".format(len(papers), n_pre))
    return {"papers": papers}


if __name__ == "__main__":
    data = fetch_depmap()
    for p in data["papers"]:
        tag = "PREPRINT" if p["is_preprint"] else "paper   "
        print("[{}] {} | {} | {}".format(tag, p["date"], p["journal"][:16], p["title"][:70]))
