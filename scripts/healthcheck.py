"""Container health probe for the production image.

The probe talks to the app over the loopback address, but sends a `Host`
header taken from `ALLOWED_HOSTS`. That way `CommonMiddleware` accepts the
request even when `127.0.0.1` is not itself an allowed host.
"""

import os
import sys
import urllib.request

REQUEST_TIMEOUT_SECONDS = 5


def _host_header():
    allowed = os.environ.get("ALLOWED_HOSTS", "")
    for candidate in allowed.split(","):
        candidate = candidate.strip()
        if candidate:
            return candidate
    return "localhost"


def main():
    port = os.environ.get("PORT", "8000")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health/",
        headers={"Host": _host_header()},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
