# Alliance News Dashboard

A self-updating website for the oncology-consortium alliance-management team. Every
**Monday and Thursday** morning it rebuilds three things:

1. **News roundup** — press releases, oncology news, and industry/business coverage
   for all 22 partner companies, sorted into **High / Medium / Low** priority.
   - **High** — the **10 most important** stories for an alliance manager: pivotal
     oncology news (trial results/readouts, FDA actions on cancer drugs, oncology
     deals) and the biggest business news.
   - **Medium** — the **next 15** most relevant items (other oncology news, mergers,
     acquisitions, earnings, executive changes).
   - **Low** — everything else about these companies (collapsed by default).

   Every item is scored for importance, so High keeps only the top 10 and Medium the
   next 15; anything past those caps falls into Low rather than being dropped. (The
   caps are adjustable — see *Customizing* below.)
2. **DepMap research** — recent academic articles (journal papers **and** preprints)
   that reference the **Cancer Dependency Map (DepMap)** or are built on DepMap data
   and targets, newest first, with preprints flagged. Pulled from **Europe PMC**,
   which full-text-searches PubMed and the preprint servers — so it catches papers
   that only mention DepMap in the methods.
3. **Stock ticker & market benchmarks** — previous-day closing price and daily %
   change for every publicly-traded partner (each linking to Yahoo Finance), plus
   two market benchmarks for context: the **S&P 500** and **XBI** (biotech ETF).

It's a static website hosted free on **GitHub Pages**, rebuilt twice a week by a free
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
Go to the **Actions** tab → **"Twice-weekly roundup"** → **Run workflow**. It takes
~2–3 minutes. After that it runs **automatically every Monday and Thursday morning**
(see the schedule below). The data file included in this repo already has real news,
DepMap papers, and stock prices; running it once just refreshes to the current day.

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
Roughly 300 headlines are classified per run, and there are ~9 runs a month
(Mon + Thu). Approximate cost:

| Sorting engine | Setup | Cost |
| --- | --- | --- |
| **Keyword rules** *(default — no key)* | none | **$0** |
| **Claude Haiku 4.5** *(set `CLASSIFIER_MODEL`)* | API key + variable | **~$0.10/run** (≈ $1/mo) |
| **Claude Opus 4.8** *(default when a key is set)* | API key | **~$0.40/run** (≈ $3–4/mo) |

Opus is the most accurate; **Haiku is the cost-friendly choice for this kind of
headline sorting** and is what we'd suggest if cost matters. You can switch any time by
changing the `CLASSIFIER_MODEL` variable. (The DepMap literature feed uses no AI.)

---

## Changing the schedule

The run is defined in [`.github/workflows/daily-update.yml`](.github/workflows/daily-update.yml).
The schedule is in **UTC**:
```yaml
- cron: "0 9 * * 1,4"
```
`0 9 * * 1,4` = **09:00 UTC on Monday (1) and Thursday (4)** = 5 AM US Eastern in summer /
4 AM in winter. To change the **days**, edit the last field (`0`=Sun … `6`=Sat; e.g.
`1,3,5` for Mon/Wed/Fri, or `*` for daily). To change the **time**, edit the hour field.
GitHub sometimes starts scheduled runs a few minutes late — that's normal.

> If you change how often it runs, also adjust `HOURS_LOOKBACK` (below) so the news
> window covers the gap between runs.

---

## Customizing the companies or sources

Everything about the companies lives in [`scripts/companies.py`](scripts/companies.py) —
the single source of truth. To **add, remove, or fix** a company, edit the list there
(name, ticker, the aliases used to match it in the news). The news roundup and the stock
ticker both pick up the change on the next build. Market benchmarks (S&P 500, XBI) are in
the `BENCHMARKS` list in the same file.

Other knobs (all optional, set as repository **Variables** or env vars):
- `MAX_HIGH` — how many items to keep in **High** (default `10`).
- `MAX_MEDIUM` — how many items to keep in **Medium** (default `15`).
- `HOURS_LOOKBACK` — how far back to include news (default `100` hours, to cover the
  up-to-4-day gap between Monday and Thursday runs).
- `MAX_ITEMS` — cap on total items per run (default `300`; the rest land in Low).
- `DEPMAP_DAYS` — how far back to include DepMap papers (default `120`).
- `DEPMAP_MAX` — max DepMap papers to show (default `25`).
- `DEPMAP_QUERY` — the Europe PMC search (default `("DepMap" OR "Cancer Dependency Map")`).
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
GitHub Action (Mon & Thu, 5 AM ET)
        │
        ├─ scripts/fetch_news.py    Google News (per company) + industry RSS feeds
        ├─ scripts/classify.py      sort into High / Medium / Low (keyword or Claude)
        ├─ scripts/fetch_stocks.py  closing price + % change (CNBC, then Nasdaq/Yahoo/Stooq)
        ├─ scripts/fetch_depmap.py  recent DepMap papers & preprints (Europe PMC)
        └─ scripts/build.py         writes docs/data.json + docs/archive/<date>.json
        │
        └─ commits docs/  ──►  GitHub Pages serves the static site
                                 (docs/index.html + style.css + app.js read the JSON)
```

A dated copy is saved under `docs/archive/` each run, so the site's **date picker** lets
you look back at previous roundups.

---

## Troubleshooting

- **"Couldn't load the roundup" on the page** — the first build hasn't run yet.
  Trigger it from the **Actions** tab (**Run workflow**), or wait for the next
  Monday/Thursday run.
- **Stock prices show "price unavailable"** — a stock data source was momentarily
  unreachable for that ticker. The page still renders; the next run usually fixes it.
  (Private/subsidiary companies intentionally show a label instead of a price.)
- **News or DepMap looks thin one run** — quiet period, or a source was temporarily
  down. The build tolerates individual source failures and uses whatever it can reach.
- **Want to re-run now** — Actions tab → "Twice-weekly roundup" → Run workflow.

---

## Notes

- For internal use by the consortium alliance-management team. Headlines and papers link
  to their original publishers; please respect their terms.
- Stock figures are informational only and **not investment advice**.
- News is aggregated via Google News and public RSS feeds; DepMap papers via Europe PMC.
  Coverage depends on what those sources publish.
