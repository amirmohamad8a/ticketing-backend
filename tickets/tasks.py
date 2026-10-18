import logging

from celery import shared_task

from core.orphans import find_orphan_files
from tickets.lifecycle import close_due_tickets

logger = logging.getLogger(__name__)


@shared_task(name="tickets.auto_close_resolved", ignore_result=True)
def auto_close_resolved():
    return close_due_tickets()


@shared_task(name="tickets.report_orphan_files", ignore_result=True)
def report_orphan_files():
    orphans = find_orphan_files()
    level = logging.WARNING if orphans else logging.INFO
    logger.log(
        level,
        "Orphan file report",
        extra={"count": len(orphans), "sample": orphans[:50]},
    )
    return len(orphans)
