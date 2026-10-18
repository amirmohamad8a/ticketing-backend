import os

from django.http import Http404
from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.generics import CreateAPIView, ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.models import User
from accounts.pagination import UserCursorPagination
from accounts.permissions import STAFF_ROLES, IsAdmin, IsAgentOrAdmin, can_view_avatar
from accounts.schema import (
    agent_schema,
    auth_schema,
    avatar_download_schema,
    logout_schema,
    password_change_schema,
    profile_schema,
    user_schema,
)
from accounts.serializers import (
    AgentSerializer,
    PasswordChangeSerializer,
    ProfileSerializer,
    RegisterSerializer,
    StaffProfileSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from accounts.services import change_own_password, logout_user
from accounts.throttles import LoginUsernameThrottle
from core.downloads import build_download_link
from core.events import close_user_sockets

AVATAR_MIME_TYPES = {
    extension: content_type for content_type, extension in User.AVATAR_CONTENT_TYPES.items()
}


@auth_schema
class RegisterView(CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"


@profile_schema
class MeView(RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        request = getattr(self, "request", None)
        role = getattr(getattr(request, "user", None), "role", None)
        if role in STAFF_ROLES:
            return StaffProfileSerializer
        return ProfileSerializer

    def get_object(self):
        return self.request.user


@password_change_schema
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_change"

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = change_own_password(
            request.user,
            serializer.validated_data["new_password"],
            close_user_sockets_fn=close_user_sockets,
        )
        refresh = RefreshToken.for_user(user)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


@logout_schema
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout_user(
            request.data.get("refresh"),
            request.user,
            close_user_sockets_fn=close_user_sockets,
        )
        return Response(status=status.HTTP_205_RESET_CONTENT)


@auth_schema
class TaggedTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]
    throttle_scope = "login"


@auth_schema
class TaggedTokenRefreshView(TokenRefreshView):
    pass


@user_schema
class UserViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["role", "is_active"]
    pagination_class = UserCursorPagination
    http_method_names = ["get", "post", "patch", "head", "options"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "user_management"

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action == "partial_update":
            return UserUpdateSerializer
        return UserSerializer


@agent_schema
class AgentListView(ListAPIView):
    serializer_class = AgentSerializer
    permission_classes = [IsAgentOrAdmin]
    pagination_class = None
    queryset = User.objects.filter(
        is_active=True, role__in=[User.Role.AGENT, User.Role.ADMIN]
    ).order_by("first_name", "last_name", "username", "id")


@avatar_download_schema
class AvatarDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        owner = get_object_or_404(User, pk=pk)
        if not owner.avatar or not can_view_avatar(request.user, owner):
            raise Http404
        extension = os.path.splitext(owner.avatar.name)[1].lower()
        content_type = AVATAR_MIME_TYPES.get(extension, "application/octet-stream")
        return Response(build_download_link(request, owner.avatar, content_type))
