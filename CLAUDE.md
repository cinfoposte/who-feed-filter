# WHO Feed Filter
Automated filter for the [WHO Taleo RSS feed](http://who.taleo.net) that extracts only the jobs relevant to cinfo's job portal: **Geneva-based positions at Professional and Director grade (P1–P6, D1–D2)**.

Runs twice a week via GitHub Actions and commits the filtered output as a clean RSS file ready for import.

---

## What It Does

The raw WHO feed contains all global vacancies — consultancies, internships, national officer roles, General Service positions, and postings across dozens of duty stations. This filter applies two hard criteria:

**Location** — Duty station must be Geneva (Switzerland). Matches variants including `Geneva`, `Genève`, `Genf`, `CH-Geneva`, `CH-1211`, `Geneva (Switzerland)`, and `Switzerland (Geneva)`.

**Grade** — Must be a Professional or Director level grade: P1, P2, P3, P4, P5, P6, D1, or D2. All common WHO spelling variants are handled (`P3` / `P-3` / `P 3`).

The following role types are always excluded regardless of grade or location: Consultants, SSA contracts, Interns, Junior Professional Officers (JPO), National Officers (NOA–NOD), and General Service grades (G-/GS-).

---

## How It Works

Because the WHO Taleo feed often serves empty or truncated `<description>` fields, the filter operates in two stages:

1. **Pre-filter on title** — fast exclusion of obvious mismatches (wrong role type, wrong grade in title)
2. **Detail page fetch** — the actual job page is fetched and parsed for structured fields like `Duty Station` and `Grade`, which are reliably present in the HTML

The output is a valid filtered RSS file written to `who_filtered_feed.xml` (at the repository root), which is automatically committed back to this repository after each run.

---

## Schedule

The workflow runs on **Mondays and Thursdays at 07:00 UTC** (08:00 Swiss time / 09:00 Swiss summer time).

You can also trigger it manually at any time via the **Actions** tab → **WHO Feed Filter** → **Run workflow**.

---

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
├── CLAUDE.md                     # Context file for Claude Code
├── requirements.txt
└── README.md
```

---

## Running Locally

```bash
# Clone and install dependencies
git clone https://github.com/YOUR-USERNAME/who-feed-filter.git
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

---

## Configuration

All configuration options are at the top of `who_feed_filter.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `FEED_URL` | WHO Taleo URL | Source feed to filter |
| `FETCH_DETAIL` | `True` | Fetch job detail pages for richer parsing |
| `REQUEST_DELAY` | `0.5` | Seconds between detail page requests |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Filter Rules Reference

### Grade Regex
```
\b(?:P[- ]?[1-6]|D[- ]?[1-2])\b
```
Matches P1–P6 and D1–D2 in all common WHO spacing variants.

### Location Patterns
The filter looks for a duty-station context label (e.g. `Duty Station:`, `Location:`, `Based in:`) followed by one of these Geneva variants:

```
Geneva / Genève / Genéva / Genf / CH-Geneva / CH-1211
Geneva, Switzerland / Switzerland (Geneva)
```

A bare mention of "Geneva" in the body text (e.g. "occasional travel to Geneva") is not sufficient without a duty-station label.

### Exclusion Keywords (title match)
```
SSA | Consultant | Consultancy | Intern | Internship | JPO
NOA | NOB | NOC | NOD | National Officer | National Professional
GS-[0-9] | G-[0-9]
```

---

## Adapting the Filter

| If WHO changes... | Edit this... |
|-------------------|-------------|
| How grade is written | `_GRADE_CORE` regex in the script |
| Duty station label wording | `_DUTY_LABEL` in `RE_LOCATION_LABELLED` |
| Geneva office name or postal code | `_GENEVA_VARIANTS` in the script |
| Feed URL | `FEED_URL` constant at the top of the script |
| Run schedule | `cron:` lines in `.github/workflows/run_filter.yml` |

---

## Built With

- Python 3.12
- [requests](https://docs.python-requests.org/) for HTTP
- GitHub Actions for scheduling

---

*Maintained by cinfo — the information and consulting centre for careers in international cooperation. [cinfo.ch](https://www.cinfo.ch)*
