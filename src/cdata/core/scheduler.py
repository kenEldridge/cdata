"""APScheduler integration for scheduled fetching."""

import logging
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from cdata.config import get_settings, load_jobs
from cdata.config.schema import JobConfig, ScheduleType
from cdata.core.fetcher import Fetcher


logger = logging.getLogger(__name__)


class Scheduler:
    """Manages scheduled fetch jobs."""

    def __init__(self, daemon: bool = False):
        self.settings = get_settings()
        self.fetcher = Fetcher()
        self.daemon = daemon

        if daemon:
            self._scheduler = BackgroundScheduler(timezone=self.settings.scheduler_timezone)
        else:
            self._scheduler = BlockingScheduler(timezone=self.settings.scheduler_timezone)

    def _create_trigger(self, job: JobConfig):
        """Create an APScheduler trigger from job config."""
        if job.schedule is None:
            return None

        if job.schedule.type == ScheduleType.CRON:
            if job.schedule.expression:
                parts = job.schedule.expression.split()
                if len(parts) >= 5:
                    return CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4],
                    )
        elif job.schedule.type == ScheduleType.INTERVAL:
            kwargs = {}
            if job.schedule.seconds:
                kwargs["seconds"] = job.schedule.seconds
            if job.schedule.minutes:
                kwargs["minutes"] = job.schedule.minutes
            if job.schedule.hours:
                kwargs["hours"] = job.schedule.hours
            if kwargs:
                return IntervalTrigger(**kwargs)

        return None

    def _run_job(self, job_id: str) -> None:
        """Execute a job."""
        logger.info(f"Running job: {job_id}")
        try:
            result = self.fetcher.run_job(job_id)
            logger.info(f"Job {job_id} completed: {result.status.value}, {result.record_count} records")
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")

    def load_jobs(self) -> int:
        """Load and schedule all enabled jobs."""
        jobs = load_jobs()
        count = 0

        for job in jobs:
            if not job.enabled:
                continue

            trigger = self._create_trigger(job)
            if trigger is None:
                continue

            self._scheduler.add_job(
                self._run_job,
                trigger=trigger,
                args=[job.id],
                id=job.id,
                name=job.description or job.id,
                replace_existing=True,
            )
            count += 1
            logger.info(f"Scheduled job: {job.id}")

        return count

    def start(self) -> None:
        """Start the scheduler."""
        count = self.load_jobs()
        logger.info(f"Starting scheduler with {count} jobs")
        self._scheduler.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    def get_jobs(self) -> list[dict]:
        """Get information about scheduled jobs."""
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            })
        return jobs

    @property
    def running(self) -> bool:
        """Check if scheduler is running."""
        return self._scheduler.running
