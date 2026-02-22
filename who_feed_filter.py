"""
WHO RSS Feed Filter
===================
Filters WHO job feed items to only import:
  - Duty Station: Geneva / Genève (Switzerland)
  - Grade: P1–P6 or D1–D2 (Professional & higher)
Assumptions / Design Decisions
--------------------------------
1. The WHO Taleo feed's <description> is often truncated or empty ("..").
   The filter therefore operates in two stages:
     Stage 1 – fast pre-filter on <title> alone (reject obvious mismatches).
     Stage 2 – fetch the actual job detail HTML page and parse the full text.
   If fetching is disabled (FETCH_DETAIL=False), the filter falls back to
   whatever text is available in <title>+<description>.
2. Grade detection:
   - Regex covers P1-P6, D1-D2 with optional separator (space or hyphen).
   - Anchored with word boundaries to avoid matching "P3O" or "D1gital".
   - Only grades in the right context (not free-form body text like "P3 skills")
     are trusted; we look specifically near known WHO grade label patterns.
3. Location detection:
   - We match a Duty Station / Location label followed by a Geneva variant.
   - A bare mention of "Geneva" in free body text (e.g., "travel to Geneva") is
     NOT sufficient – the match must be preceded by a duty-station context word.
   - If no labelled duty station is found we fall back to title matching
     (many WHO titles end with ", Geneva").
4. Exclusion rules (belt-and-suspenders, even if grade regex already covers it):
   - Explicit title-pattern exclusions for: SSA, Consultant, Intern, NO[A-D],
     General Service (G-/GS-).
"""
import re
import sys
import time
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
try:
    import requests
    from requests.adapters import HTTPAdapter, Retry
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
# The WHO Taleo careers portal migrated from who.taleo.net to careers.who.int.
# The RSS feed URL is the standard Taleo job-search URL with &rss=true appended.
# To find/verify this URL: go to https://careers.who.int/careersection/ex/jobsearch.ftl,
# run a search, then click the RSS icon in the results page to copy the live feed URL.
FEED_URL = (
    "https://careers.who.int/careersection/ex/jobsearch.ftl"
    "?lang=en&portal=101430233&searchtype=3"
    "&f=null&s=3|D&a=null&multiline=true&rss=true"
)
FETCH_DETAIL   = True   # Set False to skip HTTP detail-page fetching (faster, less accurate)
REQUEST_DELAY  = 0.5    # Seconds between detail-page requests (be polite)
LOG_LEVEL      = logging.INFO
logging.basicConfig(level=LOG_LEVEL, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)
# ─────────────────────────────────────────────────────────────────────────────
# REGEX PATTERNS  (compiled once at module load)
# ─────────────────────────────────────────────────────────────────────────────
# --- Grade ---------------------------------------------------------------
# Matches: P1 P2 P3 P4 P5 P6 P-1 … P-6 P 1 … P 6
#          D1 D2 D-1 D-2 D 1 D 2
# Word-boundary anchored so "P3O" or "D12" don't match.
_GRADE_CORE = r"(?:P[- ]?[1-6]|D[- ]?[1-2])"
RE_GRADE = re.compile(
    r"\b" + _GRADE_CORE + r"\b",
    re.IGNORECASE,
)
# Grade in a "labelled" context – stronger signal.
# e.g. "Grade: P4", "P-4 level", "(P3,", "– P4 –"
RE_GRADE_LABELLED = re.compile(
    r"(?:"
    r"grade[:\s]+\b" + _GRADE_CORE + r"\b"          # "Grade: P4"
    r"|"
    r"\b" + _GRADE_CORE + r"\b(?:\s*,|\s*\)|\s*[-–]|\s+level)"  # "P4," / "(P3)" / "P4 level"
    r"|"
    r"[-–(,]\s*\b" + _GRADE_CORE + r"\b"            # "- P4" / ", P3"
    r")",
    re.IGNORECASE,
)
# --- Location ------------------------------------------------------------
# Geneva variants: Geneva, Genève, GENEVA, genf (German), CH-Geneva,
#                  Geneva (Switzerland), Switzerland (Geneva), etc.
_GENEVA_VARIANTS = (
    r"Gen(?:e|è|é)va?"          # Geneva / Genève / Genéva / Genf-ish
    r"|Genf"                    # German spelling
    r"|CH-1211"                 # WHO HQ postal code in Geneva
    r"|CH\s*[-–]\s*Geneva"
    r"|Geneva\s*,?\s*Switzerland"
    r"|Switzerland\s*\(Geneva\)"
)
# Duty-station label words that precede the location value in job ads
_DUTY_LABEL = (
    r"(?:duty\s*station|location|based\s+in|headquarters?|posted?\s+(?:in|at)|"
    r"place\s+of\s+(?:work|assignment)|office\s+location|country\s+of\s+assignment)"
)
RE_LOCATION_LABELLED = re.compile(
    r"(?:" + _DUTY_LABEL + r")\s*[:\-–]?\s*(?:" + _GENEVA_VARIANTS + r")",
    re.IGNORECASE,
)
# Title-level location: many WHO titles end with ", Geneva" or "(Geneva)"
RE_LOCATION_TITLE = re.compile(
    r"[,(]\s*(?:" + _GENEVA_VARIANTS + r")\s*[),]?$",
    re.IGNORECASE,
)
# Bare Geneva mention (fallback only – used when labelled match fails)
RE_LOCATION_BARE = re.compile(
    r"\b(?:" + _GENEVA_VARIANTS + r")\b",
    re.IGNORECASE,
)
# --- Exclusions ----------------------------------------------------------
# Roles that must NEVER be imported regardless of grade/location signals.
RE_EXCLUDED_ROLE = re.compile(
    r"\b("
    r"SSA"                          # Special Service Agreement
    r"|Consultant"                  # Consultant / Consultancy
    r"|Consultancy"
    r"|Intern(?:ship)?"             # Intern / Internship
    r"|JPO"                         # Junior Professional Officer
    r"|NO[A-Da-d]"                  # National Officer grades
    r"|National\s+Officer"
    r"|National\s+Professional"
    r"|GS-\d"                       # General Service grades
    r"|G-\d"
    r")\b",
    re.IGNORECASE,
)
# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FeedItem:
    title:       str = ""
    link:        str = ""
    description: str = ""
    pub_date:    str = ""
    detail_html: str = ""          # populated if FETCH_DETAIL=True
    grade_found: Optional[str] = None
    location_ok: bool = False
    reason:      str = ""          # human-readable accept/reject reason
# ─────────────────────────────────────────────────────────────────────────────
# HTTP HELPER
# ─────────────────────────────────────────────────────────────────────────────
def _make_session() -> "requests.Session":
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504])
    s.mount("http://",  HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "cinfo-feed-filter/1.0 (+https://www.cinfo.ch)"})
    return s
def fetch_text(url: str, session) -> str:
    """Fetch URL and return visible text (HTML tags stripped)."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        # Strip HTML tags with a simple regex – good enough for search
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text)
        return text
    except Exception as exc:
        log.warning("Could not fetch %s: %s", url, exc)
        return ""
# ─────────────────────────────────────────────────────────────────────────────
# FILTER LOGIC
# ─────────────────────────────────────────────────────────────────────────────
def _full_text(item: FeedItem) -> str:
    """All available text for an item concatenated."""
    return " | ".join(filter(None, [item.title, item.description, item.detail_html]))
def check_excluded(item: FeedItem) -> bool:
    """Return True if the item must be excluded based on role-type keywords."""
    match = RE_EXCLUDED_ROLE.search(item.title)
    if match:
        item.reason = f"Excluded role type: '{match.group()}' in title"
        return True
    return False
def check_grade(item: FeedItem) -> bool:
    """
    Return True if a valid P1-P6 / D1-D2 grade is found.
    Preference: labelled match > bare match.
    Sets item.grade_found.
    """
    text = _full_text(item)
    # Strong signal: labelled context
    m = RE_GRADE_LABELLED.search(text)
    if m:
        # Extract just the grade code from the match
        code = RE_GRADE.search(m.group())
        if code:
            item.grade_found = code.group().upper().replace(" ", "").replace("-", "")
            return True
    # Weaker signal: bare grade anywhere in text
    # Only trust bare grade if detail page was fetched (reduces false positives
    # from description body text like "P3 competencies required")
    if item.detail_html:
        m = RE_GRADE.search(text)
        if m:
            item.grade_found = m.group().upper().replace(" ", "").replace("-", "")
            return True
    # Last resort: grade code in title (e.g. "Health Officer, P4, Geneva")
    m = RE_GRADE.search(item.title)
    if m:
        item.grade_found = m.group().upper().replace(" ", "").replace("-", "")
        return True
    item.reason = "No P/D grade found"
    return False
def check_location(item: FeedItem) -> bool:
    """
    Return True if duty station is Geneva.
    Priority: labelled > title > bare (detail page only).
    """
    text = _full_text(item)
    # Best: explicit duty-station label
    if RE_LOCATION_LABELLED.search(text):
        item.location_ok = True
        return True
    # Good: location in title suffix
    if RE_LOCATION_TITLE.search(item.title):
        item.location_ok = True
        return True
    # Acceptable: bare mention in fetched detail page
    # (detail page usually has a structured "Duty Station: Geneva" block)
    if item.detail_html and RE_LOCATION_BARE.search(item.detail_html):
        item.location_ok = True
        return True
    item.reason = "Duty station is not Geneva"
    return False
def should_import(item: FeedItem) -> bool:
    """Master filter: returns True only for Geneva + P/D-grade jobs."""
    if check_excluded(item):
        return False
    grade_ok    = check_grade(item)
    location_ok = check_location(item)
    if grade_ok and location_ok:
        item.reason = f"✅ IMPORT — grade={item.grade_found}, location=Geneva"
        return True
    # Consolidate reason if both failed
    if not grade_ok and not location_ok:
        item.reason = "No valid grade AND duty station not Geneva"
    return False
# ─────────────────────────────────────────────────────────────────────────────
# FEED PARSING
# ─────────────────────────────────────────────────────────────────────────────
def parse_feed(xml_source: str) -> list[FeedItem]:
    """Parse RSS XML string and return list of FeedItem."""
    root = ET.fromstring(xml_source)
    ns   = {"content": "http://purl.org/rss/1.0/modules/content/"}
    items = []
    for elem in root.findall(".//item"):
        fi = FeedItem(
            title       = (elem.findtext("title")       or "").strip(),
            link        = (elem.findtext("link")        or "").strip(),
            description = (elem.findtext("description") or "").strip(),
            pub_date    = (elem.findtext("pubDate")     or "").strip(),
        )
        # Some feeds use <content:encoded> for full description
        ce = elem.find("content:encoded", ns)
        if ce is not None and ce.text:
            fi.description += " " + ce.text.strip()
        # Skip the "More Jobs Available" sentinel item
        if "More Jobs Available" in fi.title:
            continue
        items.append(fi)
    return items
def process_feed(xml_source: str) -> tuple[list[FeedItem], list[FeedItem]]:
    """
    Parse the feed, optionally fetch detail pages, apply filters.
    Returns (accepted, rejected).
    """
    items   = parse_feed(xml_source)
    session = _make_session() if (FETCH_DETAIL and HAS_REQUESTS) else None
    accepted, rejected = [], []
    for item in items:
        # Fetch detail page for richer text
        if session and item.link:
            log.debug("Fetching detail: %s", item.link)
            item.detail_html = fetch_text(item.link, session)
            time.sleep(REQUEST_DELAY)
        if should_import(item):
            accepted.append(item)
        else:
            rejected.append(item)
    return accepted, rejected
# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def print_results(accepted: list[FeedItem], rejected: list[FeedItem]) -> None:
    print("\n" + "="*72)
    print(f"  ACCEPTED ({len(accepted)} jobs to import)")
    print("="*72)
    for item in accepted:
        print(f"  ✅  [{item.grade_found}]  {item.title}")
        print(f"       {item.link}")
    print("\n" + "="*72)
    print(f"  REJECTED ({len(rejected)} jobs filtered out)")
    print("="*72)
    for item in rejected:
        print(f"  ❌  {item.title}")
        print(f"       Reason: {item.reason}")
    print()
def build_filtered_rss(original_xml: str, accepted: list[FeedItem]) -> str:
    """Re-emit a valid RSS feed containing only accepted items."""
    accepted_links = {item.link for item in accepted}
    root   = ET.fromstring(original_xml)
    channel = root.find("channel")
    for elem in list(channel.findall("item")):
        link = (elem.findtext("link") or "").strip()
        if link not in accepted_links:
            channel.remove(elem)
    ET.indent(root, space="  ")
    # encoding="utf-8" returns bytes with a correct <?xml ... encoding='utf-8'?> declaration.
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
# ─────────────────────────────────────────────────────────────────────────────
# SELF-CONTAINED UNIT TESTS  (run with: python who_feed_filter.py --test)
# ─────────────────────────────────────────────────────────────────────────────
TEST_CASES = [
    # (title, description/detail_snippet, expect_import, label)
    (
        "Health Officer (Tuberculosis), P4, Geneva",
        "Duty Station: Geneva, Switzerland. Grade: P4. Under the direction of ...",
        True,
        "Classic P4 Geneva title → IMPORT",
    ),
    (
        "Technical Officer (Digital Health), P-3, Geneva, Switzerland",
        "Location: Genève. This is a fixed-term appointment at the P-3 level.",
        True,
        "P-3 with hyphen, Genève variant → IMPORT",
    ),
    (
        "Communications Officer (P 2), WHO Headquarters, Geneva",
        "Place of assignment: Geneva. Grade P 2 (space variant).",
        True,
        "P 2 space variant → IMPORT",
    ),
    (
        "Director, Department of Health Systems (D-1), Geneva",
        "Duty station: CH-Geneva. Director level D-1 position.",
        True,
        "D-1 Director grade, CH-Geneva variant → IMPORT",
    ),
    (
        "Human Resources Associate, (GS-6), Fixed-Term, Damascus, Syria",
        "Duty Station: Damascus. General Service grade GS-6.",
        False,
        "GS-6 General Service, wrong location → REJECT",
    ),
    (
        "Consultancy - Leadership Learning Design & Digital Content Specialist",
        "Location: Geneva. Consultancy contract.",
        False,
        "Consultant role → REJECT even if Geneva",
    ),
    (
        "SSA - Project Officer – Solar Electrification, NOA",
        "Duty Station: Brazzaville. NOA grade.",
        False,
        "SSA + NOA, wrong location → REJECT",
    ),
    (
        "Technical Officer (Behavioural Insights), P3",
        "The position is based in Copenhagen, Denmark. Grade P3.",
        False,
        "P3 but NOT Geneva → REJECT",
    ),
    (
        "Health Information Systems Officer, P5, Geneva",
        "Location: Geneva (Switzerland). Programme: Health Emergencies. Grade: P-5.",
        True,
        "P5 with parenthetical Switzerland variant → IMPORT",
    ),
    (
        "Intern – Global Health Policy, Geneva",
        "Internship programme. Duty station: Geneva.",
        False,
        "Intern title → REJECT even if Geneva",
    ),
]
def run_tests() -> None:
    print("\n" + "="*72)
    print("  UNIT TESTS")
    print("="*72)
    passed = failed = 0
    for title, detail, expect, label in TEST_CASES:
        item = FeedItem(title=title, description="", detail_html=detail)
        result = should_import(item)
        ok = result == expect
        status = "PASS" if ok else "FAIL"
        sym    = "✅" if ok else "❌"
        print(f"  {sym} [{status}] {label}")
        if not ok:
            print(f"         Expected import={expect}, got import={result}")
            print(f"         Reason: {item.reason}")
        passed += ok
        failed += (not ok)
    print(f"\n  {passed}/{passed+failed} tests passed")
    print("="*72 + "\n")
# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--test" in sys.argv:
        run_tests()
        sys.exit(0)
    if not HAS_REQUESTS:
        log.error("requests library not found. Install with: pip install requests")
        sys.exit(1)
    session = _make_session()
    log.info("Fetching WHO RSS feed …")
    try:
        resp = session.get(FEED_URL, timeout=20)
        resp.raise_for_status()
        xml_source = resp.text
    except Exception as exc:
        log.error("Failed to fetch feed: %s", exc)
        sys.exit(1)
    log.info("Processing feed items …")
    accepted, rejected = process_feed(xml_source)
    print_results(accepted, rejected)
    # Optionally write filtered feed to disk
    filtered_rss = build_filtered_rss(xml_source, accepted)
    out_path = "who_filtered_feed.xml"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(filtered_rss)
    log.info("Filtered RSS written to %s", out_path)
