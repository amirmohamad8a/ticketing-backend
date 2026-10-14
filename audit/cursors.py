import base64
import json
from datetime import datetime

TICKET_KIND = "ticket"
USER_KIND = "user"
KINDS = (TICKET_KIND, USER_KIND)
MAX_ID = 2**63 - 1


class InvalidCursor(Exception):
    pass


def encode_cursor(created_at, kind, row_id):
    payload = [created_at.isoformat(), kind, row_id]
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(value):
    try:
        payload = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
        if not (isinstance(payload, list) and len(payload) == 3):
            raise InvalidCursor
        moment, kind, row_id = payload
        if not isinstance(moment, str) or kind not in KINDS:
            raise InvalidCursor
        if not isinstance(row_id, int) or isinstance(row_id, bool) or not 1 <= row_id <= MAX_ID:
            raise InvalidCursor
        created_at = datetime.fromisoformat(moment)
    except (ValueError, RecursionError):
        raise InvalidCursor from None
    if created_at.tzinfo is None:
        raise InvalidCursor
    return created_at, kind, row_id
