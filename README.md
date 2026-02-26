# WHO Feed Filter

Automated filter for the [WHO Careers RSS feed](https://careers.who.int) that extracts only the jobs relevant to cinfo's job portal: **Geneva-based positions at Professional and Director grade (P1–P6, D1–D2)**.

The filtered feed is republished via GitHub Pages at:
**https://cinfoposte.github.io/who-feed-filter/who_feed_filter.xml**

Subscribe to this URL in any RSS reader to receive only matching WHO vacancies.

## What It Does

The raw WHO feed contains all global vacancies — consultancies, internships, national officer roles, General Service positions, and postings across dozens of duty stations. This filter applies two hard criteria:

**Location** — Duty station must be Geneva (Switzerland). Matches variants including `Geneva`, `Genève`, `Genf`, `CH-Geneva`, `CH-1211`, `Geneva (Switzerland)`, and `Switzerland (Geneva)`.

**Grade** — Must be a Professional or Director level grade: P1, P2, P3, P4, P5, P6, D1, or D2. All common WHO spelling variants are handled (`P3` / `P-3` / `P 3`).

The following role types are always excluded regardless of grade or location: Consultants, SSA contracts, Interns, Junior Professional Officers (JPO), National Officers (NOA–NOD), and General Service grades (G-/GS-).

## How It Works

Because the WHO Taleo feed often serves empty or truncated `<description>` fields, the filter operates in two stages:

1. **Stage 1 — Pre-filter on title** — fast exclusion of obvious mismatches (excluded role types like SSA, Consultant, Intern)
2. **Stage 2 — Detail page fetch** — the actual job page is fetched via HTTP and parsed for structured fields like `Duty Station` and `Grade`, which are reliably present in the HTML

The scraper (`scraper.py`) downloads the upstream feed, applies the filter logic from `who_feed_filter.py`, and writes a clean RSS 2.0 file to `who_feed_filter.xml`. GitHub Actions commits and pushes changes automatically, and GitHub Pages serves the file as a public feed URL.

## Upstream Source

The upstream data comes from the official WHO Careers RSS feed:
```
https://careers.who.int/careersection/ex/jobsearch.ftl?lang=en&portal=101430233&searchtype=3&f=null&s=3|D&a=null&multiline=true&rss=true
```

The upstream URL can be overridden via the `WHO_FEED_URL` environment variable.

## Schedule

The scraper workflow runs **daily at 07:00 UTC** (08:00 Swiss time / 09:00 Swiss summer time).

You can also trigger it manually at any time via the **Actions** tab → **WHO Feed Scraper** → **Run workflow**.

## Repository Structure

```
who-feed-filter/
├── .github/
│   └── workflows/
│       ├── run_filter.yml        # Legacy workflow (Mon/Thu)
│       └── scrape.yml            # Daily scraper workflow
├── tests/
│   └── test_filter.py            # Unit tests (pytest)
├── scraper.py                    # Scraper entry point (fetches + filters + writes RSS)
├── who_feed_filter.py            # Filter logic (regexes, grade/location checks)
├── who_feed_filter.xml           # Filtered output (auto-updated, served via Pages)
├── requirements.txt
├── CLAUDE.md
└── README.md
```

## Running Locally

```bash
# Clone and install dependencies
git clone https://github.com/cinfoposte/who-feed-filter.git
cd who-feed-filter
pip install -r requirements.txt

# Run the scraper (fetches upstream feed, writes who_feed_filter.xml)
python scraper.py

# Override upstream URL if needed
WHO_FEED_URL="https://example.com/feed.xml" python scraper.py

# Run built-in unit tests (no HTTP requests)
python who_feed_filter.py --test

# Run pytest suite
pip install pytest
pytest tests/
```

The filtered feed is written to `who_feed_filter.xml` in the repository root.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WHO_FEED_URL` (env var) | WHO Careers RSS URL | Override the upstream feed URL |
| `FETCH_DETAIL` | `True` | Fetch job detail pages for richer parsing (in `who_feed_filter.py`) |
| `REQUEST_DELAY` | `0.5` | Seconds between detail page requests |
| `LOG_LEVEL` | `INFO` | Python logging level |

## GitHub Pages Setup

To serve the filtered feed as a public URL:

1. Go to **Settings** → **Pages**
2. Under **Source**, select **Deploy from a branch**
3. Choose branch **main**, folder **/ (root)**
4. Click **Save**

After a few minutes, the feed will be available at:
```
https://cinfoposte.github.io/who-feed-filter/who_feed_filter.xml
```

> **Note:** The exact URL depends on your GitHub Pages configuration. If you use a custom domain, adjust the URL accordingly. The repository must be public (or have Pages enabled for private repos on a paid plan) for the feed to be accessible.

## Built With

- Python 3.12
- [requests](https://docs.python-requests.org/) for HTTP
- GitHub Actions for scheduling
- GitHub Pages for feed hosting

---

*Maintained by cinfo — the information and consulting centre for careers in international cooperation. [cinfo.ch](https://www.cinfo.ch)*
