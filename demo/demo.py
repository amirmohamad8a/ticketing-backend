import logging
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from django.utils.text import Truncator

from accounts.models import User
from chat.conversations import TITLE_MAX_LENGTH
from chat.models import Site, Visitor
from chat.offline import convert_unanswered_chat
from tickets.events import TicketEventField
from tickets.models import Attachment, CannedReply, Comment, Tag, Ticket, TicketEvent, TicketRating

logger = logging.getLogger(__name__)

CUSTOMER_USERNAME = "demo_customer"
AGENT_USERNAME = "demo_agent"
ADMIN_USERNAME = "demo_admin"
DEMO_USERNAMES = (CUSTOMER_USERNAME, AGENT_USERNAME, ADMIN_USERNAME)
DEMO_PASSWORD = "demo-ticketing-2026"

USER_PROFILES = {
    CUSTOMER_USERNAME: (User.Role.CUSTOMER, "علی", "رضایی"),
    AGENT_USERNAME: (User.Role.AGENT, "پریسا", "کریمی"),
    ADMIN_USERNAME: (User.Role.ADMIN, "سارا", "محمدی"),
}

SITE_KEY = "demo-store-widget-key"
SITE_NAME = "Demo Store"
SITE_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
SITE_GREETING = "سلام! برای شروع گفتگو پیام خود را بنویسید."

TAGS = (
    ("billing", Tag.Color.BLUE),
    ("bug", Tag.Color.RED),
    ("feature-request", Tag.Color.PURPLE),
    ("mobile", Tag.Color.TEAL),
    ("shipping", Tag.Color.ORANGE),
)
TAG_NAMES = tuple(name for name, _color in TAGS)

CANNED_REPLIES = (
    ("greeting", "خوش‌آمدگویی", "سلام، به پشتیبانی خوش آمدید. چطور می‌توانم کمکتان کنم؟"),
    ("checking", "در حال بررسی", "لطفاً چند لحظه صبر کنید، درخواست شما را بررسی می‌کنم."),
    (
        "need-info",
        "درخواست اطلاعات",
        "برای پیگیری بهتر، لطفاً شماره سفارش یا شماره موبایل خود را بفرستید.",
    ),
    (
        "refund-policy",
        "Refund policy",
        "Refunds are issued to the original payment method within 5 business days.",
    ),
    ("closing", "پایان گفتگو", "اگر سؤال دیگری دارید در خدمتیم. روز خوبی داشته باشید!"),
)
CANNED_SHORTCUTS = tuple(shortcut for shortcut, _title, _body in CANNED_REPLIES)

HISTORY_KINDS = frozenset({"assign", "status", "offline"})

PORTAL_TICKETS = (
    {
        "title": "Cannot log in on the mobile app",
        "description": "The app rejects my password on my phone, but it works on the website.",
        "priority": Ticket.Priority.HIGH,
        "age": timedelta(days=3, hours=2),
        "timeline": (
            (3, "message", "customer", "I tried reinstalling the app and it did not help."),
            (5, "assign", "agent"),
            (8, "tag", "bug"),
            (10, "tag", "mobile"),
            (20, "status", Ticket.Status.IN_PROGRESS),
            (25, "message", "agent", "Thanks. I am checking the login logs for your account."),
            (
                90,
                "message",
                "agent",
                "Stale session on the mobile client, not an account issue.",
                True,
            ),
        ),
    },
    {
        "title": "Invoice shows the wrong amount",
        "description": "My October invoice is higher than the price of my plan.",
        "priority": Ticket.Priority.MEDIUM,
        "age": timedelta(days=2),
        "timeline": (
            (10, "message", "customer", "Could someone confirm which plan I am being billed on?"),
            (15, "tag", "billing"),
        ),
    },
    {
        "title": "Report export fails for large ranges",
        "description": "Exporting a report for a full year fails with a server error.",
        "priority": Ticket.Priority.URGENT,
        "age": timedelta(days=1, hours=6),
        "timeline": (
            (1, "assign", "agent"),
            (5, "tag", "bug"),
            (15, "status", Ticket.Status.IN_PROGRESS),
            (30, "message", "agent", "Which date range were you exporting when it failed?"),
            (
                100,
                "message",
                "agent",
                "Exports over 90 days probably hit the request timeout.",
                True,
            ),
            (120, "status", Ticket.Status.WAITING_ON_CUSTOMER),
        ),
    },
    {
        "title": "Add a dark mode to the dashboard",
        "description": "Please add a dark theme to the dashboard for night shifts.",
        "priority": Ticket.Priority.LOW,
        "age": timedelta(days=6),
        "timeline": (
            (10, "assign", "agent"),
            (30, "status", Ticket.Status.IN_PROGRESS),
            (35, "tag", "feature-request"),
            (300, "message", "agent", "Dark mode is live. You can switch it on in your settings."),
            (330, "message", "customer", "Works great, thank you!"),
            (360, "status", Ticket.Status.RESOLVED),
            (400, "rating", 5, "Fast and exactly what I asked for."),
        ),
    },
    {
        "title": "Refund for a duplicate payment",
        "description": "I was charged twice for the same order and need one payment refunded.",
        "priority": Ticket.Priority.HIGH,
        "age": timedelta(days=9),
        "timeline": (
            (2, "message", "customer", "I can see two identical charges on my card statement."),
            (5, "assign", "agent"),
            (8, "tag", "billing"),
            (10, "status", Ticket.Status.IN_PROGRESS),
            (20, "message", "agent", "Both charges are visible. I am requesting the refund now."),
            (60, "message", "agent", "Finance approved the refund.", True),
            (150, "message", "customer", "Any update on the refund?"),
            (
                230,
                "message",
                "agent",
                "The refund was issued. It should reach you within 5 business days.",
            ),
            (240, "status", Ticket.Status.RESOLVED),
            (300, "rating", 4, "Solved, but the refund took a while."),
            (10320, "status", Ticket.Status.CLOSED),
        ),
    },
)

CHAT_TICKETS = (
    {
        "visitor": "سارا",
        "age": timedelta(minutes=12),
        "timeline": (
            (0, "message", "visitor", "سلام، سفارش من هنوز به دستم نرسیده. می‌توانید پیگیری کنید؟"),
            (1, "assign", None),
            (
                2,
                "message",
                "agent",
                "سلام، خوش آمدید. لطفاً شماره سفارش خود را بفرستید تا بررسی کنم.",
            ),
            (3, "status", Ticket.Status.IN_PROGRESS),
            (4, "message", "visitor", "شماره سفارش ۱۲۴۸۰ است."),
            (5, "tag", "shipping"),
            (
                7,
                "message",
                "agent",
                "ممنون. سفارش شما تحویل پست شده و تا دو روز کاری به دستتان می‌رسد.",
            ),
            (9, "message", "visitor", "عالی، ممنون. کد رهگیری را هم می‌توانید بدهید؟"),
        ),
    },
    {
        "visitor": "رضا",
        "phone": "09120000002",
        "age": timedelta(days=2, hours=3),
        "timeline": (
            (0, "message", "visitor", "سلام، می‌خواهم سفارشم را لغو کنم."),
            (1, "assign", None),
            (2, "status", Ticket.Status.IN_PROGRESS),
            (3, "message", "agent", "سلام، حتماً. سفارش شما هنوز ارسال نشده و همین حالا لغو شد."),
            (4, "tag", "billing"),
            (5, "message", "visitor", "ممنون. پول چه زمانی برمی‌گردد؟"),
            (8, "message", "agent", "مبلغ تا ۴۸ ساعت آینده به حساب شما برمی‌گردد."),
            (10, "message", "visitor", "ممنون از راهنمایی‌تان."),
            (12, "status", Ticket.Status.RESOLVED),
            (40, "rating", 5, "پاسخ سریع و کامل بود."),
        ),
    },
    {
        "visitor": "مینا",
        "age": timedelta(minutes=3),
        "timeline": ((0, "message", "visitor", "سلام، آیا امکان تعویض سایز کفش وجود دارد؟"),),
    },
    {
        "visitor": "نیما",
        "phone": "09120000003",
        "age": timedelta(days=1, hours=2),
        "timeline": (
            (0, "message", "visitor", "سلام، ساعت کاری پشتیبانی تلفنی چیست؟"),
            (1, "offline"),
        ),
    },
    {
        "visitor": "کیان",
        "email": "kian@example.com",
        "age": timedelta(days=4),
        "timeline": (
            (
                0,
                "message",
                "visitor",
                "سلام، فاکتور خرید خود را لازم دارم. چطور می‌توانم آن را دریافت کنم؟",
            ),
            (1, "offline"),
            (500, "assign", "agent"),
            (505, "status", Ticket.Status.IN_PROGRESS),
            (
                510,
                "message",
                "agent",
                "سلام، فاکتور شما به ایمیل‌تان ارسال شد. لطفاً صندوق ایمیل را بررسی کنید.",
            ),
            (640, "message", "visitor", "رسید، ممنون."),
            (650, "status", Ticket.Status.RESOLVED),
            (700, "rating", 3, "پاسخ دیر رسید اما مشکل حل شد."),
        ),
    },
)


def ensure_demo_allowed(force=False):
    if settings.DEBUG or force:
        return
    raise CommandError(
        "Demo data creates accounts with a known password and can only be used while DEBUG "
        "is true. Pass --force to override."
    )


@contextmanager
def _clock(moment):
    original = timezone.now
    timezone.now = lambda: moment
    try:
        yield
    finally:
        timezone.now = original


def _ensure_user(username):
    role, first_name, last_name = USER_PROFILES[username]
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"role": role, "email": "", "first_name": first_name, "last_name": last_name},
    )
    if created:
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
    return user


def _ensure_tag(name, color):
    tag = Tag.objects.filter(name__iexact=name).first()
    if tag is None:
        tag = Tag.objects.create(name=name, color=color)
    return tag


def _ensure_canned_replies():
    for shortcut, title, body in CANNED_REPLIES:
        CannedReply.objects.get_or_create(
            shortcut=shortcut, defaults={"title": title, "body": body}
        )


class DemoSeeder:
    def __init__(self, now):
        self.now = now
        self.customer = None
        self.agent = None
        self.senders = {}
        self.site = None
        self.tags = {}
        self.handlers = {
            "assign": self._assign,
            "status": self._set_status,
            "message": self._post_message,
            "tag": self._add_tag,
            "offline": self._convert,
            "rating": self._rate,
        }

    def run(self):
        users = {username: _ensure_user(username) for username in DEMO_USERNAMES}
        self.customer = users[CUSTOMER_USERNAME]
        self.agent = users[AGENT_USERNAME]
        self.senders = {"customer": self.customer, "agent": self.agent}
        self.site = self._ensure_site()
        self.tags = {name: _ensure_tag(name, color) for name, color in TAGS}
        _ensure_canned_replies()
        created = [self._seed_portal_ticket(spec) for spec in PORTAL_TICKETS]
        created += [self._seed_chat_ticket(spec) for spec in CHAT_TICKETS]
        return sum(created)

    def _ensure_site(self):
        site, _created = Site.objects.get_or_create(
            key=SITE_KEY,
            defaults={
                "name": SITE_NAME,
                "allowed_origins": list(SITE_ORIGINS),
                "greeting": SITE_GREETING,
                "primary_color": "#0f766e",
                "position": Site.Position.BOTTOM_LEFT,
                "offline_timeout_minutes": 2,
            },
        )
        return site

    def _seed_portal_ticket(self, spec):
        defaults = {"description": spec["description"], "priority": spec["priority"]}
        return self._seed_ticket(spec, {"customer": self.customer}, spec["title"], defaults)

    def _seed_chat_ticket(self, spec):
        timeline = sorted(spec["timeline"], key=lambda item: item[0])
        created_at = self.now - spec["age"]
        last_activity = created_at + timedelta(minutes=timeline[-1][0])
        first_body = next(item[3] for item in timeline if item[1] == "message")
        with _clock(created_at):
            visitor, _created = Visitor.objects.get_or_create(
                site=self.site,
                name=spec["visitor"],
                defaults={
                    "phone": spec.get("phone", ""),
                    "email": spec.get("email", ""),
                    "last_seen_at": last_activity,
                },
            )
        title = Truncator(" ".join(first_body.split())).chars(TITLE_MAX_LENGTH)
        defaults = {"description": "", "channel": Ticket.Channel.CHAT, "site": self.site}
        return self._seed_ticket(spec, {"visitor": visitor}, title, defaults)

    def _seed_ticket(self, spec, owner, title, defaults):
        created_at = self.now - spec["age"]
        with _clock(created_at):
            ticket, created = Ticket.all_objects.get_or_create(
                title=title, defaults=defaults, **owner
            )
        if not created and ticket.is_deleted:
            ticket.restore()
        for minutes, kind, *args in sorted(spec["timeline"], key=lambda item: item[0]):
            if not created and kind in HISTORY_KINDS:
                continue
            moment = min(ticket.created_at + timedelta(minutes=minutes), self.now)
            with _clock(moment):
                self.handlers[kind](ticket, *args)
        return created

    def _event(self, ticket, actor, field_changed, old_value, new_value):
        TicketEvent.objects.create(
            ticket=ticket,
            actor=actor,
            field_changed=field_changed,
            old_value=old_value,
            new_value=new_value,
        )

    def _assign(self, ticket, actor_key):
        ticket.assignee = self.agent
        ticket.save(update_fields=["assignee", "updated_at"])
        self._event(
            ticket,
            self.senders.get(actor_key),
            TicketEventField.ASSIGNEE,
            "",
            self.agent.username,
        )

    def _set_status(self, ticket, status):
        old_status = ticket.status
        ticket.status = status
        update_fields = ["status", "updated_at"]
        if status in Ticket.FINISHED_STATUSES:
            if ticket.resolved_at is None:
                ticket.resolved_at = timezone.now()
                update_fields.append("resolved_at")
        else:
            ticket.resolved_at = None
            update_fields.append("resolved_at")
        ticket.save(update_fields=update_fields)
        self._event(ticket, self.agent, TicketEventField.STATUS, old_status, status)

    def _post_message(self, ticket, sender, body, internal=False):
        author = self.senders.get(sender)
        visitor = ticket.visitor if sender == "visitor" else None
        comment, _created = Comment.objects.get_or_create(
            ticket=ticket,
            author=author,
            visitor=visitor,
            body=body,
            defaults={"is_internal": internal},
        )
        if sender == "agent" and not internal and ticket.first_response_at is None:
            ticket.first_response_at = comment.created_at
            ticket.save(update_fields=["first_response_at"])

    def _add_tag(self, ticket, name):
        tag = self.tags[name]
        if ticket.tags.filter(pk=tag.pk).exists():
            return
        ticket.tags.add(tag)
        self._event(ticket, self.agent, TicketEventField.TAG, "", tag.name)

    def _convert(self, ticket):
        convert_unanswered_chat(ticket.pk)

    def _rate(self, ticket, score, comment):
        if ticket.status in Ticket.FINISHED_STATUSES:
            TicketRating.objects.get_or_create(
                ticket=ticket, defaults={"score": score, "comment": comment}
            )


def _restore_user(user, files):
    role, first_name, last_name = USER_PROFILES[user.username]
    if user.avatar:
        files.append(user.avatar.name)
    user.role = role
    user.first_name = first_name
    user.last_name = last_name
    user.email = ""
    user.phone = None
    user.avatar = None
    user.is_active = True
    user.max_concurrent_chats = User.DEFAULT_MAX_CONCURRENT_CHATS
    user.last_chat_assigned_at = None
    user.set_password(DEMO_PASSWORD)
    user.save()


def _discard_files(names):
    for name in dict.fromkeys(names):
        if not name:
            continue
        try:
            default_storage.delete(name)
        except Exception:
            logger.warning("Could not delete a demo file", extra={"file_name": name}, exc_info=True)


def _demo_canned_reply_query():
    query = Q(pk__in=[])
    for shortcut, title, body in CANNED_REPLIES:
        query |= Q(shortcut=shortcut, title=title, body=body)
    return query


@transaction.atomic
def _purge():
    files = []
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.allow_audit_purge = 'on'")
    ticket_ids = list(
        Ticket.all_objects.filter(
            Q(customer__username__in=DEMO_USERNAMES)
            | Q(site__key=SITE_KEY)
            | Q(visitor__site__key=SITE_KEY)
        ).values_list("pk", flat=True)
    )
    if ticket_ids:
        files.extend(
            Attachment.objects.filter(
                Q(ticket_id__in=ticket_ids) | Q(comment__ticket_id__in=ticket_ids)
            ).values_list("file", flat=True)
        )
        QuerySet.delete(Ticket.all_objects.filter(pk__in=ticket_ids))
    Visitor.objects.filter(site__key=SITE_KEY).delete()
    Site.objects.filter(key=SITE_KEY).delete()
    CannedReply.objects.filter(_demo_canned_reply_query()).delete()
    unused_tag_ids = list(
        Tag.objects.annotate(ticket_total=Count("tickets"))
        .filter(name__in=TAG_NAMES, ticket_total=0)
        .values_list("pk", flat=True)
    )
    Tag.objects.filter(pk__in=unused_tag_ids).delete()
    for user in User.objects.filter(username__in=DEMO_USERNAMES):
        _restore_user(user, files)
    transaction.on_commit(lambda: _discard_files(files), robust=True)


@transaction.atomic
def seed_demo_data():
    return DemoSeeder(timezone.now()).run()


@transaction.atomic
def reset_demo_data():
    _purge()
    return seed_demo_data()
