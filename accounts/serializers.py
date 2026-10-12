from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from accounts.models import User
from accounts.validators import normalize_phone, validate_iranian_mobile


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

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "phone", "avatar", "role"]
        read_only_fields = ["id", "username", "role"]

    def validate_phone(self, value):
        return value or None

    def validate_avatar(self, value):
        if value is None:
            return value
        if value.size > User.AVATAR_MAX_SIZE_BYTES:
            max_mb = User.AVATAR_MAX_SIZE_BYTES // (1024 * 1024)
            message = _("Avatar too large. Max size is %(max_mb)sMB.")
            raise serializers.ValidationError(message % {"max_mb": max_mb})
        extension = User.AVATAR_CONTENT_TYPES.get(getattr(value, "content_type", ""))
        if extension is None:
            raise serializers.ValidationError(_("Avatar must be a PNG, JPEG or WebP image."))
        value.name = f"avatar{extension}"
        return value

    def update(self, instance, validated_data):
        storage = instance.avatar.storage
        old_name = instance.avatar.name if instance.avatar else ""
        instance = super().update(instance, validated_data)
        if "avatar" in validated_data and old_name:
            new_name = instance.avatar.name if instance.avatar else ""
            if new_name != old_name:
                storage.delete(old_name)
        return instance


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
