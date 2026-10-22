import logging
import math
import re
from datetime import date, timedelta
from urllib.parse import quote, unquote

import phonenumbers
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.services.scrapers.base import BaseScraper
from app.services.scrapers.human import Human
from app.services.scrapers.pacing import ScraperBlockedError, ScraperLimitError, ScraperState

logger = logging.getLogger(__name__)

MAPS_URL = "https://www.google.com/maps"
VIEWPORT = {"width": 1366, "height": 768}
# Width of the map area beside the results panel at this viewport.
MAP_AREA_PX = 950

FEED = 'div[role="feed"]'
SEARCH_BOX = "input#searchboxinput, input[name='q']"
PLACE_TITLE = "h1.DUwDvf"

PLACE_ID_RE = re.compile(r"!19s([^!?&/]+)")
FEATURE_ID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.IGNORECASE)
COORDS_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
RATING_RE = re.compile(r"(\d+[.,]\d)")
PARENS_RE = re.compile(r"\(([^)]*)\)")
PLAIN_NUMBER_RE = re.compile(r"[\d\s\u00a0\u202f.,]+")

# Stop scrolling after this many consecutive results outside the radius,
# or this many scrolls that load nothing new.
OUT_OF_RADIUS_STREAK_LIMIT = 20
# Before anything inside the circle turns up, Google's relevance ordering may
# list far-away places first, so keep looking longer.
OUT_OF_RADIUS_STREAK_LIMIT_BEFORE_FIRST = 60
VIEWPORT_RE = re.compile(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+(?:\.\d+)?)z")
STALE_SCROLL_LIMIT = 4
# Consecutive businesses whose details can't be read before assuming the layout changed.
FAILED_PLACE_STREAK_LIMIT = 5

def browser_launch_message(exc):
    text = str(exc)
    if "Executable doesn't exist" in text or "is not found at" in text:
        return (
            "The browser used for searching isn't installed (or was removed by a Playwright update). "
            "In the project folder run: .venv/bin/playwright install chromium, then start the search again."
        )
    if "Missing X server" in text or "$DISPLAY" in text:
        return "Couldn't open the browser window: no desktop display is available to this server."
    if "ProcessSingleton" in text or ("profile" in text.lower() and "in use" in text.lower()):
        return "The browser profile is already open in another window. Close that Chromium window and try again."
    return f"Couldn't open the browser: {text.splitlines()[0][:300]}"


COLLECT_LINKS_JS = """() => {
  const feed = document.querySelector('div[role="feed"]');
  if (!feed) return [];
  window.__bsNextKey = window.__bsNextKey || 0;
  return [...feed.querySelectorAll('a.hfpxzc[href*="/maps/place/"]')].map(a => {
    if (!a.dataset.bsKey) a.dataset.bsKey = String(window.__bsNextKey++);
    return {key: a.dataset.bsKey, href: a.href, label: a.getAttribute('aria-label') || ''};
  });
}"""

MARK_PANELS_SEEN_JS = "() => document.querySelectorAll('h1.DUwDvf').forEach(h => h.dataset.bsSeen = '1')"

NEW_PANEL_READY_JS = """(label) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  return [...document.querySelectorAll('h1.DUwDvf')]
    .some(h => !h.dataset.bsSeen && norm(h.innerText) === norm(label));
}"""

EXTRACT_PLACE_JS = """() => {
  const titles = [...document.querySelectorAll('h1.DUwDvf')];
  const h1 = titles.filter(h => !h.dataset.bsSeen).pop() || titles.pop();
  if (!h1) return null;
  const main = h1.closest('div[role="main"]') || document;
  const one = sel => main.querySelector(sel);
  const label = el => el ? (el.getAttribute('aria-label') || el.innerText || '').trim() : null;
  const phone = one('[data-item-id^="phone:tel:"]');
  const rating = one('div.F7nice');
  return {
    name: h1.innerText.trim(),
    category: one('button.DkEaL')?.innerText.trim() || null,
    address: label(one('button[data-item-id="address"]')),
    phone: phone ? phone.getAttribute('data-item-id').slice('phone:tel:'.length) : null,
    website: one('a[data-item-id="authority"]')?.href || null,
    rating_text: rating ? rating.innerText : null,
    rating_labels: rating ? [...rating.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label')) : [],
    hours: [...main.querySelectorAll('table.eK4R0e tr')].map(tr => {
      const td = tr.querySelectorAll('td');
      return td.length >= 2 ? [td[0].innerText.trim(), (td[1].getAttribute('aria-label') || td[1].innerText).trim()] : null;
    }).filter(Boolean),
    unclaimed: !!one('[data-item-id="merchant"]'),
    price_level: [...main.querySelectorAll('span')].slice(0, 200).map(s => s.innerText.trim())
      .find(t => /^(₾{1,4}|\\${1,4}|€{1,4}|₾\\s?\\d+\\s?[–-]\\s?\\d+|₾\\s?\\d+\\+)$/.test(t)) || null,
  };
}"""

REVIEWS_TAB = 'button[role="tab"][aria-label$="მიმოხილვები"], button[role="tab"][aria-label^="Reviews"]'
REVIEWS_SORT = 'button[aria-label="ყველაზე შესაბამისი"], button[aria-label="Most relevant"]'
REVIEWS_TO_READ = 5  # Google shows this many before the list is scrolled

READ_REVIEWS_JS = """(limit) => {
  const titles = [...document.querySelectorAll('h1.DUwDvf')];
  const h1 = titles.filter(h => !h.dataset.bsSeen).pop() || titles.pop();
  const main = (h1 && h1.closest('div[role="main"]')) || document;
  return [...main.querySelectorAll('div.jftiEf')].slice(0, limit).map(r => ({
    date: (r.querySelector('.rsqaWe') || {}).innerText || null,
    owner: !!r.querySelector('.CDe7pd'),
  }));
}"""

BLOCK_CHECK_JS = """() => !!document.querySelector(
  'iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"], form#captcha-form, #captcha-form, div#recaptcha'
)"""


def parse_place_link(href):
    """Pull place id and coordinates out of a Maps place URL."""
    if not href:
        return None
    place_match = PLACE_ID_RE.search(href)
    feature_match = FEATURE_ID_RE.search(href)
    place_id = unquote(place_match.group(1)) if place_match else (feature_match.group(1) if feature_match else None)
    if not place_id:
        return None
    coords = COORDS_RE.search(href)
    return {
        "place_id": place_id,
        "latitude": float(coords.group(1)) if coords else None,
        "longitude": float(coords.group(2)) if coords else None,
        "maps_url": href.split("?", 1)[0],
    }


def parse_rating(text, labels=()):
    """'4,8\\n(2 617)' -> (4.8, 2617). Falls back to aria-labels for abbreviated counts."""
    rating = reviews = None
    if text:
        match = RATING_RE.search(text)
        if match:
            rating = float(match.group(1).replace(",", "."))
        parens = PARENS_RE.search(text)
        if parens and PLAIN_NUMBER_RE.fullmatch(parens.group(1).strip()):
            digits = re.sub(r"\D", "", parens.group(1))
            reviews = int(digits) if digits else None
    if reviews is None:
        for label in list(labels)[1:]:
            digits = re.sub(r"\D", "", label or "")
            if digits:
                reviews = int(digits)
                break
    return rating, reviews


def strip_label(value):
    """'მისამართი: 7 დოქის შესახვევი' -> '7 დოქის შესახვევი'."""
    if not value:
        return None
    value = value.split(": ", 1)[1] if ": " in value else value
    return value.strip() or None


def normalize_phone(raw, region="GE"):
    if not raw:
        return None
    raw = raw.strip()
    try:
        number = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return raw
    if not phonenumbers.is_valid_number(number):
        return raw
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def distance_m(lat1, lng1, lat2, lng2):
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def format_distance(meters):
    return f"{meters / 1000:.1f} km" if meters >= 1000 else f"{meters:.0f} m"


def zoom_for_radius(radius_m, latitude):
    """Map zoom whose visible width roughly covers the search circle."""
    meters_per_px = (2 * radius_m) / MAP_AREA_PX
    zoom = math.log2(156_543.03 * math.cos(math.radians(latitude)) / meters_per_px)
    return max(11, min(18, math.floor(zoom)))


def build_business(details, link, phone_region):
    rating, reviews = parse_rating(details.get("rating_text"), details.get("rating_labels") or ())
    hours = {day: value for day, value in details.get("hours") or [] if day}
    return {
        "place_id": link["place_id"],
        "name": details.get("name") or None,
        "category": details.get("category"),
        "address": strip_label(details.get("address")),
        "latitude": link.get("latitude"),
        "longitude": link.get("longitude"),
        "phone": normalize_phone(details.get("phone"), phone_region),
        "website": details.get("website"),
        "rating": rating,
        "review_count": reviews,
        "opening_hours": hours or None,
        "maps_url": link.get("maps_url"),
        "claimed": not details.get("unclaimed", False),
        "price_level": details.get("price_level"),
        **(details.get("reviews_summary") or {}),
    }


RELATIVE_KA = re.compile(r"(\d+|ერთი)\s+(წუთის|საათის|დღის|კვირის|თვის|წლის)\s+წინ")
RELATIVE_EN = re.compile(r"(\d+|an?)\s+(minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE)
UNIT_DAYS = {
    "წუთის": 0, "საათის": 0, "დღის": 1, "კვირის": 7, "თვის": 30, "წლის": 365,
    "minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365,
}


def parse_relative_date(text, today=None):
    """'3 კვირის წინ' / 'a month ago' -> an approximate date."""
    if not text:
        return None
    today = today or date.today()
    match = RELATIVE_KA.search(text) or RELATIVE_EN.search(text)
    if match:
        amount = 1 if not match.group(1).isdigit() else int(match.group(1))
        return today - timedelta(days=amount * UNIT_DAYS[match.group(2).lower()])
    lowered = text.lower()
    if "გუშინ" in lowered or "yesterday" in lowered:
        return today - timedelta(days=1)
    if any(word in lowered for word in ("ახლახან", "დღეს", "just now", "today")):
        return today
    return None


def summarize_reviews(reviews, today=None):
    """Latest review date and owner replies among the newest reviews read."""
    dates = [d for d in (parse_relative_date(r.get("date"), today) for r in reviews) if d]
    return {
        "latest_review_date": max(dates) if dates else None,
        "recent_reviews_checked": len(reviews),
        "recent_owner_replies": sum(1 for r in reviews if r.get("owner")),
    }


class GoogleMapsScraper(BaseScraper):
    """Searches Google Maps in a real, visible browser at a person's pace.

    One persistent browser profile is reused so Google sees a returning
    visitor. Results outside the radius are skipped without being opened.
    """

    name = "google_maps"

    def search(self, params, should_stop):
        cfg = self.config
        state = ScraperState(cfg["SCRAPER_STATE_FILE"])

        blocked_until = state.blocked_until()
        if blocked_until:
            raise ScraperBlockedError(
                f"Google Maps showed a CAPTCHA earlier; scraping is paused until "
                f"{blocked_until.astimezone().strftime('%Y-%m-%d %H:%M')}"
            )
        if state.places_today() >= cfg["SCRAPER_DAILY_PLACE_LIMIT"]:
            raise ScraperLimitError(
                f"Daily limit of {cfg['SCRAPER_DAILY_PLACE_LIMIT']} places reached; try again tomorrow"
            )

        wait = state.seconds_until_next_search(cfg["SCRAPER_SEARCH_COOLDOWN"])
        if wait:
            logger.info("Waiting %.0fs before the next Google Maps search", wait)
            if not Human(None, should_stop).pause(wait):
                return

        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    cfg["SCRAPER_PROFILE_DIR"],
                    channel=cfg["SCRAPER_BROWSER_CHANNEL"],
                    headless=cfg["SCRAPER_HEADLESS"],
                    viewport=VIEWPORT,
                    locale=cfg["SCRAPER_LOCALE"],
                    timezone_id=cfg["SCRAPER_TIMEZONE"],
                    geolocation={"latitude": params.latitude, "longitude": params.longitude},
                    permissions=["geolocation"],
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                )
            except PlaywrightError as exc:
                raise RuntimeError(browser_launch_message(exc)) from exc
            # Only a search that actually opened the browser counts toward the cooldown.
            state.record_search_started()
            try:
                page = context.pages[0] if context.pages else context.new_page()
                yield from self._search_page(page, params, should_stop, state)
            except PlaywrightError as exc:
                if "closed" in str(exc).lower():
                    raise RuntimeError(
                        "The browser window was closed during the search; results so far are saved"
                    ) from exc
                raise
            finally:
                try:
                    context.close()
                except PlaywrightError:
                    pass

    def _search_page(self, page, params, should_stop, state):
        cfg = self.config
        human = Human(page, should_stop)
        self._open_search(page, human, params)
        if should_stop():
            return

        if page.locator(FEED).count() == 0:
            # A query with a single match opens that place directly.
            link = parse_place_link(page.url)
            details = page.evaluate(EXTRACT_PLACE_JS)
            if link and details and details.get("name"):
                state.add_place()
                yield build_business(details, link, cfg["SCRAPER_PHONE_REGION"])
            return

        self._log_viewport(page, params)
        feed = page.locator(FEED)
        seen = set()
        skipped_distances = []
        opened = yielded = 0
        next_break = human.rng.randint(*cfg["SCRAPER_BREAK_EVERY"])
        out_of_radius_streak = stale_scrolls = failed_streak = 0

        def note_far_results(why):
            if skipped_distances:
                ordered = sorted(skipped_distances)
                logger.info(
                    "%s. Skipped %d results outside %dm: closest %.0fm, median %.0fm",
                    why, len(ordered), params.radius_m, ordered[0], ordered[len(ordered) // 2],
                )
            if not opened and skipped_distances:
                self.stop_reason = (
                    f"Google listed {len(skipped_distances)} places for this search, but none inside the "
                    f"{format_distance(params.radius_m)} circle (the closest was "
                    f"{format_distance(min(skipped_distances))} away). Try a bigger circle or move the pin."
                )

        while not should_stop():
            links = page.evaluate(COLLECT_LINKS_JS)
            fresh = [link for link in links if link["key"] not in seen]

            for link in fresh:
                seen.add(link["key"])
                parsed = parse_place_link(link["href"])
                if not parsed:
                    continue
                distance = (
                    distance_m(params.latitude, params.longitude, parsed["latitude"], parsed["longitude"])
                    if parsed["latitude"] is not None
                    else None
                )
                if distance is not None and distance > params.radius_m:
                    out_of_radius_streak += 1
                    skipped_distances.append(distance)
                    continue
                out_of_radius_streak = 0

                if state.places_today() >= cfg["SCRAPER_DAILY_PLACE_LIMIT"]:
                    raise ScraperLimitError(
                        f"Daily limit of {cfg['SCRAPER_DAILY_PLACE_LIMIT']} places reached; "
                        "results so far are saved"
                    )

                details = self._open_place(page, human, link)
                state.add_place()
                opened += 1
                if details and details.get("name"):
                    failed_streak = 0
                    if params.collect_reviews:
                        details["reviews_summary"] = self._read_reviews(page, human)
                    yield build_business(details, parsed, cfg["SCRAPER_PHONE_REGION"])
                    yielded += 1
                    if yielded >= params.max_results:
                        return
                else:
                    failed_streak += 1
                    if failed_streak >= FAILED_PLACE_STREAK_LIMIT:
                        raise RuntimeError(
                            f"Couldn't read {failed_streak} businesses in a row. Google Maps may have "
                            "changed its page layout; results so far are saved"
                        )
                if not human.pause(*cfg["SCRAPER_PLACE_DELAY"]):
                    return
                if opened >= next_break:
                    logger.info("Taking a short break after %d places", opened)
                    if not human.pause(*cfg["SCRAPER_BREAK_SECONDS"]):
                        return
                    next_break = opened + human.rng.randint(*cfg["SCRAPER_BREAK_EVERY"])

            if self._end_of_list(page):
                note_far_results("Reached the end of the results list")
                return
            streak_limit = OUT_OF_RADIUS_STREAK_LIMIT if opened else OUT_OF_RADIUS_STREAK_LIMIT_BEFORE_FIRST
            if out_of_radius_streak >= streak_limit:
                note_far_results(f"Results have moved outside the {params.radius_m}m radius; stopping")
                return

            before = len(links)
            human.scroll(feed)
            if not human.pause(1.0, 2.5):
                return
            self._check_block(page, human)
            if len(page.evaluate(COLLECT_LINKS_JS)) > before:
                stale_scrolls = 0
            else:
                stale_scrolls += 1
                if stale_scrolls >= STALE_SCROLL_LIMIT:
                    note_far_results("No more results are loading")
                    return

    def _log_viewport(self, page, params):
        """Record where Google actually centred the map, to spot searches of the wrong area."""
        offset = self._viewport_offset(page, params)
        if offset is None:
            return
        log = logger.warning if offset > max(2 * params.radius_m, 1000) else logger.info
        log("Google Maps results are centred %.0fm from the search point", offset)

    def _open_search(self, page, human, params):
        lang = params.language
        zoom = zoom_for_radius(params.radius_m, params.latitude)
        page.goto(f"{MAPS_URL}/@{params.latitude},{params.longitude},{zoom}z?hl={lang}", wait_until="domcontentloaded")
        human.pause(2.5, 4.5)
        self._handle_consent(page, human)
        self._check_block(page, human)

        box = page.locator(SEARCH_BOX).first
        try:
            box.wait_for(state="visible", timeout=15000)
            human.click(box)
            human.pause(0.4, 1.0)
            page.keyboard.press("Control+A")
            human.type(params.query)
            human.pause(0.4, 1.1)
            page.keyboard.press("Enter")
        except Exception:
            logger.info("Search box not found; opening the search URL instead")
            page.goto(
                f"{MAPS_URL}/search/{quote(params.query)}/@{params.latitude},{params.longitude},{zoom}z?hl={lang}",
                wait_until="domcontentloaded",
            )

        self._wait_for_results(page, human)

        # Typing a search lets Google re-centre the map on wherever it thinks the
        # results are; the search URL keeps it on the pin.
        offset = self._viewport_offset(page, params)
        if offset is not None and offset > max(params.radius_m, 800):
            logger.info("Google moved the map %.0fm away from the pin; reopening the search there", offset)
            human.pause(1.5, 3.0)
            page.goto(
                f"{MAPS_URL}/search/{quote(params.query)}/@{params.latitude},{params.longitude},{zoom}z?hl={lang}",
                wait_until="domcontentloaded",
            )
            self._wait_for_results(page, human)

    def _wait_for_results(self, page, human):
        try:
            page.wait_for_selector(f"{FEED}, {PLACE_TITLE}", timeout=25000)
        except Exception:
            self._check_block(page, human)
            raise RuntimeError("Google Maps did not show any results for this search") from None
        human.pause(2.0, 4.0)

    @staticmethod
    def _viewport_offset(page, params):
        match = VIEWPORT_RE.search(page.url)
        if not match:
            return None
        return distance_m(params.latitude, params.longitude, float(match.group(1)), float(match.group(2)))

    def _open_place(self, page, human, link):
        anchor = page.locator(f'{FEED} a[data-bs-key="{link["key"]}"]')
        if anchor.count() == 0:
            return None
        page.evaluate(MARK_PANELS_SEEN_JS)
        for attempt in (1, 2):
            human.click(anchor)
            try:
                page.wait_for_function(NEW_PANEL_READY_JS, arg=link["label"], timeout=15000)
                break
            except PlaywrightTimeoutError:
                self._check_block(page, human)
                if attempt == 2:
                    logger.warning("Details for %r did not load after a retry; skipping", link["label"])
                    return None
                logger.info("Details for %r did not load; retrying once", link["label"])
                if not human.pause(2.0, 4.0):
                    return None
        human.pause(1.5, 3.0)
        self._check_block(page, human)
        human.glance(page.locator(PLACE_TITLE).last)
        return page.evaluate(EXTRACT_PLACE_JS)

    def _read_reviews(self, page, human):
        """Open the Reviews tab, sort by newest and read the first few. Never fails the place."""
        try:
            panel = page.locator('div[role="main"]').filter(
                has=page.locator(f"{PLACE_TITLE}:not([data-bs-seen])")
            ).last
            tab = panel.locator(REVIEWS_TAB)
            if tab.count() == 0:
                return {"recent_reviews_checked": 0}
            human.click(tab.first)
            if not human.pause(1.5, 3.0):
                return {}
            # Google renders the sort button outside the place panel.
            sort = page.locator(REVIEWS_SORT).filter(visible=True)
            if sort.count():
                human.click(sort.last)
                human.pause(0.6, 1.4)
                options = page.locator('div[role="menuitemradio"]')
                if options.count() > 1:
                    human.click(options.nth(1))  # order: most relevant, newest, highest, lowest
                    human.pause(1.8, 3.2)
            else:
                logger.info("Reviews sort button not found; reading them in Google's default order")
            self._check_block(page, human)
            return summarize_reviews(page.evaluate(READ_REVIEWS_JS, REVIEWS_TO_READ))
        except ScraperBlockedError:
            raise
        except Exception as exc:
            logger.info("Couldn't read reviews: %s", str(exc).splitlines()[0][:200])
            return {}

    def _end_of_list(self, page):
        return page.evaluate("() => !!document.querySelector('div[role=\"feed\"] span.HlvSq')")

    def _handle_consent(self, page, human):
        if "consent." not in page.url:
            return
        logger.info("Answering Google's cookie consent page")
        buttons = page.locator('form[action*="consent"] button')
        target = None
        for i in range(buttons.count()):
            text = (buttons.nth(i).inner_text() or "").lower()
            if "reject" in text or "უარ" in text:
                target = buttons.nth(i)
                break
        target = target or (buttons.first if buttons.count() else None)
        if target is None:
            return
        human.click(target)
        page.wait_for_url(re.compile(r"google\.[^/]+/maps"), timeout=20000)
        human.pause(2, 4)

    def _is_blocked(self, page):
        if "/sorry/" in page.url:
            return True
        try:
            return page.evaluate(BLOCK_CHECK_JS)
        except Exception:
            return False

    def _check_block(self, page, human):
        if not self._is_blocked(page):
            return
        cfg = self.config
        state = ScraperState(cfg["SCRAPER_STATE_FILE"])

        if not cfg["SCRAPER_HEADLESS"]:
            logger.warning(
                "Google is asking for a CAPTCHA. Solve it in the browser window within %ds to continue.",
                cfg["SCRAPER_CAPTCHA_WAIT"],
            )
            waited = 0
            while waited < cfg["SCRAPER_CAPTCHA_WAIT"]:
                if not human.pause(3):
                    return
                waited += 3
                if not self._is_blocked(page):
                    logger.info("CAPTCHA cleared; continuing slowly")
                    human.pause(5, 10)
                    return

        until = state.mark_blocked(cfg["SCRAPER_BLOCK_BACKOFF_HOURS"])
        raise ScraperBlockedError(
            "Google Maps showed a CAPTCHA. Scraping is paused until "
            f"{until.astimezone().strftime('%Y-%m-%d %H:%M')}; results so far are saved"
        )
