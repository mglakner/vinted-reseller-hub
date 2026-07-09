import logging
import traceback
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from ..db import session_scope
from ..models import JobRun

log = logging.getLogger("vintedhub.jobs")

scheduler = BackgroundScheduler(timezone="Europe/Copenhagen")


def run_logged(job_name: str, fn) -> None:
    with session_scope() as session:
        run = JobRun(job_name=job_name)
        session.add(run)
        session.commit()
        run_id = run.id
    try:
        message = fn() or "OK"
        ok = True
    except Exception as exc:  # noqa: BLE001 — jobs må aldrig vælte scheduleren
        message = f"{exc}\n{traceback.format_exc(limit=3)}"
        ok = False
        log.exception("Job %s fejlede", job_name)
    with session_scope() as session:
        run = session.get(JobRun, run_id)
        run.finished_at = datetime.now()
        run.ok = ok
        run.message = message[:2000]
        session.add(run)
        session.commit()


def start_scheduler() -> None:
    from . import gmail_sync, image_gen, vinted_sync, weekly_report

    scheduler.add_job(
        lambda: run_logged("gmail_sync", gmail_sync.sync),
        "interval", minutes=15, id="gmail_sync",
    )
    scheduler.add_job(
        lambda: run_logged("vinted_sync", vinted_sync.sync),
        "cron", hour="9,20", minute=17, id="vinted_sync",
    )
    scheduler.add_job(
        lambda: run_logged("image_gen", image_gen.process_queue),
        "interval", minutes=2, id="image_gen",
    )
    scheduler.add_job(
        lambda: run_logged("weekly_report", weekly_report.send),
        "cron", day_of_week="mon", hour=8, minute=0, id="weekly_report",
    )
    scheduler.start()
