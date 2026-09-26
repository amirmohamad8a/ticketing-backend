from django.db import transaction

from rest_framework import serializers

from tickets.models import Ticket, TicketEvent


class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "customer",
            "assignee",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer", "created_at", "updated_at"]

    def validate_status(self, value):
        if self.instance is None:
            return value
        current_status = self.instance.status
        if value == current_status:
            return value
        allowed = Ticket.STATUS_TRANSITIONS.get(current_status, set())
        if value not in allowed:
            raise serializers.ValidationError(
                f"Cannot transition status from '{current_status}' to '{value}'."
            )
        return value

    def update(self, instance, validated_data):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if actor is not None and not actor.is_authenticated:
            actor = None

        changes = []
        if "status" in validated_data and validated_data["status"] != instance.status:
            changes.append(("status", instance.status, validated_data["status"]))
        if "assignee" in validated_data and validated_data["assignee"] != instance.assignee:
            old_assignee = instance.assignee.username if instance.assignee else ""
            new_assignee = validated_data["assignee"].username if validated_data["assignee"] else ""
            changes.append(("assignee", old_assignee, new_assignee))

        with transaction.atomic():
            instance = super().update(instance, validated_data)
            for field_changed, old_value, new_value in changes:
                TicketEvent.objects.create(
                    ticket=instance,
                    actor=actor,
                    field_changed=field_changed,
                    old_value=old_value,
                    new_value=new_value,
                )

        return instance


class TicketEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketEvent
        fields = [
            "id",
            "ticket",
            "actor",
            "field_changed",
            "old_value",
            "new_value",
            "created_at",
        ]
        read_only_fields = fields
