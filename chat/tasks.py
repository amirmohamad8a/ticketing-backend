from celery import shared_task

from chat.offline import convert_due_chats, convert_unanswered_chat
from chat.retention import purge_stale_visitors


@shared_task(name="chat.convert_to_offline", ignore_result=True)
def convert_to_offline(ticket_id):
    return convert_unanswered_chat(ticket_id)


@shared_task(name="chat.sweep_unanswered_chats", ignore_result=True)
def sweep_unanswered_chats():
    return convert_due_chats()


@shared_task(name="chat.purge_stale_visitors", ignore_result=True)
def purge_visitors_without_tickets():
    return purge_stale_visitors()
