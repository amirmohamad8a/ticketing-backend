from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view

from accounts.serializers import (
    PasswordChangeSerializer,
    TokenPairSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from core.serializers import DownloadLinkSerializer

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

user_schema = extend_schema_view(
    list=extend_schema(tags=["Users"]),
    retrieve=extend_schema(tags=["Users"]),
    create=extend_schema(
        tags=["Users"],
        request=UserCreateSerializer,
        responses={201: UserSerializer},
    ),
    partial_update=extend_schema(
        tags=["Users"],
        request=UserUpdateSerializer,
        responses=UserSerializer,
    ),
)

agent_schema = extend_schema_view(get=extend_schema(tags=["Agents"]))

avatar_download_schema = extend_schema_view(
    get=extend_schema(
        tags=["Avatars"],
        parameters=[OpenApiParameter("pk", int, OpenApiParameter.PATH)],
        responses=DownloadLinkSerializer,
    )
)
