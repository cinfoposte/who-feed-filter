#!/usr/bin/env python3
"""
WHO RSS Feed Scraper
====================
Downloads the official WHO careers RSS feed, filters it to Geneva-based
Professional/Director-grade positions (P1–P6, D1–D2), and writes the
result as a valid RSS 2.0 file for republication via GitHub Pages.

Uses the filter logic from who_feed_filter.py.
"""

import os
import sys
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from who_feed_filter import (
    FeedItem,
    check_excluded,
    check_grade,
    check_location,
    should_import,
    parse_feed,
    _make_session,
    REQUEST_DELAY,
    FETCH_DETAIL,
    HAS_REQUESTS,
    fetch_text,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_FEED_URL = (
    "https://careers.who.int/careersection/ex/jobsearch.ftl"
    "?lang=en&portal=101430233&searchtype=3"
    "&f=null&s=3|D&a=null&multiline=true&rss=true"
)

FEED_URL = os.environ.get("WHO_FEED_URL", DEFAULT_FEED_URL)
OUTPUT_FILE = "who_feed_filter.xml"

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


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
# TWO-STAGE FILTER
# ─────────────────────────────────────────────────────────────────────────────

def filter_feed(xml_source: str) -> tuple[list[FeedItem], list[FeedItem]]:
    """
    Parse the upstream feed and apply two-stage filtering.

    Stage 1: prefilter on title/description (reject obvious exclusions
             and items clearly missing grade or location signals).
    Stage 2: fetch detail page HTML for surviving items; confirm
             grade + location with stronger confidence.
    """
    items = parse_feed(xml_source)
    log.info("Parsed %d items from upstream feed", len(items))

    session = _make_session() if (FETCH_DETAIL and HAS_REQUESTS) else None
    accepted, rejected = [], []

    for item in items:
        # ── Stage 1: quick prefilter on title ────────────────────────────
        if check_excluded(item):
            log.debug("Stage 1 reject (excluded role): %s", item.title)
            rejected.append(item)
            continue

        # ── Stage 2: fetch detail page for richer parsing ────────────────
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
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    if not HAS_REQUESTS:
        log.error("requests library not found. Install with: pip install requests")
        return 1

    session = _make_session()

    log.info("Fetching WHO RSS feed from: %s", FEED_URL)
    try:
        resp = session.get(FEED_URL, timeout=30)
        resp.raise_for_status()
        xml_source = resp.text
    except Exception as exc:
        log.error("Failed to fetch upstream feed: %s", exc)
        return 1

    if not xml_source.strip():
        log.error("Upstream feed returned empty response")
        return 1

    try:
        ET.fromstring(xml_source)
    except ET.ParseError as exc:
        log.error("Upstream feed is not valid XML: %s", exc)
        return 1

    accepted, rejected = filter_feed(xml_source)

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

    # Write filtered RSS
    rss_output = build_rss(accepted)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(rss_output)

    log.info("Filtered feed written to %s (%d items)", OUTPUT_FILE, len(accepted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
