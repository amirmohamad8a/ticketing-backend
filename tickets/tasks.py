from celery import shared_task

from tickets.lifecycle import close_due_tickets


@shared_task(name="tickets.auto_close_resolved", ignore_result=True)
def auto_close_resolved():
    return close_due_tickets()
