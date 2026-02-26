#!/usr/bin/env python3
"""
WHO RSS Feed Scraper
====================
Downloads the official WHO careers RSS feed, filters it to Geneva-based
Professional/Director-grade positions (P1–P6, D1–D2), and writes the
result as a valid RSS 2.0 file for republication via GitHub Pages.

The WHO careers portal runs on Oracle Taleo, which aggressively blocks
bot-like requests.  This scraper uses browser-like HTTP headers and a
two-step session flow (visit the career section first to acquire cookies,
then request the RSS feed) to avoid 403 rejections.
"""

import os
import re
import sys
import time
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    import requests
    from requests.adapters import HTTPAdapter, Retry
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests",
          file=sys.stderr)
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

CAREER_SECTION_URL = (
    "https://careers.who.int/careersection/ex/jobsearch.ftl"
)

DEFAULT_FEED_URL = (
    "https://careers.who.int/careersection/ex/jobsearch.ftl"
    "?lang=en&portal=101430233&searchtype=3"
    "&f=null&s=3|D&a=null&multiline=true&rss=true"
)

FEED_URL = os.environ.get("WHO_FEED_URL", DEFAULT_FEED_URL)
OUTPUT_FILE = "who_feed_filter.xml"
REQUEST_DELAY = 0.5     # seconds between detail-page requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# BROWSER-LIKE HTTP SESSION
# ─────────────────────────────────────────────────────────────────────────────

# Realistic Chrome-on-Linux User-Agent
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_BROWSER_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _make_session() -> requests.Session:
    """Create a requests session with browser-like headers and retry logic."""
    s = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    s.mount("http://",  HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update(_BROWSER_HEADERS)
    return s


def _warm_session(session: requests.Session) -> None:
    """
    Visit the career section landing page first to acquire Taleo session
    cookies before requesting the RSS feed.  This mimics a real browser
    flow and prevents 403 blocks from the Taleo bot-detection layer.
    """
    log.info("Warming session: visiting career section for cookies …")
    try:
        resp = session.get(CAREER_SECTION_URL, timeout=30)
        log.info("Career section response: %d (%d bytes)",
                 resp.status_code, len(resp.content))
    except Exception as exc:
        log.warning("Could not warm session (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# REGEX PATTERNS
# ─────────────────────────────────────────────────────────────────────────────

# --- Grade ---------------------------------------------------------------
_GRADE_CORE = r"(?:P[- ]?[1-6]|D[- ]?[1-2])"
RE_GRADE = re.compile(r"\b" + _GRADE_CORE + r"\b", re.IGNORECASE)
RE_GRADE_LABELLED = re.compile(
    r"(?:"
    r"grade[:\s]+\b" + _GRADE_CORE + r"\b"
    r"|"
    r"\b" + _GRADE_CORE + r"\b(?:\s*,|\s*\)|\s*[-–]|\s+level)"
    r"|"
    r"[-–(,]\s*\b" + _GRADE_CORE + r"\b"
    r")",
    re.IGNORECASE,
)

# --- Location ------------------------------------------------------------
_GENEVA_VARIANTS = (
    r"Gen(?:e|è|é)va?"
    r"|Genf"
    r"|CH-1211"
    r"|CH\s*[-–]\s*Geneva"
    r"|Geneva\s*,?\s*Switzerland"
    r"|Switzerland\s*\(Geneva\)"
)
_DUTY_LABEL = (
    r"(?:duty\s*station|location|based\s+in|headquarters?|"
    r"posted?\s+(?:in|at)|place\s+of\s+(?:work|assignment)|"
    r"office\s+location|country\s+of\s+assignment)"
)
RE_LOCATION_LABELLED = re.compile(
    r"(?:" + _DUTY_LABEL + r")\s*[:\-–]?\s*(?:" + _GENEVA_VARIANTS + r")",
    re.IGNORECASE,
)
RE_LOCATION_TITLE = re.compile(
    r"[,(]\s*(?:" + _GENEVA_VARIANTS + r")\s*[),]?$",
    re.IGNORECASE,
)
RE_LOCATION_BARE = re.compile(
    r"\b(?:" + _GENEVA_VARIANTS + r")\b",
    re.IGNORECASE,
)

# --- Exclusions ----------------------------------------------------------
RE_EXCLUDED_ROLE = re.compile(
    r"\b("
    r"SSA"
    r"|Consultant"
    r"|Consultancy"
    r"|Intern(?:ship)?"
    r"|JPO"
    r"|NO[A-Da-d]"
    r"|National\s+Officer"
    r"|National\s+Professional"
    r"|GS-\d"
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
    detail_html: str = ""
    grade_found: Optional[str] = None
    location_ok: bool = False
    reason:      str = ""


# ─────────────────────────────────────────────────────────────────────────────
# FILTER LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def _full_text(item: FeedItem) -> str:
    return " | ".join(filter(None, [item.title, item.description, item.detail_html]))


def check_excluded(item: FeedItem) -> bool:
    match = RE_EXCLUDED_ROLE.search(item.title)
    if match:
        item.reason = f"Excluded role type: '{match.group()}' in title"
        return True
    return False


def check_grade(item: FeedItem) -> bool:
    text = _full_text(item)
    m = RE_GRADE_LABELLED.search(text)
    if m:
        code = RE_GRADE.search(m.group())
        if code:
            item.grade_found = code.group().upper().replace(" ", "").replace("-", "")
            return True
    if item.detail_html:
        m = RE_GRADE.search(text)
        if m:
            item.grade_found = m.group().upper().replace(" ", "").replace("-", "")
            return True
    m = RE_GRADE.search(item.title)
    if m:
        item.grade_found = m.group().upper().replace(" ", "").replace("-", "")
        return True
    item.reason = "No P/D grade found"
    return False


def check_location(item: FeedItem) -> bool:
    text = _full_text(item)
    if RE_LOCATION_LABELLED.search(text):
        item.location_ok = True
        return True
    if RE_LOCATION_TITLE.search(item.title):
        item.location_ok = True
        return True
    if item.detail_html and RE_LOCATION_BARE.search(item.detail_html):
        item.location_ok = True
        return True
    item.reason = "Duty station is not Geneva"
    return False


def should_import(item: FeedItem) -> bool:
    if check_excluded(item):
        return False
    grade_ok = check_grade(item)
    location_ok = check_location(item)
    if grade_ok and location_ok:
        item.reason = f"IMPORT — grade={item.grade_found}, location=Geneva"
        return True
    if not grade_ok and not location_ok:
        item.reason = "No valid grade AND duty station not Geneva"
    return False


# ─────────────────────────────────────────────────────────────────────────────
# FEED PARSING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_detail(url: str, session: requests.Session) -> str:
    """Fetch a job detail page and return visible text (HTML tags stripped)."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text)
        return text
    except Exception as exc:
        log.warning("Could not fetch %s: %s", url, exc)
        return ""


def parse_feed(xml_source: str) -> list[FeedItem]:
    """Parse RSS XML string and return list of FeedItem."""
    root = ET.fromstring(xml_source)
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    items = []
    for elem in root.findall(".//item"):
        fi = FeedItem(
            title       = (elem.findtext("title")       or "").strip(),
            link        = (elem.findtext("link")        or "").strip(),
            description = (elem.findtext("description") or "").strip(),
            pub_date    = (elem.findtext("pubDate")     or "").strip(),
        )
        ce = elem.find("content:encoded", ns)
        if ce is not None and ce.text:
            fi.description += " " + ce.text.strip()
        if "More Jobs Available" in fi.title:
            continue
        items.append(fi)
    return items


# ─────────────────────────────────────────────────────────────────────────────
# TWO-STAGE FILTER
# ─────────────────────────────────────────────────────────────────────────────

def filter_feed(xml_source: str, session: requests.Session
                ) -> tuple[list[FeedItem], list[FeedItem]]:
    """
    Stage 1: prefilter on title (reject excluded role types).
    Stage 2: fetch detail page HTML; confirm grade + location.
    """
    items = parse_feed(xml_source)
    log.info("Parsed %d items from upstream feed", len(items))

    accepted, rejected = [], []

    for item in items:
        # Stage 1
        if check_excluded(item):
            log.debug("Stage 1 reject: %s", item.title)
            rejected.append(item)
            continue

        # Stage 2
        if item.link:
            log.debug("Fetching detail: %s", item.link)
            item.detail_html = fetch_detail(item.link, session)
            time.sleep(REQUEST_DELAY)

        if should_import(item):
            accepted.append(item)
        else:
            rejected.append(item)

    return accepted, rejected


# ─────────────────────────────────────────────────────────────────────────────
# RSS OUTPUT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_rss(accepted: list[FeedItem]) -> str:
    """Build a valid RSS 2.0 XML string from accepted items."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = (
        "WHO Geneva Professional/Director Vacancies (filtered by cinfo)"
    )
    ET.SubElement(channel, "link").text = (
        "https://cinfoposte.github.io/who-feed-filter/who_feed_filter.xml"
    )
    ET.SubElement(channel, "description").text = (
        "Filtered WHO job feed: Geneva-based positions at Professional "
        "and Director grade (P1-P6, D1-D2). Source: WHO Careers RSS."
    )
    ET.SubElement(channel, "lastBuildDate").text = (
        datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    )

    for item in accepted:
        item_el = ET.SubElement(channel, "item")
        ET.SubElement(item_el, "title").text = item.title
        ET.SubElement(item_el, "link").text = item.link
        if item.pub_date:
            ET.SubElement(item_el, "pubDate").text = item.pub_date
        ET.SubElement(item_el, "description").text = item.description
        guid = ET.SubElement(item_el, "guid")
        guid.set("isPermaLink", "true")
        guid.text = item.link

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    session = _make_session()

    # Step 1: warm session by visiting the career section (acquires cookies)
    _warm_session(session)

    # Step 2: fetch the RSS feed
    log.info("Fetching WHO RSS feed …")
    try:
        resp = session.get(FEED_URL, timeout=30)
        resp.raise_for_status()
        xml_source = resp.text
    except Exception as exc:
        log.error("Failed to fetch upstream feed: %s", exc)
        log.error("URL: %s", FEED_URL)
        return 1

    # Validate response is actually XML/RSS (Taleo sometimes returns HTML)
    content_type = resp.headers.get("Content-Type", "")
    log.info("Response: %d, Content-Type: %s, length: %d bytes",
             resp.status_code, content_type, len(xml_source))

    if not xml_source.strip():
        log.error("Upstream feed returned empty response")
        return 1

    # Check if we got HTML instead of RSS
    stripped = xml_source.strip()
    if stripped.lower().startswith("<!doctype") or stripped.lower().startswith("<html"):
        log.error("Upstream returned HTML instead of RSS (possible bot block or redirect)")
        log.error("First 500 chars: %s", stripped[:500])
        return 1

    try:
        ET.fromstring(xml_source)
    except ET.ParseError as exc:
        log.error("Upstream feed is not valid XML: %s", exc)
        log.error("First 500 chars: %s", xml_source[:500])
        return 1

    # Step 3: filter
    accepted, rejected = filter_feed(xml_source, session)

    # Print summary
    total = len(accepted) + len(rejected)
    print(f"\n{'='*60}")
    print(f"  WHO Feed Filter Summary")
    print(f"{'='*60}")
    print(f"  Total items:    {total}")
    print(f"  Accepted:       {len(accepted)}")
    print(f"  Rejected:       {len(rejected)}")
    print(f"{'='*60}")
    for item in accepted:
        print(f"  + [{item.grade_found}] {item.title}")
    print()

    # Step 4: write filtered RSS
    rss_output = build_rss(accepted)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(rss_output)

    log.info("Filtered feed written to %s (%d items)", OUTPUT_FILE, len(accepted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
