import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from accounts.events import record_user_event
from accounts.models import User
from accounts.tokens import blacklist_user_tokens
from accounts.validators import normalize_phone, validate_iranian_mobile
from core.uploads import ensure_content_matches
from realtime.events import close_user_sockets

logger = logging.getLogger(__name__)


class PhoneField(serializers.CharField):
    def to_internal_value(self, data):
        return normalize_phone(super().to_internal_value(data))


def build_phone_field():
    return PhoneField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=32,
        validators=[
            validate_iranian_mobile,
            UniqueValidator(
                queryset=User.objects.all(),
                message=_("A user with that phone number already exists."),
            ),
        ],
    )


def _flag(value):
    return "true" if value else "false"


class ActorMixin:
    def _get_actor(self):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if actor is not None and not actor.is_authenticated:
            return None
        return actor


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
        style={"input_type": "password"},
    )
    phone = build_phone_field()

    class Meta:
        model = User
        fields = ["id", "username", "password", "first_name", "last_name", "phone", "role"]
        read_only_fields = ["id", "role"]

    def validate_username(self, value):
        value = User.normalize_username(value)
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError(_("A user with that username already exists."))
        return value

    def validate_phone(self, value):
        return value or None

    def validate(self, attrs):
        candidate = User(
            username=attrs.get("username", ""),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(role=User.Role.CUSTOMER, **validated_data)


class ProfileSerializer(serializers.ModelSerializer):
    phone = build_phone_field()
    avatar_download_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "phone",
            "avatar",
            "avatar_download_url",
            "role",
        ]
        read_only_fields = ["id", "username", "role"]
        extra_kwargs = {"avatar": {"write_only": True}}

    def get_avatar_download_url(self, obj) -> str | None:
        if not obj.avatar:
            return None
        path = reverse("avatar-download", args=[obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path

    def validate_phone(self, value):
        return value or None

    def validate_avatar(self, value):
        if value is None:
            return value
        if value.size > User.AVATAR_MAX_SIZE_BYTES:
            max_mb = User.AVATAR_MAX_SIZE_BYTES // (1024 * 1024)
            message = _("Avatar too large. Max size is %(max_mb)sMB.")
            raise serializers.ValidationError(message % {"max_mb": max_mb})
        content_type = getattr(value, "content_type", "")
        extension = User.AVATAR_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise serializers.ValidationError(_("Avatar must be a PNG, JPEG or WebP image."))
        ensure_content_matches(value, content_type)
        value.name = f"avatar{extension}"
        return value

    def update(self, instance, validated_data):
        storage = instance.avatar.storage
        old_name = instance.avatar.name if instance.avatar else ""
        instance = super().update(instance, validated_data)
        if "avatar" in validated_data and old_name:
            new_name = instance.avatar.name if instance.avatar else ""
            if new_name != old_name:
                self._delete_old_avatar(storage, old_name)
        return instance

    @staticmethod
    def _delete_old_avatar(storage, name):
        try:
            storage.delete(name)
        except OSError:
            logger.warning(
                "Could not delete a replaced avatar file",
                extra={"avatar_name": name},
                exc_info=True,
            )


class StaffProfileSerializer(ProfileSerializer):
    class Meta(ProfileSerializer.Meta):
        fields = [*ProfileSerializer.Meta.fields, "max_concurrent_chats"]


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
        style={"input_type": "password"},
    )
    new_password = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(_("Wrong password."))
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": _("The new password must be different from the old one.")}
            )
        try:
            validate_password(attrs["new_password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "phone",
            "role",
            "is_active",
            "date_joined",
        ]
        read_only_fields = fields


class AgentSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "role"]
        read_only_fields = fields

    def get_name(self, obj) -> str:
        return obj.get_full_name() or obj.username


class UserCreateSerializer(ActorMixin, RegisterSerializer):
    role = serializers.ChoiceField(choices=User.Role.choices, default=User.Role.AGENT)

    class Meta(RegisterSerializer.Meta):
        fields = ["id", "username", "password", "first_name", "last_name", "phone", "role"]
        read_only_fields = ["id"]

    def create(self, validated_data):
        actor = self._get_actor()

        with transaction.atomic():
            user = User.objects.create_user(**validated_data)
            record_user_event(
                user=user,
                actor=actor,
                field_changed="created",
                old_value="",
                new_value=user.role,
            )

        return user

    def to_representation(self, instance):
        return UserSerializer(instance, context=self.context).data


class UserUpdateSerializer(ActorMixin, serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ["role", "is_active", "password"]

    def validate(self, attrs):
        user = self.instance
        actor = self._get_actor()

        if actor is not None and actor.pk == user.pk:
            errors = {}
            if "role" in attrs and attrs["role"] != user.role:
                errors["role"] = _("You cannot change your own role.")
            if "is_active" in attrs and not attrs["is_active"]:
                errors["is_active"] = _("You cannot deactivate your own account.")
            if "password" in attrs:
                errors["password"] = _(
                    "Use the password change endpoint to change your own password."
                )
            if errors:
                raise serializers.ValidationError(errors)

        if "password" in attrs:
            try:
                validate_password(attrs["password"], user)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def update(self, instance, validated_data):
        actor = self._get_actor()
        password = validated_data.pop("password", None)

        events = []
        deactivated = False
        close_sockets = False
        if "role" in validated_data and validated_data["role"] != instance.role:
            events.append(("role", instance.role, validated_data["role"]))
            close_sockets = True
        if "is_active" in validated_data and validated_data["is_active"] != instance.is_active:
            new_state = validated_data["is_active"]
            events.append(("is_active", _flag(instance.is_active), _flag(new_state)))
            deactivated = not new_state
            close_sockets = True
        if password is not None:
            events.append(("password", "", ""))
            close_sockets = True

        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if password is not None:
                instance.set_password(password)
                instance.save(update_fields=["password"])
            if password is not None or deactivated:
                blacklist_user_tokens(instance)
            for field_changed, old_value, new_value in events:
                record_user_event(
                    user=instance,
                    actor=actor,
                    field_changed=field_changed,
                    old_value=old_value,
                    new_value=new_value,
                )
            if close_sockets:
                close_user_sockets(instance.pk)

        return instance

    def to_representation(self, instance):
        return UserSerializer(instance, context=self.context).data
