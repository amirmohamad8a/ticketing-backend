import factory

from accounts.models import User
from chat.models import Site, Visitor
from tickets.models import Attachment, Comment, ConversationRead, Ticket, TicketEvent


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda user: f"{user.username}@example.com")
    password = "pass12345"
    role = User.Role.CUSTOMER

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return model_class.objects.create_user(*args, **kwargs)


class AgentFactory(UserFactory):
    username = factory.Sequence(lambda n: f"agent{n}")
    role = User.Role.AGENT


class AdminFactory(UserFactory):
    username = factory.Sequence(lambda n: f"admin{n}")
    role = User.Role.ADMIN


class SiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Site

    name = factory.Sequence(lambda n: f"Site {n}")
    allowed_origins = factory.LazyFunction(lambda: ["https://example.com"])


class VisitorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Visitor

    site = factory.SubFactory(SiteFactory)
    name = factory.Sequence(lambda n: f"Visitor {n}")


class TicketFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Ticket

    class Params:
        from_visitor = factory.Trait(
            customer=None,
            visitor=factory.SubFactory(VisitorFactory),
            site=factory.SelfAttribute("visitor.site"),
            channel=Ticket.Channel.CHAT,
        )

    title = factory.Sequence(lambda n: f"Ticket {n}")
    description = "Ticket description"
    status = Ticket.Status.OPEN
    priority = Ticket.Priority.MEDIUM
    channel = Ticket.Channel.PORTAL
    customer = factory.SubFactory(UserFactory)
    visitor = None
    site = None
    assignee = None


class TicketEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TicketEvent

    ticket = factory.SubFactory(TicketFactory)
    actor = factory.SubFactory(AgentFactory)
    field_changed = "status"
    old_value = Ticket.Status.OPEN
    new_value = Ticket.Status.IN_PROGRESS


class CommentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Comment

    ticket = factory.SubFactory(TicketFactory)
    author = factory.SubFactory(UserFactory)
    body = factory.Sequence(lambda n: f"Comment {n}")
    is_internal = False


class AttachmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Attachment

    class Params:
        on_comment = factory.Trait(
            ticket=None,
            comment=factory.SubFactory(CommentFactory),
        )

    ticket = factory.SubFactory(TicketFactory)
    comment = None
    file = factory.django.FileField(filename="attachment.txt", data=b"hello world")
    original_name = "attachment.txt"
    uploaded_by = factory.SubFactory(UserFactory)
    size = factory.LazyAttribute(lambda attachment: attachment.file.size)
    content_type = "text/plain"


class ConversationReadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ConversationRead

    ticket = factory.SubFactory(TicketFactory)
    last_read_comment_id = 0
    user = factory.SubFactory(UserFactory)
    visitor = None

    class Params:
        for_visitor = factory.Trait(
            user=None,
            ticket=factory.SubFactory(TicketFactory, from_visitor=True),
            visitor=factory.SelfAttribute("ticket.visitor"),
        )
