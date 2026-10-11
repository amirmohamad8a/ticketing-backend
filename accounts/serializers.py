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


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
        style={"input_type": "password"},
    )
    phone = PhoneField(
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
