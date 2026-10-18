from dataclasses import dataclass
from enum import StrEnum

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from chat.models import Visitor
from tickets.models import SenderType

SUPPORT_NAME = "Support"


class ParticipantKind(StrEnum):
    STAFF = "staff"
    CUSTOMER = "customer"
    VISITOR = "visitor"


@dataclass(frozen=True, slots=True)
class Participant:
    user: User | None = None
    visitor: Visitor | None = None

    def __post_init__(self):
        if (self.user is None) == (self.visitor is None):
            raise ValueError("A participant needs exactly one of user or visitor.")

    @classmethod
    def from_request(cls, request):
        if isinstance(request, dict):
            user = request.get("user")
            visitor = request.get("visitor")
        else:
            user = getattr(request, "user", None)
            visitor = getattr(request, "auth", None) or getattr(request, "visitor", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return cls(user=user)
        if isinstance(visitor, Visitor):
            return cls(visitor=visitor)
        raise ValueError("A request needs an authenticated user or a visitor.")

    @property
    def kind(self):
        if self.visitor is not None:
            return ParticipantKind.VISITOR
        if self.user.role in STAFF_ROLES:
            return ParticipantKind.STAFF
        return ParticipantKind.CUSTOMER

    @property
    def is_staff(self):
        return self.kind == ParticipantKind.STAFF

    @property
    def is_customer(self):
        return self.kind == ParticipantKind.CUSTOMER

    @property
    def is_visitor(self):
        return self.kind == ParticipantKind.VISITOR

    @property
    def sees_internal_notes(self):
        return self.is_staff

    @property
    def sender_type(self):
        if self.is_visitor:
            return SenderType.VISITOR
        if self.is_staff:
            return SenderType.AGENT
        return SenderType.CUSTOMER

    @property
    def socket_identity(self):
        if self.is_visitor:
            return f"visitor:{self.visitor.pk}"
        return f"user:{self.user.pk}"

    @property
    def reader_filter(self):
        if self.is_visitor:
            return {"visitor": self.visitor}
        return {"user": self.user}

    @property
    def read_filter(self):
        return self.reader_filter

    @property
    def ownership_filter(self):
        if self.is_visitor:
            return {"visitor": self.visitor}
        if self.is_customer:
            return {"customer": self.user}
        return {}

    @property
    def owner_filter(self):
        return self.ownership_filter

    @property
    def actor(self):
        return self.user

    @property
    def display_name(self):
        if self.is_visitor:
            return self.visitor.name
        return self.user.get_full_name() or (SUPPORT_NAME if self.is_staff else self.user.username)
