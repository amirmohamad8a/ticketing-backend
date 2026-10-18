from rest_framework import serializers

from chat.models import Site, Visitor
from tickets.models import Ticket
from tickets.rules import validate_assignee, validate_status_transition, validate_tags
from tickets.services import create_ticket, update_ticket
from tickets.validators import MAX_BODY_LENGTH

STAFF_ONLY_RESPONSE_FIELDS = frozenset({"tags", "first_response_due_at", "visitor", "site"})


class TicketVisitorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Visitor
        fields = ["id", "name", "phone", "email"]
        read_only_fields = fields


class TicketSiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "name"]
        read_only_fields = fields


class TicketSerializer(serializers.ModelSerializer):
    visitor = TicketVisitorSerializer(read_only=True, allow_null=True)
    site = TicketSiteSerializer(read_only=True, allow_null=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "channel",
            "customer",
            "visitor",
            "site",
            "assignee",
            "tags",
            "first_response_due_at",
            "unread_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "channel",
            "customer",
            "first_response_due_at",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"description": {"max_length": MAX_BODY_LENGTH}}

    def get_unread_count(self, obj) -> int:
        return getattr(obj, "unread_count", 0)

    def validate_status(self, value):
        if self.instance is None:
            return value
        return validate_status_transition(self.instance, value)

    def validate_assignee(self, value):
        current = self.instance.assignee if self.instance is not None else None
        return validate_assignee(value, current)

    def validate_tags(self, value):
        return validate_tags(value)

    def _get_actor(self):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if actor is not None and not actor.is_authenticated:
            return None
        return actor

    def create(self, validated_data):
        return create_ticket(self._get_actor(), validated_data)

    def update(self, instance, validated_data):
        return update_ticket(instance, self._get_actor(), validated_data)


class CustomerTicketSerializer(TicketSerializer):
    class Meta(TicketSerializer.Meta):
        fields = [
            field
            for field in TicketSerializer.Meta.fields
            if field not in STAFF_ONLY_RESPONSE_FIELDS
        ]
        read_only_fields = [
            *TicketSerializer.Meta.read_only_fields,
            "status",
            "priority",
            "assignee",
        ]
