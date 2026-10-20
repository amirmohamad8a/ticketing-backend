#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

ENV_FILE=".env"
EXAMPLE_FILE=".env.example"
OPTIONAL_KEYS='PYTHON_IMAGE|PIP_INDEX_URL|S3_[A-Z_]+|CORS_ALLOWED_ORIGINS|ADMIN_ALLOWED_IPS'

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

ask() {
    printf '%s [%s]: ' "$2" "$3"
    answer=""
    read -r answer || true
    [ -n "$answer" ] || answer="$3"
    eval "$1=\$answer"
}

yes_no() {
    ask yn_answer "$1" "$2"
    case "$yn_answer" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

random_hex() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

set_var() {
    SET_KEY="$1" SET_VALUE="$2" awk '
        BEGIN { key = ENVIRON["SET_KEY"]; value = ENVIRON["SET_VALUE"] }
        index($0, key "=") == 1 { print key "=" value; found = 1; next }
        { print }
        END { if (!found) print key "=" value }
    ' "$ENV_FILE" >"$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
}

get_var() {
    sed -n "s/^$1=//p" "$ENV_FILE" | head -n 1
}

render_env() {
    awk -v mode="$1" -v optional="^# ($OPTIONAL_KEYS)=" '
        /^# =+$/ { next }
        /^# DEVELOPMENT/ { section = "dev"; next }
        /^# PRODUCTION/ { section = "prod"; next }
        section == "prod" && /^# (Delete the DEVELOPMENT|replace each change-me)/ { next }
        section == "dev" && mode != "dev" { next }
        section == "prod" && mode != "prod" { next }
        section == "prod" && $0 ~ /^# [A-Z][A-Z0-9_]*=/ && $0 !~ optional { sub(/^# /, "") }
        { print }
    ' "$EXAMPLE_FILE"
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed. See https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is not available ('docker compose version' failed)."
docker info >/dev/null 2>&1 || die "The Docker daemon is not running."
say "Docker and Compose are available."

MODE="${1:-}"
if [ -z "$MODE" ] && [ ! -f "$ENV_FILE" ]; then
    ask MODE "Set up for dev or prod?" "dev"
fi

if [ -f "$ENV_FILE" ]; then
    say "$ENV_FILE already exists; leaving it untouched."
    case "$(get_var COMPOSE_FILE)" in
        *prod*) MODE=prod ;;
        *) MODE=dev ;;
    esac
else
    case "$MODE" in dev | prod) ;; *) die "mode must be 'dev' or 'prod'." ;; esac
    [ -f "$EXAMPLE_FILE" ] || die "$EXAMPLE_FILE not found."

    umask 077
    render_env "$MODE" >"$ENV_FILE"

    set_var SECRET_KEY "$(random_hex)"
    set_var JWT_SIGNING_KEY "$(random_hex)"
    set_var METRICS_TOKEN "$(random_hex)"

    if [ "$MODE" = prod ]; then
        db_user="$(get_var POSTGRES_USER)"
        db_name="$(get_var POSTGRES_DB)"
        db_password="$(random_hex)"
        set_var POSTGRES_PASSWORD "$db_password"
        set_var DATABASE_URL "postgres://$db_user:$db_password@db:5432/$db_name"

        domain=""
        while [ -z "$domain" ]; do
            ask domain "Public domain (for example support.example.com)" ""
            case "$domain" in
                *://* | */* | *' '*) say "Enter a bare host name, without a scheme or path."; domain="" ;;
            esac
        done
        set_var DOMAIN "$domain"
        ask admin_ips "IPs or CIDRs allowed to reach /admin/ (space-separated, empty blocks everyone)" ""
        [ -z "$admin_ips" ] || set_var ADMIN_ALLOWED_IPS "$admin_ips"
        set_var COMPOSE_FILE "docker-compose.yml:docker-compose.prod.yml"
    else
        set_var COMPOSE_FILE "docker-compose.yml:docker-compose.dev.yml"
    fi
    set_var COMPOSE_PATH_SEPARATOR ":"
    chmod 600 "$ENV_FILE"
    say "Wrote $ENV_FILE ($MODE) with generated secrets."
fi

docker compose config --quiet || die "docker compose config failed; check $ENV_FILE."

if yes_no "Build and start the stack now? (y/n)" "y"; then
    docker compose build
    docker compose up -d
    say "Stack started."

    if yes_no "Create the first admin user? (y/n)" "y"; then
        ask admin_username "Admin username" "admin"
        ask admin_email "Admin email" ""
        [ -n "$admin_email" ] || die "an email is required."
        printf 'Admin password: '
        stty -echo 2>/dev/null || true
        read -r admin_password || true
        stty echo 2>/dev/null || true
        printf '\n'
        [ -n "$admin_password" ] || die "a password is required."

        DJANGO_SUPERUSER_USERNAME="$admin_username" \
            DJANGO_SUPERUSER_EMAIL="$admin_email" \
            DJANGO_SUPERUSER_PASSWORD="$admin_password" \
            docker compose exec -T \
                -e DJANGO_SUPERUSER_USERNAME \
                -e DJANGO_SUPERUSER_EMAIL \
                -e DJANGO_SUPERUSER_PASSWORD \
                web python manage.py createsuperuser --noinput
        say "Admin '$admin_username' created."
    fi
else
    say "Skipped. Start later with: docker compose build && docker compose up -d"
fi

say "Done."
