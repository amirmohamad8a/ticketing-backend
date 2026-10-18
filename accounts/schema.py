from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_view,
)

from accounts.serializers import (
    LogoutSerializer,
    PasswordChangeSerializer,
    ProfileSerializer,
    StaffProfileSerializer,
    TokenPairSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from core.serializers import DownloadLinkSerializer

auth_schema = extend_schema_view(post=extend_schema(tags=["Auth"]))

logout_schema = extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        request=LogoutSerializer,
        responses={205: None},
    )
)

profile_response = PolymorphicProxySerializer(
    component_name="MeProfile",
    serializers=[ProfileSerializer, StaffProfileSerializer],
    resource_type_field_name=None,
)

profile_schema = extend_schema_view(
    get=extend_schema(tags=["Auth"], responses=profile_response),
    patch=extend_schema(
        tags=["Auth"],
        request=StaffProfileSerializer,
        responses=profile_response,
    ),
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
        parameters=[OpenApiParameter("id", int, OpenApiParameter.PATH)],
        responses=DownloadLinkSerializer,
    )
)
