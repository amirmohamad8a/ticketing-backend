import http.client
import os
import sys

REQUEST_TIMEOUT_SECONDS = 5


def _host_header():
    allowed = os.environ.get("ALLOWED_HOSTS", "")
    for candidate in allowed.split(","):
        candidate = candidate.strip()
        if candidate:
            return candidate
    return "localhost"


def main():
    port = int(os.environ.get("PORT", "8000"))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        connection.request("GET", "/health/", headers={"Host": _host_header()})
        return 0 if connection.getresponse().status == 200 else 1
    except Exception:
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
