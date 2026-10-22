"""Contact details and quality signals read from a business's own website."""

import html as html_lib
import re
from collections import Counter
from datetime import date
from urllib.parse import unquote, urlsplit

import phonenumbers

EMAIL_RE = re.compile(r"[a-z0-9][a-z0-9._%+-]{0,63}@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24}", re.IGNORECASE)
MAILTO_RE = re.compile(r"""href\s*=\s*["']mailto:([^"'?]+)""", re.IGNORECASE)
EMAIL_JUNK_DOMAINS = {
    "example.com", "example.ge", "domain.com", "email.com", "yourdomain.com", "mysite.com", "company.com",
    "sentry.io", "wixpress.com", "sentry-next.wixpress.com", "godaddy.com", "test.com",
}
RECRUITING_LOCAL_RE = re.compile(r"(?:jobs?|careers?|hr|cv|vacanc(?:y|ies)|resume)[._-]?\d*@", re.IGNORECASE)
EMAIL_JUNK_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".ico")

WHATSAPP_RE = re.compile(
    r"(?:wa\.me/|whatsapp\.com/send/?\?(?:[^\"'<>\s]*?&(?:amp;)?)?phone=|whatsapp://send/?\?(?:[^\"'<>\s]*?&(?:amp;)?)?phone=)"
    r"(?:%2B|\+)?(\d{8,15})",
    re.IGNORECASE,
)

VIEWPORT_META_RE = re.compile(r"""<meta[^>]+name\s*=\s*["']?viewport["']?[^>]*>""", re.IGNORECASE)
GENERATOR_META_RE = re.compile(
    r"""<meta[^>]+name\s*=\s*["']generator["'][^>]*content\s*=\s*["']([^"']+)"""
    r"""|<meta[^>]+content\s*=\s*["']([^"']+)["'][^>]*name\s*=\s*["']generator["']""",
    re.IGNORECASE,
)
COPYRIGHT_RE = re.compile(r"(?:©|\(c\)|copyright)\s*(?:(?:19|20)\d{2}\s*[-–—]\s*)?((?:19|20)\d{2})", re.IGNORECASE)
TAG_RE = re.compile(r"<script\b.*?</script>|<style\b.*?</style>|<[^>]+>", re.IGNORECASE | re.DOTALL)
BUILDER_HINTS = (
    ("Wix", "static.wixstatic.com"),
    ("Tilda", "tildacdn"),
    ("WordPress", "/wp-content/"),
    ("Squarespace", "squarespace.com"),
    ("Shopify", "cdn.shopify.com"),
    ("Webflow", "webflow.com"),
)

SLOW_SECONDS = 4
OUTDATED_AFTER_YEARS = 2


def _host(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _plausible_email(address):
    local, _, domain = address.partition("@")
    if not local or domain in EMAIL_JUNK_DOMAINS or address.endswith(EMAIL_JUNK_SUFFIXES):
        return False
    return not re.search(r"@\dx\.|^u00[0-9a-f]{2}", address)


def extract_email(page_html, site_url):
    """The most likely contact email: mailto links first, then addresses in the
    page; ones on the site's own domain win ties."""
    cleaned = page_html.replace("\\u0040", "@").replace("\\u003e", " ").replace("\\u003c", " ")
    cleaned = html_lib.unescape(cleaned)
    votes = Counter()
    for raw in MAILTO_RE.findall(cleaned):
        votes[unquote(raw).strip().lower()] += 3
    for raw in EMAIL_RE.findall(cleaned):
        votes[raw.lower()] += 1
    site_host = _host(site_url)
    candidates = [a for a in votes if _plausible_email(a) and EMAIL_RE.fullmatch(a)]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda a: (
            not RECRUITING_LOCAL_RE.match(a),
            a.partition("@")[2].endswith(site_host) if site_host else False,
            votes[a],
        ),
    )


def extract_whatsapp(page_html, region="GE"):
    """A WhatsApp number from wa.me / api.whatsapp.com links, formatted like +995 555 12 34 56."""
    for digits in WHATSAPP_RE.findall(page_html):
        try:
            number = phonenumbers.parse(f"+{digits}", region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(number):
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    return None


def assess_website(final_url, page_html, load_seconds):
    viewport = VIEWPORT_META_RE.search(page_html)
    text = TAG_RE.sub(" ", page_html)
    years = [int(y) for y in COPYRIGHT_RE.findall(html_lib.unescape(text))]
    generator = GENERATOR_META_RE.search(page_html)
    builder = None
    if generator:
        builder = (generator.group(1) or generator.group(2)).split(" ")[0].strip()[:40] or None
    if not builder:
        builder = next((name for name, hint in BUILDER_HINTS if hint in page_html), None)
    return {
        "url": final_url,
        "https": final_url.lower().startswith("https://"),
        "mobile_friendly": bool(viewport and "width=device-width" in viewport.group(0).lower()),
        "load_seconds": round(load_seconds, 1),
        "copyright_year": max(years) if years else None,
        "builder": builder,
        "error": None,
    }


def website_issues(check, today=None):
    """Plain-language problems worth mentioning on a call."""
    if not check or "social_only" in check:
        return []
    if check.get("error"):
        return [f"Website doesn't open: {check['error']}"]
    issues = []
    if not check.get("https"):
        issues.append("No HTTPS: browsers mark it 'Not secure'")
    if check.get("mobile_friendly") is False:
        issues.append("Not mobile-friendly")
    year = check.get("copyright_year")
    if year and year <= (today or date.today()).year - OUTDATED_AFTER_YEARS:
        issues.append(f"Looks outdated (© {year})")
    seconds = check.get("load_seconds")
    if seconds and seconds > SLOW_SECONDS:
        issues.append(f"Slow to load ({seconds} s)")
    return issues
