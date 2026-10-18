from django.core.exceptions import ImproperlyConfigured

MIN_SECRET_LENGTH = 50
EXAMPLE_SECRET_MARKER = "change-me"
EXAMPLE_SECRET_PREFIX = "dev-"


def is_example_secret(value):
    lowered = value.lower()
    return EXAMPLE_SECRET_MARKER in lowered or lowered.startswith(EXAMPLE_SECRET_PREFIX)


def validate_jwt_signing_key(secret_key, jwt_signing_key):
    if jwt_signing_key == secret_key:
        raise ImproperlyConfigured("JWT_SIGNING_KEY must be different from SECRET_KEY.")


def validate_secret(name, value):
    if is_example_secret(value):
        raise ImproperlyConfigured(f"{name} is still an example value. Generate a real secret.")
    if len(value) < MIN_SECRET_LENGTH:
        raise ImproperlyConfigured(f"{name} must be at least {MIN_SECRET_LENGTH} characters long.")


def validate_secrets(**secrets):
    for name, value in secrets.items():
        validate_secret(name, value)


def validate_metrics_token(metrics_token):
    if metrics_token and is_example_secret(metrics_token):
        raise ImproperlyConfigured(
            "METRICS_TOKEN is still an example value. Generate a real secret."
        )


def resolve_num_proxies(raw, allow_zero_proxies, logger):
    if raw in (None, ""):
        raise ImproperlyConfigured(
            "NUM_PROXIES must be set explicitly in production. Use 0 only when clients reach "
            "the app directly and set ALLOW_ZERO_PROXIES=true to opt in."
        )
    try:
        num_proxies = int(raw)
    except (TypeError, ValueError):
        raise ImproperlyConfigured("NUM_PROXIES must be a whole number.")
    if num_proxies < 0:
        raise ImproperlyConfigured("NUM_PROXIES cannot be negative.")
    if num_proxies == 0:
        if not allow_zero_proxies:
            raise ImproperlyConfigured(
                "NUM_PROXIES is 0. Set it to the number of proxies in front of the app, or set "
                "ALLOW_ZERO_PROXIES=true when clients reach the app directly."
            )
        logger.warning(
            "NUM_PROXIES is 0. Behind a reverse proxy every client shares one throttle bucket "
            "and the client IP in the logs is the proxy address. Set NUM_PROXIES to the number "
            "of proxies in front of the app."
        )
    return num_proxies
