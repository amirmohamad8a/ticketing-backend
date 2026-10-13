from celery import shared_task

from chat.offline import convert_unanswered_chat


@shared_task(name="chat.convert_to_offline", ignore_result=True)
def convert_to_offline(ticket_id):
    return convert_unanswered_chat(ticket_id)
