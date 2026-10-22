import os


def _bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Background jobs write while requests read; wait for SQLite locks instead of failing.
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}}
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    RESTX_MASK_SWAGGER = False
    RESTX_ERROR_404_HELP = False
    RESTX_JSON = {"ensure_ascii": False}

    GEOCODER_URL = os.getenv("GEOCODER_URL", "https://nominatim.openstreetmap.org")
    # Nominatim's usage policy requires an identifying User-Agent.
    GEOCODER_USER_AGENT = os.getenv("GEOCODER_USER_AGENT", "BusinessScraper/1.0 (local dashboard)")
    GEOCODER_COUNTRY_CODES = os.getenv("GEOCODER_COUNTRY_CODES", "ge")
    GEOCODER_LANGUAGE = os.getenv("GEOCODER_LANGUAGE", "ka,en")
    GEOCODER_TIMEOUT = 10

    SCRAPER_PROVIDER = os.getenv("SCRAPER_PROVIDER", "google_maps")
    SCRAPER_LANGUAGE = os.getenv("SCRAPER_LANGUAGE", "ka")
    FAKE_SCRAPER_DELAY = float(os.getenv("FAKE_SCRAPER_DELAY", "0.5"))

    # Google Maps browser scraping. Defaults favour looking like one patient
    # person over speed: a visible window, a persistent profile, slow pacing.
    SCRAPER_HEADLESS = _bool(os.getenv("SCRAPER_HEADLESS", "false"))
    SCRAPER_BROWSER_CHANNEL = os.getenv("SCRAPER_BROWSER_CHANNEL") or None  # e.g. "chrome" if installed
    SCRAPER_PROFILE_DIR = os.getenv("SCRAPER_PROFILE_DIR")  # defaults to instance/browser_profile
    SCRAPER_PHONE_REGION = os.getenv("SCRAPER_PHONE_REGION", "GE")
    SCRAPER_TIMEZONE = os.getenv("SCRAPER_TIMEZONE", "Asia/Tbilisi")
    SCRAPER_LOCALE = os.getenv("SCRAPER_LOCALE", "ka-GE")
    # Seconds a person might spend looking at one business before moving on.
    SCRAPER_PLACE_DELAY = (float(os.getenv("SCRAPER_PLACE_DELAY_MIN", "4")), float(os.getenv("SCRAPER_PLACE_DELAY_MAX", "9")))
    # Every N places, step away for a longer break.
    SCRAPER_BREAK_EVERY = (12, 20)
    SCRAPER_BREAK_SECONDS = (25, 70)
    # Minimum gap between two searches, and a daily ceiling on places opened.
    SCRAPER_SEARCH_COOLDOWN = int(os.getenv("SCRAPER_SEARCH_COOLDOWN", "90"))
    SCRAPER_DAILY_PLACE_LIMIT = int(os.getenv("SCRAPER_DAILY_PLACE_LIMIT", "300"))
    # On a CAPTCHA: wait this long for you to solve it in the window, then back off for hours.
    SCRAPER_CAPTCHA_WAIT = int(os.getenv("SCRAPER_CAPTCHA_WAIT", "300"))
    SCRAPER_BLOCK_BACKOFF_HOURS = float(os.getenv("SCRAPER_BLOCK_BACKOFF_HOURS", "6"))

    # Social media lookup reads businesses' own websites (never Google or the social sites).
    SOCIAL_PAGE_DELAY = (float(os.getenv("SOCIAL_PAGE_DELAY_MIN", "1.5")), float(os.getenv("SOCIAL_PAGE_DELAY_MAX", "4")))
    SOCIAL_FETCH_TIMEOUT = float(os.getenv("SOCIAL_FETCH_TIMEOUT", "8"))

    # Sending email from your Gmail. The address and App Password are entered on
    # the Settings page and stored in MAIL_SETTINGS_FILE (defaults to instance/mail_settings.json).
    MAIL_SETTINGS_FILE = os.getenv("MAIL_SETTINGS_FILE")
    MAIL_SMTP_HOST = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com")
    MAIL_SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "465"))
    MAIL_SMTP_TIMEOUT = 20

    JOB_RUNNER_WORKERS = int(os.getenv("JOB_RUNNER_WORKERS", "1"))
    JOB_RUNNER_SYNC = False
    JOB_RUNNER_RECOVER = True

    SEARCH_RADIUS_RANGE = (100, 50_000)
    SEARCH_MAX_RESULTS_RANGE = (1, 200)


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SCRAPER_PROVIDER = "fake"
    FAKE_SCRAPER_DELAY = 0
    SOCIAL_PAGE_DELAY = (0, 0)
    JOB_RUNNER_SYNC = True
    JOB_RUNNER_RECOVER = False


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
