from django.db import transaction

from chat.models import Visitor
from tickets.events import CONTACT_FIELD, record_event


def save_contact(ticket, phone="", email=""):
    with transaction.atomic():
        visitor = Visitor.objects.select_for_update().get(pk=ticket.visitor_id)
        changed = []
        if phone and phone != visitor.phone:
            visitor.phone = phone
            changed.append("phone")
        if email and email != visitor.email:
            visitor.email = email
            changed.append("email")
        if changed:
            visitor.save(update_fields=changed)
            record_event(
                ticket=ticket,
                actor=None,
                field_changed=CONTACT_FIELD,
                old_value="",
                new_value=", ".join(changed),
            )
    return visitor
