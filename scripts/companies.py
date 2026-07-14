"""
Company registry for the Alliance News Dashboard.

This is the single source of truth for the 22 consortium companies. Edit this
file to add/remove a company or fix a ticker, then the news roundup and stock
ticker both update automatically on the next build.

Each company has:
  key          : stable slug used internally (don't change once set)
  name         : display name shown on the site
  aliases      : names/spellings to match in news headlines & to query news for
  ticker       : stock symbol, or None if not independently traded
  ticker_note  : short label shown next to the ticker (e.g. "ADR", "via Roche")
  status       : "public" | "private" | "subsidiary" | "acquired"
  parent       : owning company (for subsidiary/acquired), else None
  note         : extra context shown on non-traded rows

Ticker / status notes (verified June 2026):
  - Bayer, Roche, Takeda, Novartis trade in the US as ADRs (BAYRY, RHHBY, TAK, NVS).
  - Genentech is a member of the Roche Group  -> shows Roche (RHHBY).
  - Janssen is J&J's pharma unit (now "J&J Innovative Medicine") -> shows J&J (JNJ).
  - Boehringer Ingelheim, Pierre Fabre, and Servier are privately/foundation held.
  - Deciphera was acquired by Ono Pharmaceutical in June 2024 and delisted; it no
    longer trades on its own, so we show a note instead of a (misleading) price.
  - "Merck" here means Merck & Co. (US, ticker MRK) -- the maker of Keytruda --
    not the German Merck KGaA.
"""

# Status constants
PUBLIC = "public"
PRIVATE = "private"
SUBSIDIARY = "subsidiary"
ACQUIRED = "acquired"


COMPANIES = [
    {
        "key": "abbvie",
        "name": "AbbVie",
        "aliases": ["AbbVie"],
        "ticker": "ABBV",
        "status": PUBLIC,
    },
    {
        "key": "amgen",
        "name": "Amgen",
        "aliases": ["Amgen"],
        "ticker": "AMGN",
        "status": PUBLIC,
    },
    {
        "key": "bayer",
        "name": "Bayer",
        "aliases": ["Bayer"],
        "ticker": "BAYRY",
        "ticker_note": "ADR",
        "status": PUBLIC,
    },
    {
        "key": "bms",
        "name": "Bristol Myers Squibb",
        "aliases": ["Bristol Myers Squibb", "Bristol-Myers Squibb", "Bristol Myers", "Bristol-Myers"],
        "ticker": "BMY",
        "status": PUBLIC,
    },
    {
        "key": "boehringer",
        "name": "Boehringer Ingelheim",
        "aliases": ["Boehringer Ingelheim", "Boehringer"],
        "ticker": None,
        "status": PRIVATE,
        "note": "Privately held — not publicly traded",
    },
    {
        "key": "deciphera",
        "name": "Deciphera",
        "aliases": ["Deciphera"],
        "ticker": None,
        "status": ACQUIRED,
        "parent": "Ono Pharmaceutical",
        "note": "Acquired by Ono Pharmaceutical (2024) — no longer publicly traded",
    },
    {
        "key": "exelixis",
        "name": "Exelixis",
        "aliases": ["Exelixis"],
        "ticker": "EXEL",
        "status": PUBLIC,
    },
    {
        "key": "genentech",
        "name": "Genentech",
        "aliases": ["Genentech"],
        "ticker": "RHHBY",
        "ticker_note": "via Roche",
        "status": SUBSIDIARY,
        "parent": "Roche",
        "note": "Member of the Roche Group — shows Roche (RHHBY)",
    },
    {
        "key": "gilead",
        "name": "Gilead Sciences",
        "aliases": ["Gilead Sciences", "Gilead"],
        "ticker": "GILD",
        "status": PUBLIC,
    },
    {
        "key": "gsk",
        "name": "GSK",
        "aliases": ["GSK", "GlaxoSmithKline"],
        "ticker": "GSK",
        "status": PUBLIC,
    },
    {
        "key": "ideaya",
        "name": "IDEAYA Biosciences",
        "aliases": ["IDEAYA Biosciences", "IDEAYA", "Ideaya"],
        "ticker": "IDYA",
        "status": PUBLIC,
    },
    {
        "key": "incyte",
        "name": "Incyte",
        "aliases": ["Incyte"],
        "ticker": "INCY",
        "status": PUBLIC,
    },
    {
        "key": "janssen",
        "name": "Janssen",
        "aliases": ["Janssen", "Johnson & Johnson Innovative Medicine", "J&J Innovative Medicine"],
        "ticker": "JNJ",
        "ticker_note": "via J&J",
        "status": SUBSIDIARY,
        "parent": "Johnson & Johnson",
        "note": "J&J's pharmaceutical unit — shows Johnson & Johnson (JNJ)",
    },
    {
        "key": "lilly",
        "name": "Eli Lilly",
        "aliases": ["Eli Lilly", "Lilly"],
        "ticker": "LLY",
        "status": PUBLIC,
    },
    {
        "key": "merck",
        "name": "Merck & Co.",
        "aliases": ["Merck & Co", "Merck"],
        "ticker": "MRK",
        "status": PUBLIC,
        "note": "Merck & Co. (US) — maker of Keytruda",
    },
    {
        "key": "novartis",
        "name": "Novartis",
        "aliases": ["Novartis"],
        "ticker": "NVS",
        "ticker_note": "ADR",
        "status": PUBLIC,
    },
    {
        "key": "pfizer",
        "name": "Pfizer",
        "aliases": ["Pfizer"],
        "ticker": "PFE",
        "status": PUBLIC,
    },
    {
        "key": "pierre_fabre",
        "name": "Pierre Fabre",
        "aliases": ["Pierre Fabre"],
        "ticker": None,
        "status": PRIVATE,
        "note": "Foundation-owned — not publicly traded",
    },
    {
        "key": "revmed",
        "name": "Revolution Medicines",
        "aliases": ["Revolution Medicines", "RevMed"],
        "ticker": "RVMD",
        "status": PUBLIC,
    },
    {
        "key": "roche",
        "name": "Roche",
        "aliases": ["Roche"],
        "ticker": "RHHBY",
        "ticker_note": "ADR",
        "status": PUBLIC,
    },
    {
        "key": "servier",
        "name": "Servier",
        "aliases": ["Servier"],
        "ticker": None,
        "status": PRIVATE,
        "note": "Foundation-owned — not publicly traded",
    },
    {
        "key": "takeda",
        "name": "Takeda",
        "aliases": ["Takeda"],
        "ticker": "TAK",
        "ticker_note": "ADR",
        "status": PUBLIC,
    },
]


# Market benchmarks shown alongside the company tickers for context (broad market
# + biotech sector). These are NOT consortium members, so they live outside
# COMPANIES and never touch news matching.
#   ticker : CNBC symbol used to fetch the quote
#   yahoo  : symbol used for the "more info" link
#   kind   : "index" (shown as a level, no $) or "etf" (shown as a $ price)
BENCHMARKS = [
    {
        "key": "sp500",
        "name": "S&P 500",
        "ticker": ".SPX",
        "yahoo": "^GSPC",
        "kind": "index",
        "note": "Broad U.S. market",
    },
    {
        "key": "xbi",
        "name": "XBI",
        "ticker": "XBI",
        "yahoo": "XBI",
        "kind": "etf",
        "note": "SPDR S&P Biotech ETF",
    },
]


def yahoo_url(ticker):
    """Yahoo Finance quote page for a ticker."""
    return "https://finance.yahoo.com/quote/{}".format(ticker)


def benchmark_link(b):
    """Yahoo Finance quote page for a benchmark (its ^-prefixed symbol url-encoded)."""
    from urllib.parse import quote
    return "https://finance.yahoo.com/quote/{}".format(quote(b["yahoo"], safe=""))


def google_news_url(query):
    """Google News search page for a free-text query (used for non-traded rows)."""
    from urllib.parse import quote_plus
    return "https://news.google.com/search?q={}&hl=en-US&gl=US&ceid=US:en".format(quote_plus(query))


def primary_query(company):
    """The most specific alias to use when searching news for this company.

    The first alias is the most specific/least ambiguous spelling, which keeps
    Google News results clean (e.g. 'Revolution Medicines' rather than 'RevMed').
    """
    return company["aliases"][0]


def link_for(company):
    """Where the stock-ticker row should link.

    Public + subsidiary companies link to a Yahoo Finance quote page; private and
    acquired companies have no live quote, so we link to a news search instead.
    """
    if company.get("ticker"):
        return yahoo_url(company["ticker"])
    return google_news_url(primary_query(company))


def by_key():
    return {c["key"]: c for c in COMPANIES}


if __name__ == "__main__":
    # Quick sanity summary when run directly.
    traded = [c for c in COMPANIES if c.get("ticker")]
    not_traded = [c for c in COMPANIES if not c.get("ticker")]
    print("{} companies total".format(len(COMPANIES)))
    print("{} with a ticker:".format(len(traded)))
    for c in traded:
        note = " ({})".format(c["ticker_note"]) if c.get("ticker_note") else ""
        print("  {:<28} {}{}".format(c["name"], c["ticker"], note))
    print("{} without a live quote:".format(len(not_traded)))
    for c in not_traded:
        print("  {:<28} {}".format(c["name"], c.get("note", "")))
