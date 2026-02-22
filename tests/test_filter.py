"""
Tests for the WHO RSS Feed Filter.
Uses the same test cases as the inline --test runner but in pytest format.
"""
import pytest
from who_feed_filter import (
    FeedItem,
    should_import,
    check_excluded,
    check_grade,
    check_location,
    parse_feed,
    build_filtered_rss,
    validate_rss_response,
    _EMPTY_RSS,
)


# ── Grade + Location acceptance tests ────────────────────────────────────────

@pytest.mark.parametrize("title, detail, label", [
    (
        "Health Officer (Tuberculosis), P4, Geneva",
        "Duty Station: Geneva, Switzerland. Grade: P4. Under the direction of ...",
        "Classic P4 Geneva title",
    ),
    (
        "Technical Officer (Digital Health), P-3, Geneva, Switzerland",
        "Location: Genève. This is a fixed-term appointment at the P-3 level.",
        "P-3 with hyphen, Genève variant",
    ),
    (
        "Communications Officer (P 2), WHO Headquarters, Geneva",
        "Place of assignment: Geneva. Grade P 2 (space variant).",
        "P 2 space variant",
    ),
    (
        "Director, Department of Health Systems (D-1), Geneva",
        "Duty station: CH-Geneva. Director level D-1 position.",
        "D-1 Director grade, CH-Geneva variant",
    ),
    (
        "Health Information Systems Officer, P5, Geneva",
        "Location: Geneva (Switzerland). Programme: Health Emergencies. Grade: P-5.",
        "P5 with parenthetical Switzerland variant",
    ),
])
def test_should_import_accepts(title, detail, label):
    item = FeedItem(title=title, description="", detail_html=detail)
    assert should_import(item) is True, f"Expected IMPORT for: {label} — got reason: {item.reason}"


# ── Rejection tests ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("title, detail, label", [
    (
        "Human Resources Associate, (GS-6), Fixed-Term, Damascus, Syria",
        "Duty Station: Damascus. General Service grade GS-6.",
        "GS-6 General Service, wrong location",
    ),
    (
        "Consultancy - Leadership Learning Design & Digital Content Specialist",
        "Location: Geneva. Consultancy contract.",
        "Consultant role even if Geneva",
    ),
    (
        "SSA - Project Officer – Solar Electrification, NOA",
        "Duty Station: Brazzaville. NOA grade.",
        "SSA + NOA, wrong location",
    ),
    (
        "Technical Officer (Behavioural Insights), P3",
        "The position is based in Copenhagen, Denmark. Grade P3.",
        "P3 but NOT Geneva",
    ),
    (
        "Intern – Global Health Policy, Geneva",
        "Internship programme. Duty station: Geneva.",
        "Intern title even if Geneva",
    ),
])
def test_should_import_rejects(title, detail, label):
    item = FeedItem(title=title, description="", detail_html=detail)
    assert should_import(item) is False, f"Expected REJECT for: {label}"


# ── Exclusion checks ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "SSA - Monitoring & Evaluation Officer",
    "Consultancy - Data Analyst",
    "Intern – Communications, Geneva",
    "JPO - Programme Officer, P2, Geneva",
    "National Officer (NOB), Manila",
    "Admin Assistant (GS-5), Geneva",
    "Driver (G-3), Geneva",
])
def test_excluded_roles(title):
    item = FeedItem(title=title)
    assert check_excluded(item) is True


@pytest.mark.parametrize("title", [
    "Health Officer (Tuberculosis), P4, Geneva",
    "Director, Department of Health Systems (D-1), Geneva",
    "Technical Officer (Digital Health), P-3, Geneva",
])
def test_non_excluded_roles(title):
    item = FeedItem(title=title)
    assert check_excluded(item) is False


# ── Grade detection ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("title, detail, expected_grade", [
    ("Officer, P4, Geneva", "Grade: P4.", "P4"),
    ("Officer, P-3, Geneva", "Grade: P-3.", "P3"),
    ("Officer (P 2)", "Grade P 2.", "P2"),
    ("Director (D-1)", "Grade: D-1.", "D1"),
    ("Officer, D2, Geneva", "Grade: D-2.", "D2"),
])
def test_grade_detection(title, detail, expected_grade):
    item = FeedItem(title=title, description="", detail_html=detail)
    assert check_grade(item) is True
    assert item.grade_found == expected_grade


def test_no_grade():
    item = FeedItem(title="Admin Support, Geneva", description="", detail_html="No grade info here.")
    assert check_grade(item) is False


# ── Location detection ───────────────────────────────────────────────────────

@pytest.mark.parametrize("title, detail", [
    ("Officer, P4, Geneva", "Duty Station: Geneva, Switzerland."),
    ("Officer, P4", "Location: Genève."),
    ("Officer, P4", "Duty station: CH-Geneva."),
    ("Officer, P4", "Location: Geneva (Switzerland)."),
    ("Officer, P4", "Based in: CH-1211 Geneva."),
    ("Officer, P4", "Place of assignment: Geneva."),
])
def test_location_geneva_variants(title, detail):
    item = FeedItem(title=title, description="", detail_html=detail)
    assert check_location(item) is True


def test_location_not_geneva():
    item = FeedItem(
        title="Officer, P4, Copenhagen",
        description="",
        detail_html="Duty Station: Copenhagen, Denmark.",
    )
    assert check_location(item) is False


# ── RSS parsing and building ─────────────────────────────────────────────────

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WHO Jobs</title>
    <link>https://careers.who.int</link>
    <item>
      <title>Health Officer, P4, Geneva</title>
      <link>https://careers.who.int/job/1</link>
      <description>A P4 role in Geneva.</description>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Admin Clerk, GS-4, Manila</title>
      <link>https://careers.who.int/job/2</link>
      <description>A GS role in Manila.</description>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>More Jobs Available on our site</title>
      <link>https://careers.who.int</link>
      <description></description>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


def test_parse_feed():
    items = parse_feed(SAMPLE_RSS)
    assert len(items) == 2  # "More Jobs Available" sentinel is skipped
    assert items[0].title == "Health Officer, P4, Geneva"
    assert items[1].title == "Admin Clerk, GS-4, Manila"


def test_build_filtered_rss():
    accepted = [FeedItem(link="https://careers.who.int/job/1")]
    rss = build_filtered_rss(SAMPLE_RSS, accepted)
    assert "Health Officer, P4, Geneva" in rss
    assert "Admin Clerk, GS-4, Manila" not in rss
    assert "More Jobs Available" not in rss


# ── Response validation tests ───────────────────────────────────────────────

def test_validate_rss_response_valid_xml():
    xml = '<?xml version="1.0"?><rss><channel></channel></rss>'
    assert validate_rss_response(xml) == xml


def test_validate_rss_response_rss_root():
    xml = '<rss version="2.0"><channel></channel></rss>'
    assert validate_rss_response(xml) == xml


def test_validate_rss_response_empty():
    with pytest.raises(ValueError, match="Empty response"):
        validate_rss_response("")


def test_validate_rss_response_whitespace():
    with pytest.raises(ValueError, match="Empty response"):
        validate_rss_response("   \n  ")


def test_validate_rss_response_html():
    html = "<html><head><title>Login</title></head><body>Please log in</body></html>"
    with pytest.raises(ValueError, match="HTML, not RSS"):
        validate_rss_response(html)


def test_validate_rss_response_doctype_html():
    html = "<!DOCTYPE html><html><body>Error</body></html>"
    with pytest.raises(ValueError, match="HTML, not RSS"):
        validate_rss_response(html)


# ── Graceful parse failure tests ────────────────────────────────────────────

def test_parse_feed_invalid_xml():
    """parse_feed should return empty list on invalid XML, not crash."""
    items = parse_feed("this is not xml at all")
    assert items == []


def test_parse_feed_html_response():
    """parse_feed should handle HTML gracefully."""
    html = "<html><body><p>Not an RSS feed</p></body></html>"
    items = parse_feed(html)
    assert items == []


def test_build_filtered_rss_invalid_xml():
    """build_filtered_rss should return empty RSS on invalid original XML."""
    rss = build_filtered_rss("not xml", [])
    assert "<?xml" in rss
    assert "<rss" in rss
