import atexit
import logging
import queue
import threading
import time

from sqlalchemy import update

from app.extensions import db
from app.models import SearchJob, SearchJobStage, SearchJobStatus
from app.models.common import utcnow
from app.services import socials
from app.services.businesses import needs_online_check, upsert_business
from app.services.scrapers import SearchParams, get_scraper

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "Interrupted: the server stopped before this search finished"
SHUTDOWN_MESSAGE = "Stopped because the server shut down; results so far are saved"
SHUTDOWN_TIMEOUT = 10


class JobRunner:
    """Runs search jobs on background threads inside the Flask process.

    Each job commits after every business so progress is visible while it
    runs. Workers are daemon threads so Ctrl+C or a code reload never waits
    for a long search; on exit, running jobs are cancelled and given a few
    seconds to close their browser. Leftover jobs are marked failed on the
    first request after the next startup.
    """

    def __init__(self):
        self.app = None
        self._queue = queue.Queue()
        self._workers = []
        self._active = set()
        self._cancelled = set()
        self._lock = threading.Lock()
        self._recovered = False
        self._shutting_down = False
        self._atexit_registered = False

    def init_app(self, app):
        self.app = app
        self._shutting_down = False
        app.extensions["job_runner"] = self
        if app.config["JOB_RUNNER_RECOVER"]:
            app.before_request(self._recover_once)

    def _ensure_workers(self):
        with self._lock:
            self._workers = [w for w in self._workers if w.is_alive()]
            missing = self.app.config["JOB_RUNNER_WORKERS"] - len(self._workers)
            for _ in range(missing):
                worker = threading.Thread(
                    target=self._worker_loop, name=f"search-job-{len(self._workers)}", daemon=True
                )
                worker.start()
                self._workers.append(worker)
            if not self._atexit_registered:
                atexit.register(self.shutdown)
                self._atexit_registered = True

    def _worker_loop(self):
        while True:
            job_id = self._queue.get()
            try:
                self._run(job_id)
            finally:
                self._queue.task_done()

    def submit(self, job_id):
        if self.app.config["JOB_RUNNER_SYNC"]:
            self._run(job_id)
        else:
            self._ensure_workers()
            self._queue.put(job_id)

    def cancel(self, job_id):
        """Ask a running job to stop. Returns False if this runner isn't running it."""
        with self._lock:
            if job_id not in self._active:
                return False
            self._cancelled.add(job_id)
            return True

    def is_cancelled(self, job_id):
        with self._lock:
            return job_id in self._cancelled

    def shutdown(self, timeout=SHUTDOWN_TIMEOUT):
        """Cancel running jobs and wait briefly for them to save and close the browser."""
        with self._lock:
            self._shutting_down = True
            active = set(self._active)
            self._cancelled |= active
        if not active:
            return
        logger.info("Stopping %d running search(es) before exit", len(active))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._active:
                    return
            time.sleep(0.2)
        logger.warning("Search(es) %s did not stop in time", sorted(self._active))

    def recover_interrupted_jobs(self):
        result = db.session.execute(
            update(SearchJob)
            .where(SearchJob.status.in_([SearchJobStatus.PENDING, SearchJobStatus.RUNNING]))
            .values(status=SearchJobStatus.FAILED, error=INTERRUPTED_MESSAGE, finished_at=utcnow())
        )
        db.session.commit()
        if result.rowcount:
            logger.warning("Marked %d interrupted search job(s) as failed", result.rowcount)
        return result.rowcount

    def _recover_once(self):
        if self._recovered:
            return
        with self._lock:
            if self._recovered:
                return
            self._recovered = True
        self.recover_interrupted_jobs()

    def _run(self, job_id):
        with self._lock:
            if self._shutting_down:
                return
            self._active.add(job_id)
        with self.app.app_context():
            try:
                self._execute(job_id)
            except Exception as exc:
                logger.exception("Search job %s failed", job_id)
                db.session.rollback()
                job = db.session.get(SearchJob, job_id)
                if job is not None:
                    job.status = SearchJobStatus.FAILED
                    job.error = str(exc)[:2000] or exc.__class__.__name__
                    job.finished_at = utcnow()
                    db.session.commit()
            finally:
                db.session.remove()
                with self._lock:
                    self._active.discard(job_id)
                    self._cancelled.discard(job_id)

    def _execute(self, job_id):
        job = db.session.get(SearchJob, job_id)
        if job is None or job.status != SearchJobStatus.PENDING:
            return

        job.status = SearchJobStatus.RUNNING
        job.stage = SearchJobStage.MAPS
        job.started_at = utcnow()
        db.session.commit()
        logger.info("Search job %s started: %r near %s,%s", job.id, job.query, job.latitude, job.longitude)

        scraper = get_scraper(self.app.config["SCRAPER_PROVIDER"], self.app.config)
        params = SearchParams(
            query=job.query,
            latitude=job.latitude,
            longitude=job.longitude,
            radius_m=job.radius_m,
            max_results=job.max_results,
            language=self.app.config["SCRAPER_LANGUAGE"],
            collect_reviews=job.collect_reviews,
        )

        def should_stop():
            return self.is_cancelled(job_id)

        results = scraper.search(params, should_stop)
        try:
            for data in results:
                if should_stop():
                    break
                try:
                    _, created = upsert_business(data, job)
                except ValueError as exc:
                    logger.warning("Search job %s skipped a result: %s", job_id, exc)
                    db.session.rollback()
                    continue
                job.results_found += 1
                if created:
                    job.results_new += 1
                db.session.commit()
                if job.results_found >= job.max_results:
                    break
        finally:
            # Closing the generator runs the scraper's cleanup (e.g. closing the browser).
            close = getattr(results, "close", None)
            if close:
                close()

        if not job.results_found and scraper.stop_reason:
            job.error = scraper.stop_reason

        if job.find_socials and not should_stop():
            self._find_socials(job, should_stop)

        if should_stop():
            job.status = SearchJobStatus.CANCELLED
            if self._shutting_down:
                job.error = SHUTDOWN_MESSAGE
        else:
            job.status = SearchJobStatus.COMPLETED
        job.finished_at = utcnow()
        db.session.commit()
        logger.info(
            "Search job %s %s: %d found, %d new", job.id, job.status, job.results_found, job.results_new
        )

    def _find_socials(self, job, should_stop):
        """Second stage: check the websites of this search's businesses and look up
        their social accounts, skipping ones already checked. Runs after the browser has closed."""
        to_check = [b for b in job.businesses if needs_online_check(b)]
        job.stage = SearchJobStage.SOCIALS
        job.socials_total = len(to_check)
        db.session.commit()
        logger.info("Search job %s: looking up social media for %d businesses", job.id, len(to_check))

        with socials.SocialFinder(self.app.config) as finder:
            for business in to_check:
                if should_stop():
                    return
                try:
                    check = finder.find(business.website)
                except Exception:
                    logger.exception("Social lookup crashed for business %s", business.id)
                    check = socials.SocialCheck(error="Unexpected error")
                socials.save_social_check(business, check)
                job.socials_checked += 1
                if business.social_profiles:
                    job.socials_found += 1
                db.session.commit()
