import os

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.generics import CreateAPIView, ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
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
from accounts.throttles import LoginUsernameThrottle
from accounts.tokens import blacklist_user_tokens
from core.downloads import build_download_link
from realtime.events import close_user_sockets

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
        with transaction.atomic():
            user = serializer.save()
            blacklist_user_tokens(user)
            close_user_sockets(user.pk)
            refresh = RefreshToken.for_user(user)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


@logout_schema
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            raise ValidationError({"refresh": _("Refresh token is required.")})
        try:
            token = RefreshToken(refresh_token)
            with transaction.atomic():
                token.blacklist()
                close_user_sockets(request.user.pk)
        except TokenError:
            raise ValidationError({"refresh": _("Invalid or expired token.")})
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
