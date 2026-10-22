"""Find a business's Facebook, Instagram and TikTok accounts, plus the email,
WhatsApp number and quality signals from its website.

Only uses sources the business published itself: the website listed on
Google Maps (which is sometimes the social profile) and links on their own
website. Social sites are never visited, so nothing here can get the Google
Maps scraper or any account blocked.
"""

import ipaddress
import logging
import random
import re
import socket
import time
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from app.extensions import db
from app.models import SocialPlatform, SocialProfile, SocialSource
from app.models.common import utcnow
from app.services import website_info

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8,en;q=0.7",
}
MAX_PAGE_BYTES = 2_000_000
MAX_REDIRECTS = 5
MAX_EXTRA_PAGES = 2

PLATFORM_HOSTS = {
    "facebook.com": SocialPlatform.FACEBOOK,
    "fb.com": SocialPlatform.FACEBOOK,
    "instagram.com": SocialPlatform.INSTAGRAM,
    "tiktok.com": SocialPlatform.TIKTOK,
}
HOST_PREFIXES = ("www.", "m.", "web.", "mbasic.", "business.", "ka-ge.", "en-gb.")

INSTAGRAM_HANDLE = re.compile(r"^[a-z0-9._]{1,30}$")
TIKTOK_HANDLE = re.compile(r"^[a-z0-9._]{2,24}$")
FACEBOOK_NAME = re.compile(r"^[a-z0-9.\-]{3,80}$")

INSTAGRAM_RESERVED = {
    "p", "reel", "reels", "explore", "accounts", "stories", "tv", "about", "developer", "legal", "direct", "web",
}
FACEBOOK_RESERVED = {
    "sharer", "sharer.php", "share", "share.php", "dialog", "plugins", "tr", "login", "login.php", "groups",
    "events", "watch", "photo", "photo.php", "photos", "permalink.php", "story.php", "hashtag", "help",
    "policies", "privacy", "legal", "business", "ads", "home.php", "marketplace", "gaming", "reel", "l.php",
    "media", "video.php", "profile", "people", "public", "search", "settings", "messages", "notes",
}
# Accounts that belong to website builders or the platforms themselves; they
# show up in templates and share buttons, not as the business's own page.
GENERIC_HANDLES = {
    "facebook", "instagram", "tiktok", "meta", "wix", "wixcom", "squarespace", "wordpress", "wordpressdotcom",
    "shopify", "godaddy", "elementor", "tilda", "tildapublishing", "weebly", "webflow", "hostinger",
    "envato", "themeforest", "google", "youtube", "zuck", "linktr.ee", "linktree", "taplink", "taplink.cc",
}

RAW_SOCIAL_URL = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?(?:facebook|fb|instagram|tiktok)\.com/[^\s\"'<>()\\]+", re.IGNORECASE
)
CONTACT_PAGE_HINT = re.compile(r"contact|about|kontakt|კონტაქტ|შესახებ", re.IGNORECASE)
# Tiny pages that only forward the visitor, e.g. <script>location.href='/ge/index'</script>.
CLIENT_REDIRECT = re.compile(
    r"""(?:location(?:\.href)?\s*=\s*|location\.replace\(\s*)["']([^"']+)["']"""
    r"""|http-equiv=["']?refresh["']?[^>]*?url=([^"'>\s]+)""",
    re.IGNORECASE,
)
CLIENT_REDIRECT_MAX_BYTES = 3000


@dataclass(frozen=True)
class SocialLink:
    platform: str
    url: str
    handle: str | None


def _platform_for_host(host):
    host = (host or "").lower()
    for prefix in HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    return PLATFORM_HOSTS.get(host)


def classify_social_url(url):
    """Return a normalized SocialLink when url points at a profile, else None."""
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    platform = _platform_for_host(parsed.hostname)
    if platform is None:
        return None
    segments = [s for s in parsed.path.lower().split("/") if s]
    if not segments:
        return None
    first = segments[0]

    if platform == SocialPlatform.INSTAGRAM:
        if first in INSTAGRAM_RESERVED or not INSTAGRAM_HANDLE.match(first) or first in GENERIC_HANDLES:
            return None
        return SocialLink(platform, f"https://www.instagram.com/{first}/", first)

    if platform == SocialPlatform.TIKTOK:
        handle = first[1:] if first.startswith("@") else None
        if not handle or not TIKTOK_HANDLE.match(handle) or handle in GENERIC_HANDLES:
            return None
        return SocialLink(platform, f"https://www.tiktok.com/@{handle}", handle)

    if first == "profile.php":
        profile_id = parse_qs(parsed.query).get("id", [""])[0]
        if not profile_id.isdigit():
            return None
        return SocialLink(platform, f"https://www.facebook.com/profile.php?id={profile_id}", None)
    if first in ("pg", "pages") and len(segments) > 1:
        first = segments[1]
    if first in FACEBOOK_RESERVED or not FACEBOOK_NAME.match(first) or first in GENERIC_HANDLES:
        return None
    return SocialLink(platform, f"https://www.facebook.com/{first}", first)


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []  # [href, text]
        self._current = None

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._current = [href.strip(), ""]
            self.anchors.append(self._current)

    def handle_data(self, data):
        if self._current is not None:
            self._current[1] += data

    def handle_endtag(self, tag):
        if tag == "a":
            self._current = None


def _anchors(html):
    parser = _AnchorParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup; use what was parsed
        pass
    return parser.anchors


def extract_social_links(html):
    """Pick the most likely profile per platform from a page's HTML.

    Real <a> links count double; URLs found elsewhere (scripts, JSON) are a
    fallback for sites that render their footer with JavaScript.
    """
    votes = Counter()
    for href, _ in _anchors(html):
        link = classify_social_url(href)
        if link:
            votes[link] += 2
    for raw in RAW_SOCIAL_URL.findall(html.replace("\\/", "/")):
        link = classify_social_url(raw)
        if link:
            votes[link] += 1

    best = {}
    for link, _ in votes.most_common():
        best.setdefault(link.platform, link)
    return best


def find_contact_pages(html, base_url, limit=MAX_EXTRA_PAGES):
    """Same-site Contact/About pages, where footers often list social links."""
    base = urlsplit(base_url)
    base_host = (base.hostname or "").removeprefix("www.")
    pages = []
    for href, text in _anchors(html):
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if not CONTACT_PAGE_HINT.search(f"{href} {text}"):
            continue
        url = urljoin(base_url, href).split("#")[0]
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").removeprefix("www.") != base_host:
            continue
        if parsed.path.rstrip("/") == base.path.rstrip("/") or url in pages:
            continue
        pages.append(url)
        if len(pages) >= limit:
            break
    return pages


def client_redirect_target(html, base_url):
    """Where a tiny JavaScript or meta-refresh redirect page sends the visitor."""
    if len(html) > CLIENT_REDIRECT_MAX_BYTES:
        return None
    match = CLIENT_REDIRECT.search(html)
    if not match:
        return None
    target = urljoin(base_url, (match.group(1) or match.group(2)).strip())
    return target if urlsplit(target).scheme in ("http", "https") and target != base_url else None


class PageFetchError(Exception):
    pass


def _check_public_host(host):
    """Refuse addresses on your own machine or network, even via redirects."""
    if not host:
        raise PageFetchError("Invalid website address")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise PageFetchError("Website not found (domain doesn't exist)") from None
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise PageFetchError("Website points to a private network address")


def fetch_page(client, url):
    """Download one HTML page. Returns (final_url, html); html is None when
    the site redirects to a social profile, which is never fetched."""
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https"):
            raise PageFetchError("Not a web address")
        if _platform_for_host(parsed.hostname):
            return url, None
        _check_public_host(parsed.hostname)
        try:
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if response.status_code >= 400:
                    raise PageFetchError(f"Website returned an error (HTTP {response.status_code})")
                content_type = response.headers.get("content-type", "")
                if content_type and "html" not in content_type:
                    raise PageFetchError("Website address isn't a web page")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) >= MAX_PAGE_BYTES:
                        break
                return str(response.url), body.decode(response.charset_encoding or "utf-8", errors="replace")
        except httpx.TimeoutException:
            raise PageFetchError("Website took too long to respond") from None
        except httpx.HTTPError as exc:
            raise PageFetchError(f"Couldn't open the website ({exc.__class__.__name__})") from None
    raise PageFetchError("Website redirects too many times")


@dataclass
class SocialCheck:
    links: dict = field(default_factory=dict)  # platform -> (SocialLink, source)
    pages_checked: int = 0
    error: str | None = None
    email: str | None = None
    whatsapp: str | None = None
    website: dict | None = None  # website_info.assess_website(), or {"error": ...}


class SocialFinder:
    """Checks one website at a time, pausing between page downloads."""

    def __init__(self, config):
        self.delay = config["SOCIAL_PAGE_DELAY"]
        self.phone_region = config["SCRAPER_PHONE_REGION"]
        self.client = httpx.Client(
            headers=BROWSER_HEADERS, timeout=config["SOCIAL_FETCH_TIMEOUT"], follow_redirects=False
        )
        self._fetched_before = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.client.close()

    def _fetch(self, url):
        low, high = self.delay
        if self._fetched_before and high > 0:
            time.sleep(random.uniform(low, high))
        self._fetched_before = True
        return fetch_page(self.client, url)

    def find(self, website):
        check = SocialCheck()
        if not website:
            return check

        listed = classify_social_url(website)
        if listed:
            check.links[listed.platform] = (listed, SocialSource.GOOGLE_MAPS)
            check.website = {"url": website, "social_only": listed.platform}
            return check

        started = time.monotonic()
        try:
            final_url, html = self._fetch(website)
            target = html and client_redirect_target(html, final_url)
            if target:
                final_url, html = self._fetch(target)
        except PageFetchError as exc:
            check.error = str(exc)
            check.website = {"url": website, "error": str(exc)}
            return check
        if html is None:
            redirected = classify_social_url(final_url)
            if redirected:
                check.links[redirected.platform] = (redirected, SocialSource.WEBSITE)
            check.website = {"url": final_url, "social_only": redirected.platform if redirected else None}
            return check

        check.website = website_info.assess_website(final_url, html, time.monotonic() - started)
        check.pages_checked = 1
        self._merge(check, html, final_url)
        for page_url in find_contact_pages(html, final_url):
            if len(check.links) == len(SocialPlatform.ALL) and check.email and check.whatsapp:
                break
            try:
                _, page_html = self._fetch(page_url)
            except PageFetchError:
                continue
            if page_html:
                check.pages_checked += 1
                self._merge(check, page_html, page_url)
        return check

    def _merge(self, check, html, url):
        for platform, link in extract_social_links(html).items():
            check.links.setdefault(platform, (link, SocialSource.WEBSITE))
        check.email = check.email or website_info.extract_email(html, url)
        check.whatsapp = check.whatsapp or website_info.extract_whatsapp(html, self.phone_region)


def save_social_check(business, check):
    """Store found profiles, contacts and the website check, and mark the
    business checked. Never overwrites an email or WhatsApp you entered.
    Caller commits. Returns how many profiles were added."""
    business.email = business.email or check.email
    business.whatsapp = business.whatsapp or check.whatsapp
    business.website_check = check.website
    has_real_site = check.website and "social_only" not in check.website
    business.website_issue_count = len(website_info.website_issues(check.website)) if has_real_site else None

    existing = {p.url for p in business.social_profiles}
    added = 0
    for link, source in check.links.values():
        if link.url in existing:
            continue
        business.social_profiles.append(
            SocialProfile(platform=link.platform, url=link.url, handle=link.handle, source=source)
        )
        added += 1
    business.social_checked_at = utcnow()
    return added


def find_for_business(business, config):
    """Run a lookup for one business right away. Caller commits."""
    with SocialFinder(config) as finder:
        check = finder.find(business.website)
    added = save_social_check(business, check)
    logger.info("Social lookup for business %s: %d added, error=%s", business.id, added, check.error)
    return added, check.error


def add_manual_profile(business, url):
    """Add a profile you entered. Raises ValueError when it isn't a profile link."""
    link = classify_social_url(url)
    if link is None:
        raise ValueError(
            "That doesn't look like a Facebook page, Instagram account or TikTok account link, "
            "e.g. https://www.instagram.com/yourbusiness"
        )
    if any(p.url == link.url for p in business.social_profiles):
        raise ValueError("This account is already saved for this business")
    profile = SocialProfile(platform=link.platform, url=link.url, handle=link.handle, source=SocialSource.MANUAL)
    business.social_profiles.append(profile)
    db.session.flush()
    return profile
