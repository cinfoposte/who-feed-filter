# WHO Feed Filter

Automated filter for the [WHO Careers RSS feed](https://careers.who.int) that extracts only the jobs relevant to cinfo's job portal: **Geneva-based positions at Professional and Director grade (P1–P6, D1–D2)**.

The live filtered feed is accessible at:
`https://cinfoposte.github.io/who-feed-filter/who_filtered_feed.xml`

## What It Does

The raw WHO feed contains all global vacancies — consultancies, internships, national officer roles, General Service positions, and postings across dozens of duty stations. This filter applies two hard criteria:

**Location** — Duty station must be Geneva (Switzerland). Matches variants including `Geneva`, `Genève`, `Genf`, `CH-Geneva`, `CH-1211`, `Geneva (Switzerland)`, and `Switzerland (Geneva)`.

**Grade** — Must be a Professional or Director level grade: P1, P2, P3, P4, P5, P6, D1, or D2. All common WHO spelling variants are handled (`P3` / `P-3` / `P 3`).

The following role types are always excluded regardless of grade or location: Consultants, SSA contracts, Interns, Junior Professional Officers (JPO), National Officers (NOA–NOD), and General Service grades (G-/GS-).

## How It Works

Because the WHO Taleo feed often serves empty or truncated `<description>` fields, the filter operates in two stages:

1. **Pre-filter on title** — fast exclusion of obvious mismatches (wrong role type, wrong grade in title)
2. **Detail page fetch** — the actual job page is fetched and parsed for structured fields like `Duty Station` and `Grade`, which are reliably present in the HTML

The output is a valid filtered RSS file written to `who_filtered_feed.xml`, which is automatically committed back to this repository and served via GitHub Pages.

## Schedule

The workflow runs on **Mondays and Thursdays at 07:00 UTC** (08:00 Swiss time / 09:00 Swiss summer time).

You can also trigger it manually at any time via the **Actions** tab → **WHO Feed Filter** → **Run workflow**.

## Repository Structure

```
who-feed-filter/
├── .github/
│   └── workflows/
│       └── run_filter.yml        # GitHub Actions schedule and job definition
├── tests/
│   └── test_filter.py            # Unit tests (pytest)
├── who_feed_filter.py            # Main filter script
├── who_filtered_feed.xml         # Generated output (auto-updated by Actions)
├── requirements.txt
└── README.md
```

## Running Locally

```bash
# Clone and install dependencies
git clone https://github.com/cinfoposte/who-feed-filter.git
cd who-feed-filter
pip install -r requirements.txt

# Run built-in unit tests (no HTTP requests)
python who_feed_filter.py --test

# Run full filter (fetches detail pages — takes ~1–2 min)
python who_feed_filter.py
```

The filtered feed is written to `who_filtered_feed.xml`.

You can also run the pytest suite:

```bash
pip install pytest
pytest tests/
```

## Configuration

All configuration options are at the top of `who_feed_filter.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `FEED_URL` | WHO Careers URL | Source feed to filter |
| `FETCH_DETAIL` | `True` | Fetch job detail pages for richer parsing |
| `REQUEST_DELAY` | `0.5` | Seconds between detail page requests |
| `LOG_LEVEL` | `INFO` | Python logging level |

## GitHub Pages Setup

To serve the filtered feed as a public URL:

1. Go to **Settings** → **Pages**
2. Under **Source**, select **Deploy from a branch**
3. Choose branch `main`, folder `/ (root)`
4. Click **Save**

The feed will be available at `https://cinfoposte.github.io/who-feed-filter/who_filtered_feed.xml`

## Built With

- Python 3.12
- [requests](https://docs.python-requests.org/) for HTTP
- GitHub Actions for scheduling

---

*Maintained by cinfo — the information and consulting centre for careers in international cooperation. [cinfo.ch](https://www.cinfo.ch)*
