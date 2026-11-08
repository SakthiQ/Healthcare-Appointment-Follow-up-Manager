"""Runs the polling workers on background threads inside the web process.

The notification and calendar workers are plain `run_once(db)` pollers. In a
deployment with only one web service (the free-tier Render blueprint has no
separate worker process type) nothing would ever call them, so queued emails
and calendar syncs would sit PENDING forever. With RUN_WORKERS_IN_PROCESS=True
the FastAPI lifespan starts them here and stops them on shutdown.

Safe with more than one web instance: both workers claim rows with
`FOR UPDATE SKIP LOCKED` on PostgreSQL. A deployment that prefers separate
worker processes leaves the flag off and runs `python -m workers.<name>`.
"""
import logging
import threading
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SHUTDOWN_JOIN_TIMEOUT_SECONDS = 5.0


class WorkerRunner:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        workers: Dict[str, object],
        poll_interval_seconds: float,
    ):
        self._session_factory = session_factory
        self._workers = workers
        self._poll_interval = poll_interval_seconds
        self._stop = threading.Event()
        self._threads = []

    def start(self) -> None:
        for name, worker in self._workers.items():
            thread = threading.Thread(
                target=self._loop, args=(name, worker), name=f"worker-{name}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        logger.info(
            "Background workers started in-process: %s (poll_interval=%ss)",
            ", ".join(self._workers), self._poll_interval,
        )

    def stop(self, timeout: float = SHUTDOWN_JOIN_TIMEOUT_SECONDS) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()
        logger.info("Background workers stopped")

    def _loop(self, name: str, worker) -> None:
        # One session per iteration so a long-lived connection never goes stale
        # between polls, and a failed batch can't poison the next one.
        while not self._stop.is_set():
            db = self._session_factory()
            try:
                stats = worker.run_once(db)
                if stats and stats.get("claimed"):
                    logger.info("%s batch: %s", name, stats)
            except Exception:
                logger.exception("%s: unexpected error processing batch", name)
            finally:
                db.close()
            self._stop.wait(self._poll_interval)


def start_background_workers(
    poll_interval_seconds: Optional[float] = None,
) -> WorkerRunner:
    from app.config import settings
    from app.database import SessionLocal
    from workers.calendar_worker import calendar_worker
    from workers.hold_worker import hold_expiry_worker
    from workers.maintenance_worker import maintenance_worker
    from workers.notification_worker import notification_worker

    runner = WorkerRunner(
        session_factory=SessionLocal,
        workers={
            "NotificationWorker": notification_worker,
            "CalendarWorker": calendar_worker,
            "HoldExpiryWorker": hold_expiry_worker,
            "MaintenanceWorker": maintenance_worker,
        },
        poll_interval_seconds=(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.WORKER_POLL_INTERVAL_SECONDS
        ),
    )
    runner.start()
    return runner
