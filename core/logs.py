import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime

REDACTED = "[redacted]"

request_id_var = ContextVar("request_id", default=None)
user_id_var = ContextVar("user_id", default=None)

_STANDARD_ATTRIBUTES = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "request",
    "socket",
}

_SENSITIVE_KEY = re.compile(
    r"^(access|refresh)$|pass(word|wd)|secret|token|authorization|cookie|signature"
    r"|credential|api[_-]?key",
    re.IGNORECASE,
)

_SECRET_PARAM = (
    r"(?:token|password|passwd|secret|signature|credential|authorization|refresh|access"
    r"|api[_-]?key|ticket)"
)

_TEXT_PATTERNS = (
    (re.compile(r"(/api/downloads/)[^/\s?#]+"), rf"\g<1>{REDACTED}"),
    (re.compile(r"(bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), rf"\g<1>{REDACTED}"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), REDACTED),
    (
        re.compile(rf"([?&][^=&\s]*{_SECRET_PARAM}[^=&\s]*=)[^&\s]*", re.IGNORECASE),
        rf"\g<1>{REDACTED}",
    ),
)


def scrub(text):
    for pattern, replacement in _TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize(value):
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _SENSITIVE_KEY.search(str(key)) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRIBUTES or key in payload or key.startswith("_"):
                continue
            payload[key] = REDACTED if _SENSITIVE_KEY.search(key) else sanitize(value)
        if record.exc_info:
            payload["exception"] = scrub(self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = scrub(self.formatStack(record.stack_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
