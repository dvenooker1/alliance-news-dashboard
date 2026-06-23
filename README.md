# Alliance News Dashboard

A self-updating website for the oncology-consortium alliance-management team. Every
morning it rebuilds two things:

1. **News roundup** — press releases, oncology news, and industry/business coverage
   for all 22 partner companies, sorted into **High / Medium / Low** priority.
   - **High** — company press releases and anything directly oncology-related
     (new trials, trial results/readouts, FDA actions on cancer drugs, oncology deals).
   - **Medium** — major business news (mergers, acquisitions, earnings, executive changes).
   - **Low** — everything else about these companies that isn't relevant to an
     oncology alliance manager.
2. **Stock ticker** — previous-day closing price and daily % change for every
   publicly-traded partner, each linking to its Yahoo Finance page.

It's a static website hosted free on **GitHub Pages**, rebuilt each day by a free
**GitHub Action**. No server to run, nothing to pay for (the AI option below is optional).

The 22 companies: AbbVie · Amgen · Bayer · Bristol Myers Squibb · Boehringer Ingelheim ·
Deciphera · Exelixis · Genentech · Gilead · GSK · IDEAYA · Incyte · Janssen · Eli Lilly ·
Merck · Novartis · Pfizer · Pierre Fabre · Revolution Medicines · Roche · Servier · Takeda.

---

## One-time setup (about 5 minutes)

### 1. Put these files in a GitHub repository
Create a new repository on GitHub (private is fine) and upload this whole folder —
or, from this folder on your machine:
```bash
git init
git add .
git commit -m "Initial dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### 2. Turn on GitHub Pages
In the repository: **Settings → Pages**. Under **Build and deployment**, set
**Source = "Deploy from a branch"**, then **Branch = `main`** and **folder = `/docs`**,
and click **Save**. After a minute your site will be live at:
```
https://<your-username>.github.io/<your-repo>/
```

### 3. Run it once to get fresh data
Go to the **Actions** tab → **"Daily roundup"** → **Run workflow**. It takes ~2–3
minutes. After that it runs **automatically every morning** (see the schedule below).
> The data file included in this repo already has a day of real news, but its stock
> prices will show "price unavailable" until that first run populates them from the
> servers — so do run it once.

That's it. Share the Pages URL with your team.

---

## Optional: smarter sorting with AI

Out of the box, news is sorted by **keyword rules** — free, instant, no setup.
If you want sharper prioritization plus a one-line summary on each item, you can let
**Claude** read the headlines instead. The build uses Claude automatically when an API
key is present, and silently falls back to keyword rules if anything goes wrong.

1. Get an API key at **console.anthropic.com** (under API Keys).
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
   - Name: `ANTHROPIC_API_KEY`  ·  Value: your key.
3. *(Optional, to lower cost)* On the same page, the **Variables** tab → **New repository
   variable**: Name `CLASSIFIER_MODEL`, Value `claude-haiku-4-5`.

### What does the AI cost?
Roughly 240 headlines a day are classified. Approximate daily cost:

| Sorting engine | Setup | Cost |
| --- | --- | --- |
| **Keyword rules** *(default — no key)* | none | **$0** |
| **Claude Haiku 4.5** *(set `CLASSIFIER_MODEL`)* | API key + variable | **~$0.05–0.10/day** (≈ $2/mo) |
| **Claude Opus 4.8** *(default when a key is set)* | API key | **~$0.30–0.40/day** (≈ $10/mo) |

Opus is the most accurate; **Haiku is the cost-friendly choice for this kind of
headline sorting** and is what we'd suggest if cost matters. You can switch any time by
changing the `CLASSIFIER_MODEL` variable.

---

## Changing the schedule

The daily run is defined in [`.github/workflows/daily-update.yml`](.github/workflows/daily-update.yml).
The schedule is in **UTC**:
```yaml
- cron: "0 9 * * *"
```
`09:00 UTC` = **5 AM US Eastern in summer / 4 AM in winter**, so the roundup is ready by
5 AM ET year-round. To change it, edit that one line (for example `0 13 * * *` for ~9 AM ET).
GitHub sometimes starts scheduled runs a few minutes late — that's normal.

---

## Customizing the companies or sources

Everything lives in [`scripts/companies.py`](scripts/companies.py) — the single source of
truth. To **add, remove, or fix** a company, edit the list there (name, ticker, the
aliases used to match it in the news). Both the news roundup and the stock ticker pick up
the change on the next build. The file has comments explaining each field.

Other knobs (all optional, set as repository **Variables** or env vars):
- `HOURS_LOOKBACK` — how far back to include news (default `30` hours).
- `MAX_ITEMS` — cap on items per day (default `240`).
- News sources (industry RSS feeds) are listed near the top of
  [`scripts/fetch_news.py`](scripts/fetch_news.py).

---

## Running it locally (optional)

You don't need this for normal use, but to test changes on your machine:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python scripts/build.py            # keyword sorting (free)
# or, with AI sorting:
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/build.py

# then preview the site:
python -m http.server --directory docs 8000   # open http://localhost:8000
```

---

## How it works

```
GitHub Action (daily, 5 AM ET)
        │
        ├─ scripts/fetch_news.py    Google News (per company) + industry RSS feeds
        ├─ scripts/classify.py      sort into High / Medium / Low (keyword or Claude)
        ├─ scripts/fetch_stocks.py  closing price + % change (Yahoo Finance, Stooq fallback)
        └─ scripts/build.py         writes docs/data.json + docs/archive/<date>.json
        │
        └─ commits docs/  ──►  GitHub Pages serves the static site
                                 (docs/index.html + style.css + app.js read the JSON)
```

A dated copy is saved under `docs/archive/` each day, so the site's **date picker** lets
you look back at previous mornings.

---

## Troubleshooting

- **"Couldn't load the roundup" on the page** — the first daily build hasn't run yet.
  Trigger it from the **Actions** tab (**Run workflow**), or wait for tomorrow morning.
- **Stock prices show "price unavailable"** — a stock data source was momentarily
  unreachable for that ticker. The page still renders; the next run usually fixes it.
  (Private/subsidiary companies intentionally show a label instead of a price.)
- **News looks thin one day** — quiet news day, or a source feed was temporarily down.
  The build tolerates individual feed failures and uses whatever it can reach.
- **Want to re-run now** — Actions tab → "Daily roundup" → Run workflow.

---

## Notes

- For internal use by the consortium alliance-management team. Headlines link to their
  original publishers; please respect their terms.
- Stock figures are informational only and **not investment advice**.
- News is aggregated via Google News and public RSS feeds; coverage depends on what those
  sources publish.
