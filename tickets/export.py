import csv
import io

from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header

from asgiref.sync import sync_to_async

EXPORT_BATCH_SIZE = 500
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
UTF8_BOM = b"\xef\xbb\xbf"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _text(value):
    value = str(value)
    if value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _moment(value):
    if value is None:
        return ""
    return timezone.localtime(value).isoformat(timespec="seconds")


def _tag_names(ticket):
    return "; ".join(tag.name for tag in ticket.tags.all())


COLUMNS = (
    ("id", lambda ticket: ticket.pk),
    ("title", lambda ticket: _text(ticket.title)),
    ("status", lambda ticket: ticket.status),
    ("priority", lambda ticket: ticket.priority),
    ("channel", lambda ticket: ticket.channel),
    ("customer", lambda ticket: _text(ticket.customer.username) if ticket.customer_id else ""),
    ("visitor", lambda ticket: _text(ticket.visitor) if ticket.visitor_id else ""),
    ("assignee", lambda ticket: _text(ticket.assignee.username) if ticket.assignee_id else ""),
    ("tags", lambda ticket: _text(_tag_names(ticket))),
    ("created_at", lambda ticket: _moment(ticket.created_at)),
    ("first_response_due_at", lambda ticket: _moment(ticket.first_response_due_at)),
    ("first_response_at", lambda ticket: _moment(ticket.first_response_at)),
    ("resolved_at", lambda ticket: _moment(ticket.resolved_at)),
    ("updated_at", lambda ticket: _moment(ticket.updated_at)),
)

HEADER = [name for name, _getter in COLUMNS]


def _row(ticket):
    return [getter(ticket) for _name, getter in COLUMNS]


def _encode_rows(rows):
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _fetch_batch(queryset, before_id):
    if before_id is not None:
        queryset = queryset.filter(pk__lt=before_id)
    return list(queryset.order_by("-pk")[:EXPORT_BATCH_SIZE])


async def _stream(queryset):
    yield UTF8_BOM
    yield _encode_rows([HEADER])
    before_id = None
    while True:
        tickets = await sync_to_async(_fetch_batch)(queryset, before_id)
        if not tickets:
            break
        yield _encode_rows([_row(ticket) for ticket in tickets])
        if len(tickets) < EXPORT_BATCH_SIZE:
            break
        before_id = tickets[-1].pk


def build_export_response(queryset):
    queryset = queryset.select_related("customer", "visitor", "assignee").prefetch_related("tags")
    filename = f"tickets-{timezone.localtime():%Y%m%d-%H%M%S}.csv"
    response = StreamingHttpResponse(_stream(queryset), content_type=CSV_CONTENT_TYPE)
    response["Content-Disposition"] = content_disposition_header(True, filename)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
