from tickets.models import TicketEvent


def record_event(ticket, actor, field_changed, old_value, new_value):
    return TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        field_changed=field_changed,
        old_value=old_value,
        new_value=new_value,
    )
