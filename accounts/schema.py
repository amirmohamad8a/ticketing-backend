from drf_spectacular.utils import extend_schema, extend_schema_view

from accounts.serializers import PasswordChangeSerializer, TokenPairSerializer

auth_schema = extend_schema_view(post=extend_schema(tags=["Auth"]))

profile_schema = extend_schema_view(
    get=extend_schema(tags=["Auth"]),
    patch=extend_schema(tags=["Auth"]),
)

password_change_schema = extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        request=PasswordChangeSerializer,
        responses=TokenPairSerializer,
    )
)
