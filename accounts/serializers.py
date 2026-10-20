import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from accounts.models import User
from accounts.services import create_user, update_user
from core.events import close_user_sockets
from core.phone import build_phone_field
from core.uploads import AVATAR_UPLOAD_POLICY

logger = logging.getLogger(__name__)


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
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        return create_user(
            None,
            validated_data,
            record_created=False,
            role=User.Role.CUSTOMER,
        )


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
        return AVATAR_UPLOAD_POLICY.validate(value, max_size_bytes=User.AVATAR_MAX_SIZE_BYTES)

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
        except Exception:
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
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return attrs


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
        return create_user(self._get_actor(), validated_data)

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
                raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def update(self, instance, validated_data):
        return update_user(
            instance,
            self._get_actor(),
            validated_data,
            close_user_sockets_fn=close_user_sockets,
        )

    def to_representation(self, instance):
        return UserSerializer(instance, context=self.context).data
