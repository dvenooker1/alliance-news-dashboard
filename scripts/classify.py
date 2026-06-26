"""
Priority classification for news items.

Two engines, chosen automatically:

  * Keyword rules (always available, no setup, no cost). Sorts each item into
    high / medium / low using oncology vs. business term matching.
  * Claude (used automatically when ANTHROPIC_API_KEY is set). Reads each headline
    the way an analyst would, judges oncology relevance and priority, and writes a
    one-line summary. Falls back to keyword rules on any error.

Priority taxonomy (from the alliance-manager brief):
  HIGH   - company press releases, or anything directly oncology-related
           (new trials, trial results, FDA actions on cancer drugs, etc.)
  MEDIUM - major business news (M&A, earnings, executive changes, litigation...)
  LOW    - everything else about these companies that isn't relevant to an
           oncology-consortium alliance manager
"""

import os
import re

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# ---------------------------------------------------------------------------
# Keyword engine
# ---------------------------------------------------------------------------

# Oncology / clinical signals -> HIGH. Lowercased substring match.
ONCOLOGY_TERMS = [
    "oncolog", "cancer", "tumor", "tumour", "carcinoma", "lymphoma", "leukemia",
    "leukaemia", "melanoma", "myeloma", "glioma", "glioblastoma", "sarcoma",
    "metasta", "neoplas", "malignan", "immuno-oncology", "immunooncology",
    "checkpoint inhibitor", "pd-1", "pd-l1", "pdl1", "kras", "egfr", "her2",
    "braf", "antibody-drug conjugate", "antibody drug conjugate", " adc ",
    "car-t", "car t-cell", "car t cell", "bispecific", "oncolytic",
    "solid tumor", "solid tumour", "nsclc", "sclc", "breast cancer",
    "prostate cancer", "lung cancer", "colorectal", "pancreatic cancer",
    "ovarian cancer", "bladder cancer", "gastric cancer", "hematolog",
    "haematolog", "radioligand", "radiopharmaceutical", "asco", "esmo",
]

# Clinical-development signals. These mark something as HIGH *when combined with*
# an oncology term, and otherwise just nudge toward relevance.
CLINICAL_TERMS = [
    "phase 1", "phase 2", "phase 3", "phase i", "phase ii", "phase iii",
    "phase 1/2", "phase 2/3", "topline", "top-line", "data readout", "readout",
    "overall survival", "progression-free", "progression free",
    "objective response", "response rate", "clinical trial", "trial results",
    "fda approv", "fda accept", "breakthrough therapy", "priority review",
    "accelerated approval", "biologics license", "marketing authorization",
    "marketing authorisation", "fast track", "orphan drug", "chmp",
    "investigational", "interim analysis", "primary endpoint",
]

# Major business news -> MEDIUM. Lowercased substring match.
BUSINESS_TERMS = [
    "merger", "acquisition", "to acquire", "acquires", "acquired", "takeover",
    "buyout", "buy out", "divest", "spin-off", "spinoff", "joint venture",
    "partnership", "collaborat", "licensing deal", "license agreement",
    "licensing agreement", "earnings", "revenue", "profit", "guidance",
    "forecast", "quarterly results", "dividend", "buyback", "share repurchase",
    "layoff", "job cuts", "restructur", "ceo", "cfo", "chief executive",
    "chief ", "steps down", "resign", "appoint", "names new", "named ceo",
    "executive", "board of directors",
    "lawsuit", "sues ", "litigation", "settlement", "antitrust", "ftc ",
    "investigation", "recall", "market cap", "ipo", "bankrupt", "stake",
    "billion", "million deal",
]

# Pivotal clinical / regulatory events — the highest-value news for an alliance
# manager (trial readouts, approvals, failures). Used to rank importance.
PIVOTAL_TERMS = [
    "fda approv", "fda accept", "approval", "approved", "phase 3", "phase iii",
    "phase ii/iii", "phase 2/3", "overall survival", "topline", "top-line",
    "readout", "primary endpoint", "breakthrough therapy", "priority review",
    "accelerated approval", "chmp", "complete response letter",
    "meets primary", "met primary", "fails", "failed", "missed",
]

# High-value corporate events (large M&A) — important even when not oncology.
DEAL_TERMS = ["acqui", "merger", "takeover", "buyout", "to buy", "billion"]


def _matches(text, terms):
    return [t for t in terms if t in text]


def keyword_classify(item):
    """Return (priority, is_oncology) for a single item using keyword rules."""
    text = " {} {} ".format(item.get("title", ""), item.get("summary", "")).lower()

    onc_hits = _matches(text, ONCOLOGY_TERMS)
    is_oncology = bool(onc_hits)

    # Press releases are HIGH by definition (per the brief).
    if item.get("is_press_release"):
        return HIGH, is_oncology

    # Anything directly oncology-related is HIGH.
    if is_oncology:
        return HIGH, True

    # Business news is MEDIUM.
    if _matches(text, BUSINESS_TERMS):
        return MEDIUM, False

    # A clinical/regulatory signal without an explicit cancer term is still worth
    # surfacing for an oncology team -> MEDIUM rather than LOW.
    if _matches(text, CLINICAL_TERMS):
        return MEDIUM, False

    return LOW, False


def keyword_importance(item, priority, is_oncology):
    """A 0-100 importance estimate for ranking (keyword fallback for Claude's score).

    Tuned so an oncology alliance manager's top stories — pivotal cancer trial
    results, FDA actions, big deals — float to the top, and corporate-fluff press
    releases stay low even though every PR is nominally 'high' priority.
    """
    text = " {} {} ".format(item.get("title", ""), item.get("summary", "")).lower()
    score = 5
    if is_oncology:
        score += 35
        if _matches(text, PIVOTAL_TERMS):
            score += 30          # pivotal oncology event — the most consequential news
        elif _matches(text, CLINICAL_TERMS):
            score += 15
    elif _matches(text, PIVOTAL_TERMS):
        score += 12              # non-oncology regulatory/clinical event
    if item.get("is_press_release"):
        score += 10
    if _matches(text, DEAL_TERMS):
        score += 18              # major M&A
    elif priority == MEDIUM:
        score += 8
    return max(0, min(100, score))


def classify_keyword(items):
    for item in items:
        priority, is_oncology = keyword_classify(item)
        item["priority"] = priority
        item["is_oncology"] = is_oncology
        item["importance"] = keyword_importance(item, priority, is_oncology)
        item.setdefault("summary_ai", None)
        item["engine"] = "keyword"
    return items


# ---------------------------------------------------------------------------
# Claude engine
# ---------------------------------------------------------------------------

DEFAULT_MODEL = os.environ.get("CLASSIFIER_MODEL", "claude-opus-4-8")
CHUNK_SIZE = 25

_SYSTEM = (
    "You are an analyst supporting alliance managers who run an oncology "
    "consortium of pharma companies. For each news item, decide how relevant it "
    "is to an oncology-focused alliance manager and assign a priority:\n"
    "  HIGH   = a substantive company press release, OR anything directly "
    "oncology-related (new cancer trials, trial results/readouts, FDA or "
    "regulatory actions on oncology drugs, oncology deals, conference data). "
    "Exception: a press release that is pure corporate communications (DEI/CSR, "
    "sponsorships, events, awards, generic 'commitment to health' posts) with no "
    "oncology, clinical, regulatory, or business substance should be MEDIUM or "
    "LOW, not HIGH.\n"
    "  MEDIUM = major business news not specific to oncology (mergers, "
    "acquisitions, earnings, executive changes, major litigation, large "
    "non-oncology pipeline news).\n"
    "  LOW    = everything else about the company that an oncology-consortium "
    "alliance manager would not need (consumer products, minor non-oncology "
    "items, generic market commentary, stock-movement-only stories).\n"
    "Also return is_oncology (is the item about cancer / oncology?), "
    "is_press_release (does it read as an official company announcement?), and a "
    "single factual summary sentence of at most 24 words with no hype.\n"
    "Finally, return an `importance` score from 0-100 for how much this matters to "
    "an alliance manager who can only follow a handful of stories a day:\n"
    "  90-100 = pivotal oncology trial results/readouts, FDA or regulatory "
    "decisions on cancer drugs, or major deals (M&A) involving these companies.\n"
    "  60-89  = other genuine oncology news, or significant business news.\n"
    "  30-59  = routine corporate/business items (minor appointments, ordinary "
    "earnings, sponsorships).\n"
    "  0-29   = minor, off-topic, or stock-movement-only stories.\n"
    "Reserve the top range for the genuinely most consequential stories — most "
    "items should score below 60, and a corporate-communications press release "
    "with no oncology/clinical/regulatory/deal substance should score low even "
    "though it is a press release."
)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "priority": {"type": "string", "enum": [HIGH, MEDIUM, LOW]},
                    "is_oncology": {"type": "boolean"},
                    "is_press_release": {"type": "boolean"},
                    "summary": {"type": "string"},
                    "importance": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["index", "priority", "is_oncology", "is_press_release", "summary", "importance"],
            },
        }
    },
    "required": ["results"],
}


def _claude_classify_chunk(client, chunk):
    """Classify one chunk with Claude. Returns {index: result-dict} or {} on error."""
    import json

    lines = []
    for i, item in enumerate(chunk):
        companies = ", ".join(item.get("companies", [])) or "unknown"
        src = item.get("source", "unknown source")
        pr_hint = " [looks like a press release]" if item.get("is_press_release") else ""
        lines.append(
            "{}. [{}] (source: {}{}) {}".format(
                i, companies, src, pr_hint, item.get("title", "").strip()
            )
        )
    user = (
        "Classify these {} news items. Use the exact `index` number shown.\n\n{}".format(
            len(chunk), "\n".join(lines)
        )
    )

    try:
        resp = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        return {r["index"]: r for r in data.get("results", [])}
    except Exception as exc:  # noqa: BLE001 - any failure -> fall back to keywords
        print("  ! Claude classification failed for a chunk ({}); using keywords".format(exc))
        return {}


def classify_claude(items):
    """Classify with Claude, falling back to keyword rules per-item on any gap."""
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    print("  Classifying {} items with Claude ({})...".format(len(items), DEFAULT_MODEL))

    for start in range(0, len(items), CHUNK_SIZE):
        chunk = items[start:start + CHUNK_SIZE]
        results = _claude_classify_chunk(client, chunk)
        for i, item in enumerate(chunk):
            r = results.get(i)
            if r:
                item["priority"] = r["priority"]
                item["is_oncology"] = bool(r["is_oncology"])
                # Trust the model's PR judgment, but keep an upstream True (domain-based).
                item["is_press_release"] = item.get("is_press_release") or bool(r["is_press_release"])
                item["summary_ai"] = (r.get("summary") or "").strip() or None
                item["importance"] = max(0, min(100, int(r.get("importance") or 0)))
                item["engine"] = "claude"
            else:
                priority, is_oncology = keyword_classify(item)
                item["priority"] = priority
                item["is_oncology"] = is_oncology
                item["summary_ai"] = None
                item["importance"] = keyword_importance(item, priority, is_oncology)
                item["engine"] = "keyword"
    return items


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def claude_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and \
        os.environ.get("USE_CLAUDE", "1") != "0"


def classify(items):
    """Classify items in place and return them. Picks the engine automatically."""
    if not items:
        return items
    if claude_available():
        try:
            return classify_claude(items)
        except Exception as exc:  # noqa: BLE001
            print("  ! Claude unavailable ({}); using keyword rules".format(exc))
            return classify_keyword(items)
    print("  No ANTHROPIC_API_KEY set — using keyword rules.")
    return classify_keyword(items)


if __name__ == "__main__":
    # Tiny self-test of the keyword engine.
    samples = [
        {"title": "Merck's Keytruda shows overall survival benefit in lung cancer trial", "summary": ""},
        {"title": "Pfizer to acquire biotech for $5 billion", "summary": ""},
        {"title": "AbbVie announces new oncology data at ASCO", "summary": "", "is_press_release": True},
        {"title": "Gilead names new chief financial officer", "summary": ""},
        {"title": "Bayer consumer health launches new sunscreen line", "summary": ""},
    ]
    for s in classify_keyword(list(samples)):
        print("{:<6} onc={!s:<5} {}".format(s["priority"], s["is_oncology"], s["title"]))
