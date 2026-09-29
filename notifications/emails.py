from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from accounts.models import User
from tickets.models import Ticket

TEMPLATE_NAMES = {
    "created": "created",
    "status": "status_changed",
    "assignee": "assignee_changed",
}


def _status_label(value):
    try:
        return Ticket.Status(value).label
    except ValueError:
        return value


def get_recipients(event):
    ticket = event.ticket
    field = event.field_changed
    if field == "created":
        candidates = [ticket.customer]
    elif field == "status":
        candidates = [ticket.customer, ticket.assignee]
    elif field == "assignee":
        candidates = [
            ticket.customer,
            User.objects.filter(username=event.new_value).first(),
        ]
    else:
        return []

    recipients = []
    seen = set()
    for user in candidates:
        if user is None or not user.email or user.email in seen:
            continue
        if field != "created" and event.actor_id == user.id:
            continue
        seen.add(user.email)
        recipients.append(user)
    return recipients


def _context(event, recipient):
    if event.field_changed in ("created", "status"):
        old_value = _status_label(event.old_value) if event.old_value else ""
        new_value = _status_label(event.new_value)
    else:
        old_value = event.old_value
        new_value = event.new_value
    actor = event.actor
    return {
        "event": event,
        "ticket": event.ticket,
        "recipient": recipient,
        "actor_name": actor.get_username() if actor else "Someone",
        "old_value": old_value,
        "new_value": new_value,
        "is_new_assignee": bool(event.new_value) and recipient.username == event.new_value,
    }


def build_messages(event):
    name = TEMPLATE_NAMES.get(event.field_changed)
    if name is None:
        return []
    messages = []
    for recipient in get_recipients(event):
        context = _context(event, recipient)
        subject = render_to_string(f"notifications/email/{name}_subject.txt", context)
        body = render_to_string(f"notifications/email/{name}.txt", context)
        messages.append(
            EmailMessage(subject=" ".join(subject.split()), body=body, to=[recipient.email])
        )
    return messages
