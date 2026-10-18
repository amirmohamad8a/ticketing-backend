from django.core.management import call_command

from celery import shared_task


@shared_task(name="accounts.flush_expired_tokens", ignore_result=True)
def flush_expired_tokens():
    call_command("flushexpiredtokens")
