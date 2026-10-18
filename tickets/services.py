from django.db import transaction
from django.utils import timezone

from tickets.events import TicketEventField, record_event, tag_changes
from tickets.models import Ticket
from tickets.rules import validate_assignee, validate_status_transition, validate_tags

AUDITED_TEXT_FIELDS = (
    TicketEventField.PRIORITY,
    TicketEventField.TITLE,
    TicketEventField.DESCRIPTION,
)
MAX_EVENT_VALUE_LENGTH = 255


def _event_value(value):
    return str(value)[:MAX_EVENT_VALUE_LENGTH]


def create_ticket(actor, changes=None, **fields):
    data = dict(changes or {})
    data.update(fields)
    data.pop("status", None)
    assignee = data.get("assignee")
    tags = data.pop("tags", None)
    if tags is not None:
        tags = validate_tags(tags)
    else:
        tags = []

    with transaction.atomic():
        ticket = Ticket.objects.create(**data)
        if tags:
            ticket.tags.set(tags)
        record_event(
            ticket=ticket,
            actor=actor,
            field_changed=TicketEventField.CREATED,
            old_value="",
            new_value=ticket.status,
        )
        if assignee is not None:
            record_event(
                ticket=ticket,
                actor=actor,
                field_changed=TicketEventField.ASSIGNEE,
                old_value="",
                new_value=assignee.username,
            )
        for field_changed, old_value, new_value in tag_changes([], ticket.tags.all()):
            record_event(
                ticket=ticket,
                actor=actor,
                field_changed=field_changed,
                old_value=old_value,
                new_value=new_value,
            )
    return ticket


def update_ticket(ticket, actor, changes):
    data = dict(changes)
    tags = data.pop("tags", None)
    if "status" in data:
        validate_status_transition(ticket, data["status"])
    if "assignee" in data:
        validate_assignee(data["assignee"], ticket.assignee)
    if tags is not None:
        tags = validate_tags(tags)

    events = []
    if "status" in data and data["status"] != ticket.status:
        new_status = data["status"]
        events.append((TicketEventField.STATUS, ticket.status, new_status))
        if new_status in Ticket.FINISHED_STATUSES:
            if ticket.resolved_at is None:
                data["resolved_at"] = timezone.now()
        else:
            data["resolved_at"] = None
    if "assignee" in data and data["assignee"] != ticket.assignee:
        old_assignee = ticket.assignee.username if ticket.assignee else ""
        new_assignee = data["assignee"].username if data["assignee"] else ""
        events.append((TicketEventField.ASSIGNEE, old_assignee, new_assignee))
    for field in AUDITED_TEXT_FIELDS:
        if field in data and data[field] != getattr(ticket, field):
            events.append(
                (
                    field,
                    _event_value(getattr(ticket, field)),
                    _event_value(data[field]),
                )
            )
    if tags is not None:
        events.extend(tag_changes(ticket.tags.all(), tags))

    changed_fields = [attr for attr, value in data.items() if getattr(ticket, attr) != value]

    with transaction.atomic():
        for attr in changed_fields:
            setattr(ticket, attr, data[attr])
        ticket.save(update_fields=[*changed_fields, "updated_at"])
        if tags is not None:
            ticket.tags.set(tags)
        for field_changed, old_value, new_value in events:
            record_event(
                ticket=ticket,
                actor=actor,
                field_changed=field_changed,
                old_value=old_value,
                new_value=new_value,
            )
    return ticket


def delete_ticket(ticket, actor):
    with transaction.atomic():
        ticket.delete()
        record_event(
            ticket=ticket,
            actor=actor,
            field_changed=TicketEventField.DELETED,
            old_value="",
            new_value="",
        )
    return ticket


def restore_ticket(ticket, actor):
    if not ticket.is_deleted:
        return ticket
    with transaction.atomic():
        ticket.restore()
        record_event(
            ticket=ticket,
            actor=actor,
            field_changed=TicketEventField.RESTORED,
            old_value="",
            new_value="",
        )
    return ticket


def delete_tag(tag, actor):
    from tickets.tags import write_tag_delete_events

    with transaction.atomic():
        ticket_ids = list(
            Ticket.all_objects.filter(tags=tag).order_by("pk").values_list("pk", flat=True)
        )
        write_tag_delete_events(tag, ticket_ids, actor)
        tag.delete()
